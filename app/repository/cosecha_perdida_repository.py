from datetime import date
from decimal import Decimal

from app.core.exceptions import ReglaNegocio
from app.db.session import supabase_client


def _serializar(datos: dict) -> dict:
    return {
        key: str(value) if isinstance(value, Decimal)
        else value.isoformat() if hasattr(value, "isoformat")
        else value
        for key, value in datos.items()
    }


def _uno(tabla: str, registro_id: str, mensaje: str) -> dict:
    rows = supabase_client.table(tabla).select("*").eq("id", registro_id).limit(1).execute().data or []
    if not rows:
        raise ReglaNegocio(404, mensaje)
    return rows[0]


# ---------------- Cosechas ----------------

def cosechas(
    plot_id: str, desde: date | None = None, hasta: date | None = None,
    limite: int | None = None, offset: int = 0,
) -> list[dict]:
    """Cosechas del lote, `harvested_at` descendente; límites de fecha inclusivos."""
    query = supabase_client.table("harvests").select("*").eq("plot_id", plot_id)
    if desde:
        query = query.gte("harvested_at", desde.isoformat())
    if hasta:
        query = query.lte("harvested_at", hasta.isoformat())
    query = query.order("harvested_at", desc=True).order("created_at", desc=True)
    if limite is not None:
        query = query.range(offset, offset + limite - 1)
    return query.execute().data or []


def cosecha_por_id(harvest_id: str) -> dict:
    return _uno("harvests", harvest_id, "Cosecha no encontrada.")


def crear_cosecha(datos: dict) -> dict:
    rows = supabase_client.table("harvests").insert(_serializar(datos)).execute().data or []
    if not rows:
        raise RuntimeError("Supabase no devolvió la cosecha creada.")
    return rows[0]


def actualizar_cosecha(harvest_id: str, datos: dict) -> dict:
    rows = (
        supabase_client.table("harvests").update(_serializar(datos))
        .eq("id", harvest_id).execute().data or []
    )
    if not rows:
        raise ReglaNegocio(404, "Cosecha no encontrada.")
    return rows[0]


def borrar_cosecha(harvest_id: str) -> None:
    supabase_client.table("harvests").delete().eq("id", harvest_id).execute()


# ---------------- Estimaciones de pérdida ----------------

def estimaciones(plot_id: str, limite: int | None = None, offset: int = 0) -> list[dict]:
    """Estimaciones del lote, la más reciente primero."""
    query = (
        supabase_client.table("loss_estimations").select("*").eq("plot_id", plot_id)
        .order("created_at", desc=True)
    )
    if limite is not None:
        query = query.range(offset, offset + limite - 1)
    return query.execute().data or []


def estimacion_por_id(estimation_id: str) -> dict:
    return _uno("loss_estimations", estimation_id, "Estimación no encontrada.")


def crear_estimacion(datos: dict) -> dict:
    rows = supabase_client.table("loss_estimations").insert(_serializar(datos)).execute().data or []
    if not rows:
        raise RuntimeError("Supabase no devolvió la estimación creada.")
    return rows[0]


def actualizar_estimacion(estimation_id: str, datos: dict) -> dict:
    rows = (
        supabase_client.table("loss_estimations").update(_serializar(datos))
        .eq("id", estimation_id).execute().data or []
    )
    if not rows:
        raise ReglaNegocio(404, "Estimación no encontrada.")
    return rows[0]


def borrar_estimacion(estimation_id: str) -> None:
    supabase_client.table("loss_estimations").delete().eq("id", estimation_id).execute()
