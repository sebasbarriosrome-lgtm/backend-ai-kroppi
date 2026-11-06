from fastapi.concurrency import run_in_threadpool as hilo

from app.repository import crop_repository
from app.services.formatters import cultivo_json


async def listar_tipos() -> list[dict]:
    return await hilo(crop_repository.listar_tipos)


async def crear_cultivo(user_id: str, datos: dict) -> dict:
    return cultivo_json(await hilo(crop_repository.crear_cultivo, user_id, datos))


async def listar_cultivos(user_id: str, archivados: bool = False) -> list[dict]:
    cultivos = await hilo(crop_repository.listar_cultivos, user_id, archivados)
    return [cultivo_json(c) for c in cultivos]


async def obtener_cultivo(user_id: str, crop_id: str) -> dict:
    return cultivo_json(await hilo(crop_repository.obtener_cultivo, user_id, crop_id))


async def actualizar_cultivo(user_id: str, crop_id: str, cambios: dict) -> dict:
    return cultivo_json(await hilo(crop_repository.actualizar_cultivo, user_id, crop_id, cambios))


async def archivar_cultivo(user_id: str, crop_id: str) -> dict:
    return await actualizar_cultivo(user_id, crop_id, {"is_active": False})
