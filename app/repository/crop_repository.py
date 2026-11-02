from uuid import uuid4

from app.core.exceptions import ReglaNegocio
from app.db.session import supabase_client
from app.repository.helpers import cargar_cultivo, cultivo, fincas_del_usuario, tipo


def _fecha_iso(valor):
    return valor.isoformat() if hasattr(valor, "isoformat") else valor


def _enriquecer_cultivos(cultivos: list[dict]) -> list[dict]:
    if not cultivos:
        return []

    crop_ids = [c["id"] for c in cultivos]
    crop_type_ids = list({c["crop_type_id"] for c in cultivos})
    tipos = (
        supabase_client.table("crop_types")
        .select("*")
        .in_("id", crop_type_ids)
        .execute()
        .data
        or []
    )
    plots = (
        supabase_client.table("plots")
        .select("*")
        .in_("crop_id", crop_ids)
        .execute()
        .data
        or []
    )
    tipos_por_id = {t["id"]: t for t in tipos}
    lotes_por_cultivo: dict[str, list[dict]] = {crop_id: [] for crop_id in crop_ids}
    for plot in plots:
        lotes_por_cultivo[plot["crop_id"]].append(plot)

    for c in cultivos:
        c["crop_type"] = tipos_por_id.get(c["crop_type_id"])
        if c["crop_type"] is None:
            raise RuntimeError(f"No existe el tipo de cultivo {c['crop_type_id']}.")
        c["plots"] = lotes_por_cultivo[c["id"]]
    return cultivos


def listar_tipos() -> list[dict]:
    filas = (
        supabase_client.table("crop_types")
        .select("*")
        .eq("is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )
    return [tipo(t) for t in filas]


def tipo_por_slug(slug: str) -> dict | None:
    filas = (
        supabase_client.table("crop_types")
        .select("*")
        .eq("slug", slug)
        .eq("is_active", True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return tipo(filas[0]) if filas else None


def crear_cultivo(user_id: str, datos: dict) -> dict:
    farm_id = str(datos["farm_id"])
    farm = (
        supabase_client.table("farms")
        .select("id")
        .eq("id", farm_id)
        .eq("owner_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not farm:
        raise ReglaNegocio(404, "Finca no encontrada.")

    crop_type = (
        supabase_client.table("crop_types")
        .select("id,is_active")
        .eq("id", str(datos["crop_type_id"]))
        .limit(1)
        .execute()
        .data
        or []
    )
    if not crop_type or not crop_type[0]["is_active"]:
        raise ReglaNegocio(400, "Tipo de cultivo no válido.")

    creado = {
        "id": str(uuid4()),
        "farm_id": farm_id,
        "crop_type_id": str(datos["crop_type_id"]),
        "name": datos["name"].strip(),
        "planted_at": _fecha_iso(datos.get("planted_at")),
        "expected_harvest_at": _fecha_iso(datos.get("expected_harvest_at")),
        "is_active": True,
    }
    supabase_client.table("crops").insert(creado).execute()
    return cultivo(cargar_cultivo(user_id, creado["id"]))


def listar_cultivos(user_id: str, archivados: bool = False) -> list[dict]:
    farm_ids = fincas_del_usuario(user_id)
    if not farm_ids:
        return []
    filas = (
        supabase_client.table("crops")
        .select("*")
        .in_("farm_id", farm_ids)
        .eq("is_active", not archivados)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    return [cultivo(c) for c in _enriquecer_cultivos(filas)]


def obtener_cultivo(user_id: str, crop_id: str) -> dict:
    return cultivo(cargar_cultivo(user_id, crop_id))


def actualizar_cultivo(user_id: str, crop_id: str, cambios: dict) -> dict:
    c = cargar_cultivo(user_id, crop_id)
    if cambios.get("name") is not None:
        cambios["name"] = cambios["name"].strip()
    planted_at = _fecha_iso(cambios.get("planted_at", c.get("planted_at")))
    harvest_at = _fecha_iso(
        cambios.get("expected_harvest_at", c.get("expected_harvest_at"))
    )
    if planted_at and harvest_at and harvest_at < planted_at:
        raise ReglaNegocio(400, "La cosecha estimada no puede ser anterior a la siembra.")

    payload = {
        key: _fecha_iso(value) if key in {"planted_at", "expected_harvest_at"} else value
        for key, value in cambios.items()
        if key in {"name", "planted_at", "expected_harvest_at", "is_active"}
        and value is not None
    }
    if payload:
        filas = (
            supabase_client.table("crops")
            .update(payload)
            .eq("id", crop_id)
            .select("id")
            .execute()
            .data
            or []
        )
        if not filas:
            raise ReglaNegocio(404, "Cultivo no encontrado.")
    return cultivo(cargar_cultivo(user_id, crop_id))
