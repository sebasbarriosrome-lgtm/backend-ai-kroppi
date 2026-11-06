import io
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool as hilo
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import ReglaNegocio
from app.repository import plot_modules_repository as repo
from app.services import storage

log = logging.getLogger("kroppi.care")
_BUCKET = "care-evidence"
_MIME_FORMAT = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def _validar_fecha(fecha: date) -> None:
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha)
    if fecha > datetime.now(ZoneInfo("America/Bogota")).date():
        raise ReglaNegocio(400, "La fecha de aplicación no puede ser futura.")


def _validar_enfermedad(codigo: str | None) -> None:
    if codigo is not None:
        from app import config
        if codigo not in config.ENFERMEDADES or codigo == config.CODIGO_SANO:
            raise ReglaNegocio(400, "El código de enfermedad no existe.")


def _validar_registro(datos: dict) -> None:
    if datos.get("applied_at"):
        _validar_fecha(datos["applied_at"])
    if (datos.get("quantity") is None) != (datos.get("quantity_unit") is None):
        raise ReglaNegocio(400, "La cantidad y su unidad deben enviarse juntas.")
    _validar_enfermedad(datos.get("target_disease_code"))


def _serializar(row: dict, evidence_url: str | None = None) -> dict:
    return {**row, "evidence_url": evidence_url}


async def _con_url(http: httpx.AsyncClient, row: dict) -> dict:
    ruta = row.get("evidence_path")
    try:
        url = await storage.firmar_objeto(http, _BUCKET, ruta) if ruta else None
    except httpx.HTTPError as error:
        log.exception("No se pudo firmar la evidencia %s", ruta)
        raise HTTPException(502, "No se pudo generar la URL temporal de la evidencia.") from error
    return _serializar(row, url)


async def crear(user_id: str, plot_id: str, datos: dict) -> dict:
    await hilo(repo.lote_propietario, user_id, plot_id)
    _validar_registro(datos)
    row = await hilo(
        repo.crear_cuidado,
        {**datos, "plot_id": plot_id, "created_by": user_id},
    )
    return _serializar(row)


async def listar(
    http: httpx.AsyncClient, user_id: str, plot_id: str, desde: date | None, hasta: date | None,
    tipo: str | None, limite: int, offset: int,
) -> list[dict]:
    await hilo(repo.lote_propietario, user_id, plot_id)
    if desde and hasta and desde > hasta:
        raise ReglaNegocio(400, "La fecha inicial debe ser anterior a la final.")
    rows = await hilo(repo.listar_cuidados, plot_id, desde, hasta, tipo, limite, offset)
    paths = [row["evidence_path"] for row in rows if row.get("evidence_path")]
    try:
        urls = await storage.firmar_objetos(http, _BUCKET, paths)
    except (httpx.HTTPError, RuntimeError) as error:
        log.exception("No se pudieron firmar evidencias de la lista")
        raise HTTPException(502, "No se pudieron cargar las URLs temporales de las evidencias.") from error
    return [
        _serializar(row, urls.get(row.get("evidence_path")))
        for row in rows
    ]


async def obtener(http: httpx.AsyncClient, user_id: str, activity_id: str) -> dict:
    row = await hilo(repo.cuidado_por_id, activity_id)
    await hilo(repo.lote_propietario, user_id, row["plot_id"])
    return await _con_url(http, row)


async def actualizar(
    http: httpx.AsyncClient, user_id: str, activity_id: str, cambios: dict
) -> dict:
    row = await hilo(repo.cuidado_por_id, activity_id)
    await hilo(repo.lote_propietario, user_id, row["plot_id"])
    combinado = {**row, **cambios}
    _validar_registro(combinado)
    if not cambios:
        return await _con_url(http, row)
    updated = await hilo(repo.actualizar_cuidado, activity_id, cambios)
    return await _con_url(http, updated)


async def eliminar(http: httpx.AsyncClient, user_id: str, activity_id: str) -> None:
    row = await hilo(repo.cuidado_por_id, activity_id)
    await hilo(repo.lote_propietario, user_id, row["plot_id"])
    ruta = row.get("evidence_path")
    if ruta:
        try:
            await storage.eliminar_objeto(http, _BUCKET, ruta)
        except httpx.HTTPError:
            log.exception("No se pudo borrar la evidencia %s; se continuará con la fila", ruta)
    await hilo(repo.borrar_cuidado, activity_id)


async def subir_evidencia(
    http: httpx.AsyncClient, user_id: str, activity_id: str, contenido: bytes, content_type: str | None
) -> dict:
    row = await hilo(repo.cuidado_por_id, activity_id)
    await hilo(repo.lote_propietario, user_id, row["plot_id"])
    if content_type not in _MIME_FORMAT:
        raise HTTPException(400, "Formato no soportado. Usa JPG, PNG o WEBP.")
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(413, "La imagen supera 10 MB.")
    try:
        image = Image.open(io.BytesIO(contenido))
        image.verify()
        if image.format != _MIME_FORMAT[content_type]:
            raise HTTPException(400, "El tipo MIME no coincide con el contenido de la imagen.")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "El archivo no es una imagen válida.")

    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[content_type]
    ruta = f"{user_id}/{row['plot_id']}/{activity_id}.{extension}"
    try:
        await storage.subir_objeto(http, _BUCKET, ruta, contenido, content_type)
    except httpx.HTTPError:
        log.exception("No se pudo guardar la evidencia de cuidado")
        raise HTTPException(502, "No se pudo guardar la evidencia. Intenta de nuevo.")
    try:
        updated = await hilo(repo.actualizar_evidencia, activity_id, ruta)
    except Exception:
        try:
            await storage.eliminar_objeto(http, _BUCKET, ruta)
        except httpx.HTTPError:
            log.exception("No se pudo limpiar evidencia tras fallar el registro")
        raise
    previous_path = row.get("evidence_path")
    if previous_path and previous_path != ruta:
        try:
            await storage.eliminar_objeto(http, _BUCKET, previous_path)
        except httpx.HTTPError:
            log.exception("No se pudo borrar la evidencia reemplazada %s", previous_path)
    return await _con_url(http, updated)


async def eliminar_evidencia(http: httpx.AsyncClient, user_id: str, activity_id: str) -> None:
    row = await hilo(repo.cuidado_por_id, activity_id)
    await hilo(repo.lote_propietario, user_id, row["plot_id"])
    ruta = row.get("evidence_path")
    if ruta:
        await storage.eliminar_objeto(http, _BUCKET, ruta)
        await hilo(repo.actualizar_evidencia, activity_id, None)
