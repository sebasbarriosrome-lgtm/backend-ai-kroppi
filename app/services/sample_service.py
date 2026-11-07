import httpx
from fastapi.concurrency import run_in_threadpool as hilo

from app.repository import sample_repository
from app.services import storage
from app.services.formatters import muestreo_json


async def crear_muestreo(user_id: str, plot_id: str, datos: dict) -> dict:
    m = await hilo(sample_repository.crear_muestreo, user_id, plot_id, datos)
    return muestreo_json(m)


async def listar_muestreos(user_id: str, plot_id: str, limit: int) -> list[dict]:
    muestreos = await hilo(sample_repository.listar_muestreos, user_id, plot_id, limit)
    return [muestreo_json(m) for m in muestreos]


async def actualizar_muestreo(user_id: str, sample_id: str, datos: dict) -> dict:
    m = await hilo(sample_repository.actualizar_muestreo, user_id, sample_id, datos)
    return muestreo_json(m)


async def eliminar_muestreo(http: httpx.AsyncClient, user_id: str, sample_id: str) -> None:
    rutas = await hilo(sample_repository.eliminar_muestreo, user_id, sample_id)
    for ruta in rutas:
        await storage.eliminar_imagen(http, ruta)
