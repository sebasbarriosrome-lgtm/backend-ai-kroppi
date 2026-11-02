from fastapi.concurrency import run_in_threadpool as hilo
import httpx

from app.repository import diagnosis_repository, plot_repository
from app.services.diagnosis_service import firmar_diagnosticos
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
    recientes = await hilo(diagnosis_repository.diagnosticos_de_lote, user_id, plot_id, 10)
    lote["recent_diagnostics"] = await firmar_diagnosticos(http, recientes)
    return lote_json(lote)


async def actualizar_lote(user_id: str, plot_id: str, cambios: dict) -> dict:
    return lote_json(await hilo(plot_repository.actualizar_lote, user_id, plot_id, cambios))
