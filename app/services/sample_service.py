from fastapi.concurrency import run_in_threadpool as hilo

from app.repository import sample_repository
from app.services.formatters import muestreo_json


async def crear_muestreo(user_id: str, plot_id: str, datos: dict) -> dict:
    m = await hilo(sample_repository.crear_muestreo, user_id, plot_id, datos)
    return muestreo_json(m)


async def listar_muestreos(user_id: str, plot_id: str, limit: int) -> list[dict]:
    muestreos = await hilo(sample_repository.listar_muestreos, user_id, plot_id, limit)
    return [muestreo_json(m) for m in muestreos]
