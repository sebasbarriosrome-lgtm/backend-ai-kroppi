from datetime import datetime

from app.core.exceptions import ReglaNegocio
from app.db.session import supabase_client
from app.repository.helpers import cargar_lote, enriquecer_diagnosticos, registro


def contexto_muestreo(user_id: str, plot_samples_id: str) -> dict:
    filas = (
        supabase_client.table("plot_samples")
        .select("id,plot_id")
        .eq("id", plot_samples_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not filas:
        raise ReglaNegocio(404, "Muestreo no encontrado.")
    lote = cargar_lote(user_id, filas[0]["plot_id"])
    return {
        "plot_id": filas[0]["plot_id"],
        "crop_type": lote["crop"]["crop_type"],
    }


def guardar_diagnostico(datos: dict) -> None:
    payload = {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in datos.items()
    }
    supabase_client.table("diagnostics").insert(payload).execute()


def listar_diagnosticos(
    user_id: str,
    limite: int,
    desplazamiento: int,
    plot_id: str | None = None,
    desde: str | None = None,
) -> list[dict]:
    columns = "*"
    if plot_id:
        cargar_lote(user_id, plot_id)
        columns = "*,plot_samples!inner(plot_id)"
    query = (
        supabase_client.table("diagnostics")
        .select(columns)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
    )
    if desde is not None:
        query = query.gte("created_at", desde)
    if plot_id:
        query = query.eq("plot_samples.plot_id", plot_id)
    filas = (
        query.range(desplazamiento, desplazamiento + limite - 1).execute().data or []
    )
    return [
        registro(d)
        for d in enriquecer_diagnosticos(filas)
    ]


def obtener_diagnostico(user_id: str, diagnostico_id: str, desde: str | None = None) -> dict:
    filas = (
        supabase_client.table("diagnostics")
        .select("*")
        .eq("id", diagnostico_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not filas:
        raise ReglaNegocio(404, "Diagnóstico no encontrado.")
    if desde is not None and datetime.fromisoformat(filas[0]["created_at"]) < datetime.fromisoformat(desde):
        raise ReglaNegocio(403, "El historial completo de diagnósticos requiere Premium.")
    return registro(enriquecer_diagnosticos(filas)[0])


def eliminar_diagnostico(user_id: str, diagnostico_id: str) -> str | None:
    """Borra un diagnóstico propio. Devuelve la ruta de su imagen para limpiarla."""
    filas = (
        supabase_client.table("diagnostics")
        .select("id,image_url")
        .eq("id", diagnostico_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not filas:
        raise ReglaNegocio(404, "Diagnóstico no encontrado.")
    supabase_client.table("diagnostics").delete().eq("id", diagnostico_id).execute()
    return filas[0].get("image_url")


def diagnosticos_de_lote(user_id: str, plot_id: str, limite: int = 10) -> list[dict]:
    return listar_diagnosticos(user_id, limite, 0, plot_id)
