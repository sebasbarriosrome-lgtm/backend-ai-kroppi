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
) -> list[dict]:
    query = (
        supabase_client.table("diagnostics")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
    )
    if plot_id:
        cargar_lote(user_id, plot_id)
        samples = (
            supabase_client.table("plot_samples")
            .select("id")
            .eq("plot_id", plot_id)
            .execute()
            .data
            or []
        )
        sample_ids = [sample["id"] for sample in samples]
        if not sample_ids:
            return []
        query = query.in_("plot_samples_id", sample_ids)
    filas = (
        query.range(desplazamiento, desplazamiento + limite - 1).execute().data or []
    )
    return [
        registro(d)
        for d in enriquecer_diagnosticos(filas)
    ]


def obtener_diagnostico(user_id: str, diagnostico_id: str) -> dict:
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
    return registro(enriquecer_diagnosticos(filas)[0])


def diagnosticos_de_lote(user_id: str, plot_id: str, limite: int = 10) -> list[dict]:
    cargar_lote(user_id, plot_id)
    return listar_diagnosticos(user_id, limite, 0, plot_id)
