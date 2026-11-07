import logging
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool as hilo

from app import config
from app.core.exceptions import ReglaNegocio
from app.repository import plot_modules_repository as repo
from app.repository import cosecha_perdida_repository
from app.services import cosecha_service, perdida_service, stats_service, storage
from app.services.perdidas_calculo import a_json, formato_kg, formato_moneda, normalizar_estimacion

log = logging.getLogger("kroppi.reports")
_BUCKET = "reports"
_DISCLAIMER = (
    "Resultados orientativos generados con apoyo de inteligencia artificial. "
    "Confirme con un agrónomo o técnico de campo."
)


def _disease_code(row: dict) -> str | None:
    prediction = row.get("ai_prediction") or {}
    code = row.get("predicted_label") or prediction.get("disease_code")
    if code:
        return code
    top = prediction.get("top") or []
    if top and float(top[0].get("confidence") or 0) >= config.MODEL_CONFIG["umbral"]:
        return top[0].get("disease_code")
    return None


async def datos_informe(
    http: httpx.AsyncClient, user_id: str, plot_id: str, start: date, end: date
) -> dict:
    if start > end:
        raise ReglaNegocio(400, "La fecha inicial debe ser anterior a la final.")
    plot = await hilo(repo.lote_propietario, user_id, plot_id)
    samples, care, harvests, losses = await _fetch(plot_id, start, end)
    diagnostics = (
        await hilo(
            repo.diagnosticos, user_id, [sample["id"] for sample in samples], start, end
        )
        if samples else []
    )
    stats = await stats_service.obtener(user_id, plot_id, start, end, "month")
    farm = plot["crop"]["farm"]
    crop = plot["crop"]
    crop_type = crop["crop_type"]

    disease_counts: Counter[str] = Counter()
    disease_periods: dict[tuple[str, str], int] = defaultdict(int)
    photos = []
    for diag in diagnostics:
        code = _disease_code(diag)
        if not code or code == config.CODIGO_SANO:
            continue
        disease_counts[code] += 1
        created_at = datetime.fromisoformat(str(diag["created_at"]).replace("Z", "+00:00"))
        period = created_at.astimezone(ZoneInfo("America/Bogota")).strftime("%Y-%m")
        disease_periods[(period, code)] += 1
        photos.append(diag)
    total = sum(disease_counts.values())
    disease_breakdown = [
        {"disease_code": code, "disease_name": config.ENFERMEDADES.get(code, {}).get("name", code),
         "count": count, "pct": round(count * 100 / total, 2) if total else 0}
        for code, count in disease_counts.most_common()
    ]
    disease_evolution = [
        {"period": period, "disease_code": code, "count": count}
        for (period, code), count in sorted(disease_periods.items())
    ]
    photos.sort(key=lambda row: float(row.get("confidence") or 0), reverse=True)
    photos = photos[:6]
    try:
        signed_photos = await storage.firmar_objetos(
            http, config.SUPABASE_BUCKET, [r["image_url"] for r in photos]
        )
    except (httpx.HTTPError, RuntimeError) as error:
        log.exception("No se pudieron firmar las fotos del informe")
        raise HTTPException(502, "No se pudieron preparar las fotos del informe.") from error
    sample_photos = [
        {"signed_url": signed_photos.get(r["image_url"]), "disease_name":
         config.ENFERMEDADES.get(_disease_code(r), {}).get("name", _disease_code(r)),
         "confidence": float(r.get("confidence") or 0), "taken_at": r["created_at"]}
        for r in photos if signed_photos.get(r["image_url"])
    ]
    care_urls = {}
    paths = [row["evidence_path"] for row in care[:10] if row.get("evidence_path")]
    if paths:
        try:
            care_urls = await storage.firmar_objetos(http, "care-evidence", paths)
        except (httpx.HTTPError, RuntimeError) as error:
            log.exception("No se pudieron firmar evidencias del informe")
            raise HTTPException(502, "No se pudieron preparar las evidencias del informe.") from error
    care_rows = [
        {
            "applied_at": row["applied_at"], "activity_type": row["activity_type"],
            "product_name": row.get("product_name"), "active_ingredient": row.get("active_ingredient"),
            "quantity": row.get("quantity"), "quantity_unit": row.get("quantity_unit"),
            "application_method": row.get("application_method"),
            "target_disease_name": config.ENFERMEDADES.get(row.get("target_disease_code"), {}).get("name"),
            "cost": row.get("cost"), "notes": row.get("notes"),
            "evidence_url": care_urls.get(row.get("evidence_path")),
        }
        for row in care
    ]
    harvest_rows = [cosecha_service.item(row) for row in harvests]
    production_totals = cosecha_service.totales(harvests)
    currency = stats["currency"]
    loss_summary = None
    if losses:
        # La estimación más reciente cuyo periodo toca el rango del informe.
        latest = max(losses, key=lambda e: (e["period_to"], str(e.get("created_at") or "")))
        loss_summary = {
            "estimation_id": latest["id"],
            "period_from": latest["period_from"].isoformat(),
            "period_to": latest["period_to"].isoformat(),
            "expected_kg": a_json(latest["expected_yield_kg"]),
            "harvested_kg": a_json(latest["harvested_kg"]),
            "lost_kg": a_json(latest["lost_kg"]),
            "loss_pct": a_json(latest["loss_pct"]),
            "loss_amount": a_json(latest["estimated_loss_amount"]),
            "currency": latest["currency"],
            "explanation": latest.get("explanation"),
            "estimations": [perdida_service.item(row) for row in losses],
        }
    samples_out = []
    for sample in samples:
        incidence = sample.get("incidence_pct")
        if incidence is None:
            incidence = round(sample["plants_affected"] * 100 / sample["plants_evaluated"], 2)
        status = stats_service._status(
            float(incidence), float(crop_type["alert_threshold_pct"]),
            float(crop_type["danger_threshold_pct"]),
        )
        samples_out.append({**sample, "incidence_pct": incidence, "status": status})
    avg = stats["totals"]["avg_incidence_pct"]
    disease_summary = ", ".join(f"{name}: {count}" for name, count in [
        (item["disease_name"], item["count"]) for item in disease_breakdown
    ]) or "no se detectó enfermedad"
    if not samples:
        summary_text = "No hay datos suficientes: no se registraron muestreos en este periodo."
        bullets = ["No se registraron muestreos en el periodo."]
    else:
        summary_text = (
            f"En la finca {farm['name']}, cultivo {crop['name']}, lote {plot['name']} "
            f"se realizaron {len(samples)} muestreos entre {start} y {end}, con una "
            f"incidencia promedio de {avg:g} %. Se detectaron: {disease_summary}. "
            f"Se aplicaron {len(care)} cuidados con un costo de "
            f"{formato_moneda(Decimal(str(stats['totals']['care_cost_cop'])), 'COP')} COP. "
            f"Se cosecharon {formato_kg(Decimal(str(stats['totals']['harvested_kg'])))}."
        )
        bullets = []
        series = stats["incidence_series"]
        if len(series) >= 2:
            change = series[-1]["incidence_pct"] - series[0]["incidence_pct"]
            trend = "subió" if change > 1 else "bajó" if change < -1 else "se mantuvo estable"
            bullets.append(f"La incidencia {trend} ({series[0]['incidence_pct']:g} % a {series[-1]['incidence_pct']:g} %).")
        if stats["harvests_without_price"]:
            bullets.append(f"Hay {stats['harvests_without_price']} cosecha(s) sin precio registrado.")
    return {
        "generated_at": datetime.now(ZoneInfo("America/Bogota")).isoformat(),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "identification": {
            "farm": {"id": farm["id"], "name": farm["name"], "department": farm.get("department"),
                     "municipality": farm.get("municipality"), "area_ha": farm.get("area_ha")},
            "crop": {"id": crop["id"], "name": crop["name"], "type": crop_type["name"],
                     "planted_at": crop.get("planted_at"), "expected_harvest_at": crop.get("expected_harvest_at")},
            "plot": {"id": plot["id"], "name": plot["name"], "area_ha": plot["area_ha"],
                     "variety": plot.get("variety"), "plant_count": plot.get("plant_count"),
                     "status": {"HEALTHY": "sano", "ALERT": "alerta", "DANGER": "peligro"}.get(
                         plot.get("status"), plot.get("status")
                     )},
            "owner_name": (await hilo(repo.perfil, farm["owner_id"])).get("full_name", ""),
        },
        "samples": samples_out, "disease_breakdown": disease_breakdown,
        "disease_evolution": disease_evolution, "sample_photos": sample_photos,
        "care_activities": care_rows, "harvests": harvest_rows,
        "production": {"harvested_kg": stats["totals"]["harvested_kg"],
                       "revenue": stats["totals"]["revenue"], "currency": currency,
                       "by_currency": production_totals["by_currency"],
                       "harvests_without_price": stats["harvests_without_price"]},
        "losses": loss_summary,
        "costs": {"care_cost_cop": stats["totals"]["care_cost_cop"]},
        "chart_series": {"incidence": stats["incidence_series"],
                         "harvest": stats["harvest_series"], "loss_cumulative": stats["loss_series"],
                         "expected_vs_harvested": stats["expected_vs_harvested"]},
        "conclusions": {"summary_text": summary_text, "bullets": bullets, "disclaimer": _DISCLAIMER},
    }


