from fastapi.concurrency import run_in_threadpool as hilo
import httpx

from app.repository import plot_repository
from app.services.diagnosis_service import listar_diagnosticos
from app.services.formatters import lote_json, muestreo_json


async def crear_lote(user_id: str, crop_id: str, datos: dict) -> dict:
    return lote_json(await hilo(plot_repository.crear_lote, user_id, crop_id, datos))


async def listar_lotes(user_id: str, crop_id: str) -> list[dict]:
    lotes = await hilo(plot_repository.listar_lotes, user_id, crop_id)
    return [lote_json(p) for p in lotes]


async def obtener_lote(user_id: str, plot_id: str, http: httpx.AsyncClient) -> dict:
    lote = await hilo(plot_repository.obtener_lote, user_id, plot_id)
    if lote["last_sample"]:
        muestreo_json(lote["last_sample"])
    lote["recent_diagnostics"] = await listar_diagnosticos(http, user_id, 10, 0, plot_id)
    return lote_json(lote)


async def actualizar_lote(user_id: str, plot_id: str, cambios: dict) -> dict:
    return lote_json(await hilo(plot_repository.actualizar_lote, user_id, plot_id, cambios))
