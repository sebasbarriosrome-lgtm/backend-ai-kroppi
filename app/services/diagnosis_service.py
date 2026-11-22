import io
import logging
from datetime import datetime, timezone
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import httpx
import numpy as np
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool as hilo
from PIL import Image, ImageOps, UnidentifiedImageError

from app import config
from app.repository import diagnosis_repository
from app.schemas import diagnostico_json
from app.services.classifier import Classifier
from app.services.recommendations import obtener_recomendaciones
from app.services import storage, subscription_service

log = logging.getLogger("kroppi")


def a_jpeg(imagen: Image.Image, max_lado: int = 1600) -> bytes:
    copia = imagen.convert("RGB")
    copia.thumbnail((max_lado, max_lado))
    buffer = io.BytesIO()
    copia.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


async def firmar_diagnosticos(http: httpx.AsyncClient, registros: list[dict]) -> list[dict]:
    urls = await storage.firmar_urls(http, [r["image_path"] for r in registros])
    return [diagnostico_json(r, urls.get(r["image_path"], r["image_path"])) for r in registros]


async def crear_diagnostico(
    *,
    http: httpx.AsyncClient,
    clasificadores: dict[str, Classifier],
    user_id: str,
    contenido: bytes,
    content_type: str | None,
    plot_samples_id: str,
    latitude: float | None,
    longitude: float | None,
    idempotency_key: UUID | None = None,
) -> dict:
    if (latitude is None) != (longitude is None):
        raise HTTPException(400, "Envía latitude y longitude juntas, o ninguna.")
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(400, "Formato no soportado. Usa JPG, PNG o WEBP.")
    if len(contenido) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"La imagen supera {config.MAX_UPLOAD_MB} MB.")
    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "El archivo no es una imagen válida.")
    imagen = ImageOps.exif_transpose(imagen)

    contexto = await hilo(diagnosis_repository.contexto_muestreo, user_id, plot_samples_id)
    tipo = contexto["crop_type"]
    slug = tipo["slug"]
    if slug not in config.CULTIVOS_SOPORTADOS:
        raise HTTPException(400, f"No hay modelo para el cultivo '{tipo['slug']}'.")
    clasificador = clasificadores[slug]

    codigos = [clasificador.class_to_code[c] for c in clasificador.class_names]
    diag_id = str(
        uuid5(NAMESPACE_URL, f"kroppi:diagnoses:{user_id}:{idempotency_key}")
        if idempotency_key is not None else uuid4()
    )
    await subscription_service.consumir_diagnostico(user_id, diag_id)
    probs = await hilo(clasificador.predict, imagen)
    orden = np.argsort(probs)[::-1][:3]
    top = [{"disease_code": codigos[i], "confidence": round(float(probs[i]), 4)} for i in orden]
    mejor = int(orden[0])
    confianza = round(float(probs[mejor]), 4)

    etiqueta = codigos[mejor] if confianza >= clasificador.umbral else None
    enfermedad = config.ENFERMEDADES[etiqueta] if etiqueta else None

    recomendaciones: list[str] = []
    if enfermedad is not None and not enfermedad["is_healthy"]:
        nombre_cultivo = "maíz" if slug == "maiz" else "café"
        recomendaciones = await obtener_recomendaciones(enfermedad, nombre_cultivo)

    ruta = f"{user_id}/{diag_id}.jpg"
    try:
        await storage.subir_imagen(http, ruta, await hilo(a_jpeg, imagen))
    except httpx.HTTPError:
        log.exception("Falló la subida de la imagen a Storage")
        raise HTTPException(502, "No se pudo guardar la imagen. Intenta de nuevo.")

    ahora = datetime.now(timezone.utc)
    registro = {
        "id": diag_id,
        "plot_samples_id": plot_samples_id,
        "image_path": ruta,
        "created_at": ahora,
        "model_version": clasificador.model_version,
        "confidence": confianza,
        "top": top,
        "recommendations": recomendaciones,
        "crop": tipo,
        "plot_id": contexto["plot_id"],
        "disease": enfermedad,
    }
    try:
        await hilo(
            diagnosis_repository.guardar_diagnostico,
            {
                "id": diag_id,
                "user_id": user_id,
                "plot_samples_id": plot_samples_id,
                "image_url": ruta,
                "predicted_label": etiqueta,
                "confidence": confianza,
                "recommendations": recomendaciones,
                "ai_prediction": {
                    "model_version": clasificador.model_version,
                    "model_threshold": clasificador.umbral,
                    "confidence": confianza,
                    "disease_code": etiqueta,
                    "disease_name": enfermedad["name"] if enfermedad else "Planta sana",
                    "scientific_name": (enfermedad["scientific_name"] if enfermedad else None)
                    or "No especificado",
                    "pathogen_type": enfermedad["pathogen_type"] if enfermedad else None,
                    "symptoms": enfermedad["symptoms"] if enfermedad else [],
                    "top": top,
                    "recommendations": recomendaciones,
                },
                "latitude": latitude,
                "longitude": longitude,
                "user_feedback": None,
                "created_at": ahora,
            },
        )
    except Exception:
        log.exception("Falló el guardado del diagnóstico")
        await storage.eliminar_imagen(http, ruta)
        raise HTTPException(500, "No se pudo guardar el diagnóstico.")

    return (await firmar_diagnosticos(http, [registro]))[0]


async def listar_diagnosticos(
    http: httpx.AsyncClient,
    user_id: str,
    limit: int,
    offset: int,
    plot_id: str | None,
) -> list[dict]:
    acceso = await subscription_service.acceso(user_id)
    desde = subscription_service.inicio_historial_diagnosticos(acceso)
    registros = await hilo(
        diagnosis_repository.listar_diagnosticos, user_id, limit, offset, plot_id, desde
    )
    return await firmar_diagnosticos(http, registros)


async def obtener_diagnostico(http: httpx.AsyncClient, user_id: str, diagnostico_id: str) -> dict:
    acceso = await subscription_service.acceso(user_id)
    desde = subscription_service.inicio_historial_diagnosticos(acceso)
    registro = await hilo(diagnosis_repository.obtener_diagnostico, user_id, diagnostico_id, desde)
    return (await firmar_diagnosticos(http, [registro]))[0]


async def eliminar_diagnostico(http: httpx.AsyncClient, user_id: str, diagnostico_id: str) -> None:
    ruta = await hilo(diagnosis_repository.eliminar_diagnostico, user_id, diagnostico_id)
    if ruta:
        await storage.eliminar_imagen(http, ruta)