async def _fetch(plot_id: str, start: date, end: date):
    import asyncio
    samples, care, harvests, estimations = await asyncio.gather(
        hilo(repo.muestreos, plot_id, start, end),
        hilo(repo.cuidados, plot_id, start, end),
        hilo(repo.cosechas, plot_id, start, end),
        hilo(cosecha_perdida_repository.estimaciones, plot_id),
    )
    # Estimaciones cuyo periodo toca el rango del informe (no por fecha de creación).
    estimations = [
        e for e in map(normalizar_estimacion, estimations)
        if e["period_from"] and e["period_to"]
        and e["period_from"] <= end and start <= e["period_to"]
    ]
    return samples, care, harvests, estimations


async def subir_informe(
    http: httpx.AsyncClient, user_id: str, plot_id: str, start: date, end: date,
    contenido: bytes, content_type: str | None,
) -> dict:
    await hilo(repo.lote_propietario, user_id, plot_id)
    if start > end:
        raise ReglaNegocio(400, "La fecha inicial debe ser anterior a la final.")
    if content_type != "application/pdf" or not contenido.startswith(b"%PDF"):
        raise HTTPException(400, "El archivo no es un PDF válido.")
    if len(contenido) > 15 * 1024 * 1024:
        raise HTTPException(413, "El PDF supera 15 MB.")
    report_id = str(uuid4())
    route = f"{user_id}/{plot_id}/{report_id}.pdf"
    report_data = await datos_informe(http, user_id, plot_id, start, end)
    summary = {
        "avg_incidence_pct": sum(
            float(sample["incidence_pct"]) for sample in report_data["samples"]
        ) / len(report_data["samples"]) if report_data["samples"] else 0,
        "harvested_kg": report_data["production"]["harvested_kg"],
        "loss": (
            {
                key: report_data["losses"].get(key)
                for key in ("expected_kg", "harvested_kg", "lost_kg", "loss_pct", "loss_amount_cop")
            }
            if report_data["losses"] is not None else None
        ),
        "samples": len(report_data["samples"]),
        "care_activities": len(report_data["care_activities"]),
    }
    try:
        await storage.subir_objeto(http, _BUCKET, route, contenido, "application/pdf")
    except httpx.HTTPError:
        log.exception("No se pudo guardar el archivo del informe")
        raise HTTPException(502, "No se pudo guardar el informe. Intenta de nuevo.")
    try:
        row = await hilo(repo.crear_informe, {
            "id": report_id, "plot_id": plot_id, "created_by": user_id,
            "period_from": start.isoformat(), "period_to": end.isoformat(),
            "file_path": route, "file_size_bytes": len(contenido), "summary": summary,
        })
    except Exception:
        try:
            await storage.eliminar_objeto(http, _BUCKET, route)
        except httpx.HTTPError:
            log.exception("No se pudo limpiar PDF tras fallar su registro")
        raise
    return row


async def listar_informes(user_id: str, plot_id: str) -> list[dict]:
    await hilo(repo.lote_propietario, user_id, plot_id)
    return await hilo(repo.informes, plot_id)


async def obtener_informe(http: httpx.AsyncClient, user_id: str, report_id: str) -> dict:
    row = await hilo(repo.informe_por_id, report_id)
    await hilo(repo.lote_propietario, user_id, row["plot_id"])
    try:
        url = await storage.firmar_objeto(http, _BUCKET, row["file_path"]) if row.get("file_path") else None
    except httpx.HTTPError as error:
        log.exception("No se pudo firmar el PDF %s", report_id)
        raise HTTPException(502, "No se pudo generar la URL temporal del informe.") from error
    return {**row, "file_url": url}


async def eliminar_informe(http: httpx.AsyncClient, user_id: str, report_id: str) -> None:
    row = await hilo(repo.informe_por_id, report_id)
    await hilo(repo.lote_propietario, user_id, row["plot_id"])
    if row.get("file_path"):
        await storage.eliminar_objeto(http, _BUCKET, row["file_path"])
    await hilo(repo.borrar_informe, report_id)
