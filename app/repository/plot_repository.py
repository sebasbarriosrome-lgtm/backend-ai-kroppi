from uuid import uuid4

from app.core.exceptions import ReglaNegocio
from app.db.session import supabase_client
from app.repository.helpers import cargar_cultivo, cargar_lote, lote, muestreo, tipo


def crear_lote(user_id: str, crop_id: str, datos: dict) -> dict:
    crop = cargar_cultivo(user_id, crop_id)
    if not crop["is_active"]:
        raise ReglaNegocio(400, "El cultivo está archivado.")

    payload = {
        "id": str(uuid4()),
        "crop_id": crop_id,
        "name": datos["name"].strip(),
        "area_ha": datos["area_ha"],
        "plant_count": datos.get("plant_count"),
        "variety": datos.get("variety"),
        "latitude": datos.get("latitude"),
        "longitude": datos.get("longitude"),
        "status": "HEALTHY",
    }
    supabase_client.table("plots").insert(payload).execute()
    return lote(cargar_lote(user_id, payload["id"]))


def listar_lotes(user_id: str, crop_id: str) -> list[dict]:
    cargar_cultivo(user_id, crop_id)
    filas = (
        supabase_client.table("plots")
        .select("*")
        .eq("crop_id", crop_id)
        .order("name")
        .execute()
        .data
        or []
    )
    return [lote(p) for p in filas]


def obtener_lote(user_id: str, plot_id: str) -> dict:
    p = cargar_lote(user_id, plot_id)
    muestras = (
        supabase_client.table("plot_samples")
        .select("*")
        .eq("plot_id", plot_id)
        .order("sampled_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return {
        **lote(p),
        "crop": {"id": p["crop"]["id"], "name": p["crop"]["name"]},
        "crop_type": tipo(p["crop"]["crop_type"]),
        "last_sample": muestreo(muestras[0]) if muestras else None,
    }


def actualizar_lote(user_id: str, plot_id: str, cambios: dict) -> dict:
    actual = cargar_lote(user_id, plot_id)
    latitud = cambios.get("latitude", actual.get("latitude"))
    longitud = cambios.get("longitude", actual.get("longitude"))
    if (latitud is None) != (longitud is None):
        raise ReglaNegocio(400, "Envía latitude y longitude juntas, o ninguna.")

    payload = {
        key: value.strip() if key == "name" and value is not None else value
        for key, value in cambios.items()
        if key in {"name", "area_ha", "plant_count", "variety", "latitude", "longitude"}
        and not (key == "name" and value is None)
        and not (key == "area_ha" and value is None)
    }
    if payload:
        filas = (
            supabase_client.table("plots")
            .update(payload)
            .eq("id", plot_id)
            .select("id")
            .execute()
            .data
            or []
        )
        if not filas:
            raise ReglaNegocio(404, "Lote no encontrado.")
    return lote(cargar_lote(user_id, plot_id))


def tipo_del_lote(user_id: str, plot_id: str) -> str:
    return cargar_lote(user_id, plot_id)["crop"]["crop_type_id"]
