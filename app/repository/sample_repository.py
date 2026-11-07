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


def _muestreo_propio(user_id: str, sample_id: str) -> tuple[dict, dict]:
    filas = (
        supabase_client.table("plot_samples")
        .select("*")
        .eq("id", sample_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not filas:
        raise ReglaNegocio(404, "Muestreo no encontrado.")
    return filas[0], cargar_lote(user_id, filas[0]["plot_id"])


def _estado(m: dict, crop_type: dict) -> str:
    incidencia = round(m["plants_affected"] / m["plants_evaluated"] * 100, 2)
    return calcular_estado(
        incidencia, crop_type["alert_threshold_pct"], crop_type["danger_threshold_pct"]
    )


def _sincronizar_lote(lote: dict) -> None:
    """Estado y fecha del lote según su muestreo más reciente."""
    ultimo = (
        supabase_client.table("plot_samples")
        .select("*")
        .eq("plot_id", lote["id"])
        .order("sampled_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    cambios = (
        {
            "status": _estado(ultimo[0], lote["crop"]["crop_type"]),
            "last_sampled_at": ultimo[0]["sampled_at"],
        }
        if ultimo
        else {"status": "HEALTHY", "last_sampled_at": None}
    )
    supabase_client.table("plots").update(cambios).eq("id", lote["id"]).execute()


def actualizar_muestreo(user_id: str, sample_id: str, datos: dict) -> dict:
    actual, lote = _muestreo_propio(user_id, sample_id)
    evaluadas = datos.get("plants_evaluated", actual["plants_evaluated"])
    afectadas = datos.get("plants_affected", actual["plants_affected"])
    if afectadas > evaluadas:
        raise ReglaNegocio(400, "Las plantas afectadas no pueden superar las evaluadas.")

    payload = {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in datos.items()
    }
    respuesta = actual
    if payload:
        respuesta = (
            supabase_client.table("plot_samples")
            .update(payload)
            .eq("id", sample_id)
            .execute()
            .data
            or [None]
        )[0]
        if respuesta is None:
            raise RuntimeError("Supabase no devolvió el muestreo actualizado.")

    _sincronizar_lote(lote)
    estado = _estado(respuesta, lote["crop"]["crop_type"])
    return {
        **muestreo(respuesta, estado),
        "incidence_pct": respuesta.get(
            "incidence_pct", round(afectadas / evaluadas * 100, 2)
        ),
    }


def eliminar_muestreo(user_id: str, sample_id: str) -> list[str]:
    """Borra el muestreo y sus diagnósticos. Devuelve las rutas de imagen a limpiar."""
    _, lote = _muestreo_propio(user_id, sample_id)
    diagnosticos = (
        supabase_client.table("diagnostics")
        .select("id,image_url")
        .eq("plot_samples_id", sample_id)
        .execute()
        .data
        or []
    )
    if diagnosticos:
        supabase_client.table("diagnostics").delete().eq(
            "plot_samples_id", sample_id
        ).execute()
    supabase_client.table("plot_samples").delete().eq("id", sample_id).execute()
    _sincronizar_lote(lote)
    return [d["image_url"] for d in diagnosticos if d.get("image_url")]
