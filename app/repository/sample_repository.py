from datetime import datetime
from uuid import uuid4

from app.core.exceptions import ReglaNegocio
from app.db.session import supabase_client
from app.repository.helpers import calcular_estado, cargar_lote, muestreo


def crear_muestreo(user_id: str, plot_id: str, datos: dict) -> dict:
    lote = cargar_lote(user_id, plot_id)
    evaluadas = datos["plants_evaluated"]
    afectadas = datos["plants_affected"]
    if afectadas > evaluadas:
        raise ReglaNegocio(400, "Las plantas afectadas no pueden superar las evaluadas.")

    incidencia = round(afectadas / evaluadas * 100, 2)
    crop_type = lote["crop"]["crop_type"]
    estado = calcular_estado(
        incidencia, crop_type["alert_threshold_pct"], crop_type["danger_threshold_pct"]
    )
    sampled_at = datos["sampled_at"]
    if isinstance(sampled_at, datetime):
        sampled_at = sampled_at.isoformat()

    payload = {
        "id": str(uuid4()),
        "plot_id": plot_id,
        "sampled_by": user_id,
        "sampled_at": sampled_at,
        "method": datos.get("method", "SAMPLING"),
        "plants_evaluated": evaluadas,
        "plants_affected": afectadas,
        "notes": datos.get("notes"),
    }
    respuesta = (
        supabase_client.table("plot_samples")
        .insert(payload)
        .select("*")
        .execute()
        .data
        or []
    )
    if not respuesta:
        raise RuntimeError("Supabase no devolvió el muestreo creado.")

    supabase_client.table("plots").update(
        {"status": estado, "last_sampled_at": sampled_at}
    ).eq("id", plot_id).execute()

    return {
        **muestreo(respuesta[0], estado),
        "incidence_pct": respuesta[0].get("incidence_pct", incidencia),
    }


def listar_muestreos(user_id: str, plot_id: str, limite: int = 50) -> list[dict]:
    cargar_lote(user_id, plot_id)
    filas = (
        supabase_client.table("plot_samples")
        .select("*")
        .eq("plot_id", plot_id)
        .order("sampled_at", desc=True)
        .limit(limite)
        .execute()
        .data
        or []
    )
    return [muestreo(m) for m in reversed(filas)]
