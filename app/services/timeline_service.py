from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.concurrency import run_in_threadpool as hilo

from app import config
from app.core.exceptions import ReglaNegocio
from app.repository import plot_modules_repository as repo
from app.services import stats_service

_BOGOTA = ZoneInfo("America/Bogota")
_TIPOS = {"sample", "diagnosis", "care", "harvest", "loss", "report"}


def _fecha(value: str | datetime | date, time_only: bool = False) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min, tzinfo=_BOGOTA)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_BOGOTA)
    parsed = parsed.astimezone(_BOGOTA)
    if time_only:
        return datetime.combine(parsed.date(), time.min, tzinfo=_BOGOTA)
    return parsed


def _event(
    identifier: str, kind: str, occurred_at: datetime, title: str,
    subtitle: str | None, ref_table: str, ref_id: str, data: dict | None = None,
    severity: str | None = None,
) -> dict:
    return {
        "id": identifier,
        "type": kind,
        "occurred_at": occurred_at.isoformat(),
        "title": title,
        "subtitle": subtitle,
        "severity": severity,
        "ref": {"table": ref_table, "id": ref_id},
        "data": data or {},
    }


async def obtener(
    user_id: str, plot_id: str, desde: date, hasta: date,
    types: list[str], limite: int, before: datetime | None,
) -> dict:
    invalid = set(types) - _TIPOS
    if invalid:
        raise ReglaNegocio(400, "Uno o más tipos de evento no son válidos.")
    if desde > hasta:
        raise ReglaNegocio(400, "La fecha inicial debe ser anterior a la final.")
    plot = await hilo(repo.lote_propietario, user_id, plot_id)
    threshold = plot["crop"]["crop_type"]
    tasks = {}
    if "sample" in types or "diagnosis" in types:
        tasks["samples"] = hilo(repo.muestreos, plot_id, desde, hasta)
    for kind, field in (
        ("care", "care"), ("harvest", "harvest"), ("loss", "loss"),
    ):
        if kind in types:
            tasks[field] = hilo(
                {"care": repo.cuidados, "harvest": repo.cosechas, "loss": repo.perdidas}[kind],
                plot_id, desde, hasta,
            )
    if "report" in types:
        tasks["reports"] = hilo(repo.informes_periodo, plot_id, desde, hasta, 200)
    import asyncio
    fetched = await asyncio.gather(*tasks.values()) if tasks else []
    data = dict(zip(tasks.keys(), fetched))
    samples = data.get("samples", [])
    diagnostics = (
        await hilo(
            repo.diagnosticos, user_id, [s["id"] for s in samples], desde, hasta
        )
        if "diagnosis" in types and samples else []
    )
    historical_diagnostics = []
    if "diagnosis" in types:
        historical_ids = await hilo(repo.ids_muestreos, plot_id)
        historical_diagnostics = await hilo(
            repo.diagnosticos_historial, user_id, historical_ids
        )

    events: list[dict] = []
    if "sample" in types:
        for sample in samples:
            evaluated = int(sample["plants_evaluated"])
            affected = int(sample["plants_affected"])
            incidence = sample.get("incidence_pct")
            incidence = float(incidence) if incidence is not None else round(affected * 100 / evaluated, 2)
            status = stats_service._status(
                incidence, float(threshold["alert_threshold_pct"]),
                float(threshold["danger_threshold_pct"]),
            )
            events.append(_event(
                sample["id"], "sample", _fecha(sample["sampled_at"]),
                f"Muestreo: {affected} de {evaluated} plantas afectadas ({incidence:g} %)",
                sample.get("method"), "plot_samples", sample["id"],
                {"incidence_pct": incidence, "plants_evaluated": evaluated, "plants_affected": affected},
                status,
            ))
    if "diagnosis" in types:
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for diagnosis in diagnostics:
            prediction = diagnosis.get("ai_prediction") or {}
            code = diagnosis.get("predicted_label") or prediction.get("disease_code")
            top = prediction.get("top") or []
            if not code and top and float(top[0].get("confidence") or 0) >= config.MODEL_CONFIG["umbral"]:
                code = top[0].get("disease_code")
            if code and code != config.CODIGO_SANO:
                grouped[(diagnosis["plot_samples_id"], code)].append(diagnosis)
        first_by_disease: dict[str, tuple[datetime, tuple[str, str]]] = {}
        for diagnosis in historical_diagnostics:
            prediction = diagnosis.get("ai_prediction") or {}
            code = diagnosis.get("predicted_label") or prediction.get("disease_code")
            top = prediction.get("top") or []
            if not code and top and float(top[0].get("confidence") or 0) >= config.MODEL_CONFIG["umbral"]:
                code = top[0].get("disease_code")
            if code and code != config.CODIGO_SANO:
                occurred = _fecha(diagnosis["created_at"])
                if code not in first_by_disease or occurred < first_by_disease[code][0]:
                    first_by_disease[code] = (occurred, (diagnosis["plot_samples_id"], code))
        for (sample_id, code), records in grouped.items():
            disease = config.ENFERMEDADES.get(code, {})
            occurred = min(_fecha(row["created_at"]) for row in records)
            first = first_by_disease.get(code, (None, None))[1] == (sample_id, code)
            events.append(_event(
                f"{sample_id}:{code}", "diagnosis", occurred,
                f"Detección de {disease.get('name', code)}",
                f"{len(records)} planta(s)", "plot_samples", sample_id,
                {"disease_code": code, "count": len(records), "first_detection": first,
                 "diagnosis_ids": [r["id"] for r in records]},
                "high" if any(float(r.get("confidence") or 0) >= 0.85 for r in records) else None,
            ))
    for row in data.get("care", []):
        description = row.get("product_name") or row["activity_type"].replace("_", " ").title()
        if row.get("quantity") is not None:
            description += f" · {row['quantity']} {row.get('quantity_unit', '')}".rstrip()
        events.append(_event(
            row["id"], "care", _fecha(row["applied_at"], True),
            f"{row['activity_type'].replace('_', ' ').title()}: {description}",
            row.get("target_disease_code"), "care_activities", row["id"],
            {
                "applied_at": row["applied_at"],
                "activity_type": row["activity_type"],
                "product_name": row.get("product_name"),
                "quantity": row.get("quantity"),
                "quantity_unit": row.get("quantity_unit"),
                "cost": row.get("cost"),
            },
        ))
    for row in data.get("harvest", []):
        kg = float(row["quantity_kg"])
        subtitle = f"${float(row['price_per_kg']) * kg:,.0f} COP" if row.get("price_per_kg") is not None else None
        events.append(_event(row["id"], "harvest", _fecha(row["harvested_at"], True),
            f"Cosecha: {kg:g} kg", subtitle, "harvests", row["id"],
            {"harvested_at": row["harvested_at"], "quantity_kg": kg,
             "price_per_kg": row.get("price_per_kg")}))
    for row in data.get("loss", []):
        inputs = row.get("inputs") or {}
        amount = float(row.get("estimated_loss_amount") or 0)
        lost = float(inputs.get("lost_kg") or 0)
        events.append(_event(row["id"], "loss", _fecha(row["created_at"]),
            f"Estimación de pérdidas: {lost:g} kg / ${amount:,.0f} COP",
            row.get("explanation"), "loss_estimations", row["id"],
            {"lost_kg": inputs.get("lost_kg"), "loss_pct": inputs.get("loss_pct"),
             "estimated_loss_amount": row.get("estimated_loss_amount"),
             "explanation": row.get("explanation")}))
    if "report" in types:
        for row in data.get("reports", []):
            occurred = _fecha(row["created_at"])
            if desde <= occurred.date() <= hasta:
                events.append(_event(
                    row["id"], "report", occurred, "Informe PDF generado",
                    f"{row['period_from']} – {row['period_to']}", "plot_reports", row["id"],
                    {"period_from": row["period_from"], "period_to": row["period_to"]},
                ))
    events = [event for event in events if desde <= _fecha(event["occurred_at"]).date() <= hasta]
    if before:
        boundary = _fecha(before)
        events = [event for event in events if _fecha(event["occurred_at"]) < boundary]
    events.sort(key=lambda event: (_fecha(event["occurred_at"]), event["type"]), reverse=True)
    page = events[:limite]
    if len(events) > limite and page:
        last_timestamp = _fecha(page[-1]["occurred_at"])
        while (
            len(page) < len(events)
            and _fecha(events[len(page)]["occurred_at"]) == last_timestamp
        ):
            page.append(events[len(page)])
    return {
        "items": page,
        "next_before": page[-1]["occurred_at"] if len(events) > len(page) and page else None,
    }
