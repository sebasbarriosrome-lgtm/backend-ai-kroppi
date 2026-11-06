from app import config
from app.core.exceptions import ReglaNegocio
from app.db.session import supabase_client


def calcular_estado(incidencia: float, alerta: float, peligro: float) -> str:
    if incidencia >= peligro:
        return "DANGER"
    if incidencia >= alerta:
        return "ALERT"
    return "HEALTHY"


def tipo(t: dict) -> dict:
    return {
        "id": t["id"],
        "name": t["name"],
        "scientific_name": t.get("scientific_name"),
        "icon_url": t.get("icon_url"),
        "is_active": t.get("is_active"),
        "slug": t.get("slug"),
        "alert_threshold_pct": t["alert_threshold_pct"],
        "danger_threshold_pct": t["danger_threshold_pct"],
        "avg_yield_kg_per_ha": t.get("avg_yield_kg_per_ha"),
        "created_at": t.get("created_at"),
    }


def lote(p: dict) -> dict:
    return {
        "id": p["id"],
        "crop_id": p["crop_id"],
        "name": p["name"],
        "area_ha": p["area_ha"],
        "plant_count": p.get("plant_count"),
        "variety": p.get("variety"),
        "latitude": p.get("latitude"),
        "longitude": p.get("longitude"),
        "status": p["status"],
        "last_sampled_at": p.get("last_sampled_at"),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
    }


def cultivo(c: dict) -> dict:
    plots = c.get("plots", [])
    estados = [p["status"] for p in plots]
    return {
        "id": c["id"],
        "farm_id": c["farm_id"],
        "name": c["name"],
        "planted_at": c.get("planted_at"),
        "expected_harvest_at": c.get("expected_harvest_at"),
        "is_active": c["is_active"],
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
        "crop_type": tipo(c["crop_type"]),
        "plots_summary": {
            "total": len(estados),
            "healthy": estados.count("HEALTHY"),
            "alert": estados.count("ALERT"),
            "danger": estados.count("DANGER"),
            "total_area_ha": round(sum(p["area_ha"] for p in plots), 2),
        },
    }


def muestreo(m: dict, estado: str | None = None) -> dict:
    return {
        "id": m["id"],
        "plot_id": m["plot_id"],
        "sampled_by": m.get("sampled_by"),
        "sampled_at": m["sampled_at"],
        "method": m["method"],
        "plants_evaluated": m["plants_evaluated"],
        "plants_affected": m["plants_affected"],
        "incidence_pct": m.get("incidence_pct"),
        "notes": m.get("notes"),
        "status": estado,
    }


def registro(x: dict) -> dict:
    ia = x.get("ai_prediction") or {}
    codigo = x.get("predicted_label")
    return {
        "id": x["id"],
        "image_path": x["image_url"],
        "plot_samples_id": x["plot_samples_id"],
        "created_at": x["created_at"],
        "model_version": ia.get("model_version", ""),
        "confidence": float(x.get("confidence") if x.get("confidence") is not None else ia.get("confidence", 0.0)),
        "top": ia.get("top", []),
        "recommendations": x.get("recommendations") or ia.get("recommendations", []),
        "crop": tipo(x["crop_type"]),
        "plot_id": x.get("plot_id"),
        "disease": config.ENFERMEDADES.get(codigo) if codigo else None,
    }


def _obtener_uno(tabla: str, **filtros: str) -> dict | None:
    query = supabase_client.table(tabla).select("*")
    for campo, valor in filtros.items():
        query = query.eq(campo, valor)
    filas = query.limit(1).execute().data or []
    return filas[0] if filas else None


def cargar_cultivo(user_id: str, crop_id: str) -> dict:
    c = _obtener_uno("crops", id=crop_id)
    if c is None:
        raise ReglaNegocio(404, "Cultivo no encontrado.")

    farm = _obtener_uno("farms", id=c["farm_id"], owner_id=user_id)
    if farm is None:
        raise ReglaNegocio(404, "Cultivo no encontrado.")
    c["farm"] = farm

    crop_type = _obtener_uno("crop_types", id=c["crop_type_id"])
    if crop_type is None:
        raise RuntimeError(f"No existe el tipo de cultivo {c['crop_type_id']}.")
    c["crop_type"] = crop_type
    c["plots"] = (
        supabase_client.table("plots")
        .select("*")
        .eq("crop_id", crop_id)
        .execute()
        .data
        or []
    )
    return c


def fincas_del_usuario(user_id: str) -> list[str]:
    filas = (
        supabase_client.table("farms")
        .select("id")
        .eq("owner_id", user_id)
        .execute()
        .data
        or []
    )
    return [f["id"] for f in filas]


def cargar_lote(user_id: str, plot_id: str) -> dict:
    p = _obtener_uno("plots", id=plot_id)
    if p is None:
        raise ReglaNegocio(404, "Lote no encontrado.")

    c = cargar_cultivo(user_id, p["crop_id"])
    p["crop"] = c
    return p


def enriquecer_diagnosticos(diagnosticos: list[dict]) -> list[dict]:
    if not diagnosticos:
        return []

    sample_ids = list(
        {d["plot_samples_id"] for d in diagnosticos if d.get("plot_samples_id")}
    )
    samples = []
    if sample_ids:
        samples = (
            supabase_client.table("plot_samples")
            .select("id,plot_id")
            .in_("id", sample_ids)
            .execute()
            .data
            or []
        )
    samples_by_id = {sample["id"]: sample for sample in samples}

    plot_ids = list({sample["plot_id"] for sample in samples})
    plots = []
    if plot_ids:
        plots = (
            supabase_client.table("plots")
            .select("id,crop_id")
            .in_("id", plot_ids)
            .execute()
            .data
            or []
        )
    plots_by_id = {plot["id"]: plot for plot in plots}

    crop_ids = list({plot["crop_id"] for plot in plots})
    crops = []
    if crop_ids:
        crops = (
            supabase_client.table("crops")
            .select("id,crop_type_id")
            .in_("id", crop_ids)
            .execute()
            .data
            or []
        )
    crops_by_id = {crop["id"]: crop for crop in crops}
    crop_type_ids = list({crop["crop_type_id"] for crop in crops})
    types = []
    if crop_type_ids:
        types = (
            supabase_client.table("crop_types")
            .select("*")
            .in_("id", crop_type_ids)
            .execute()
            .data
            or []
        )
    types_by_id = {crop_type["id"]: crop_type for crop_type in types}

    for diagnosis in diagnosticos:
        sample = samples_by_id.get(diagnosis.get("plot_samples_id"))
        if sample is None:
            raise RuntimeError(
                f"No existe el muestreo {diagnosis.get('plot_samples_id')} del diagnóstico."
            )
        diagnosis["plot_id"] = sample["plot_id"] if sample else None
        plot = plots_by_id.get(sample["plot_id"])
        if plot is None:
            raise RuntimeError(f"No existe el lote {sample['plot_id']} del muestreo.")
        crop = crops_by_id.get(plot["crop_id"]) if plot else None
        if crop is None:
            raise RuntimeError(f"No existe el cultivo {plot['crop_id']} del lote.")
        crop_type = types_by_id.get(crop["crop_type_id"])
        if crop_type is None:
            raise RuntimeError(f"No existe el tipo de cultivo {crop['crop_type_id']}.")
        diagnosis["crop_type"] = crop_type
    return diagnosticos
