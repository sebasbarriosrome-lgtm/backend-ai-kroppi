import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError

from app import config, repositorio, storage
from app.auth import Usuario, usuario_actual
from app.classifier import Classifier
from app.recommendations import obtener_recomendaciones
from app.schemas import diagnostico_json

log = logging.getLogger("kroppi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.classifier = Classifier()
    app.state.http = httpx.AsyncClient(timeout=20)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Kroppi API", version=config.MODEL_VERSION, lifespan=lifespan)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


def _a_jpeg(imagen: Image.Image, max_lado: int = 1600) -> bytes:
    """Copia para guardar: JPEG sin metadatos (se pierde el GPS del EXIF) y tamaño acotado."""
    copia = imagen.convert("RGB")
    copia.thumbnail((max_lado, max_lado))
    buffer = io.BytesIO()
    copia.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


async def _responder(request: Request, registros: list[dict]) -> list[dict]:
    """Convierte registros de BD en el JSON del contrato, con URLs temporales para las fotos."""
    urls = await storage.firmar_urls(request.app.state.http, [r["image_path"] for r in registros])
    return [diagnostico_json(r, urls.get(r["image_path"], r["image_path"])) for r in registros]


@app.get("/health")
def health():
    return {"status": "ok", "model_version": config.MODEL_VERSION}


@app.post("/diagnoses", status_code=201)
async def crear_diagnostico(
    request: Request,
    file: UploadFile = File(...),
    crop_slug: str = Form("cafe"),
    latitude: float | None = Form(None, ge=-90, le=90),
    longitude: float | None = Form(None, ge=-180, le=180),
    usuario: Usuario = Depends(usuario_actual),
):
    # --- 1. Validar la entrada ---
    if crop_slug not in config.CULTIVOS_SOPORTADOS:
        raise HTTPException(400, f"No hay modelo para el cultivo '{crop_slug}'.")
    if (latitude is None) != (longitude is None):
        raise HTTPException(400, "Envía latitude y longitude juntas, o ninguna.")
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(400, "Formato no soportado. Usa JPG, PNG o WEBP.")
    contenido = await file.read()
    if len(contenido) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"La imagen supera {config.MAX_UPLOAD_MB} MB.")
    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "El archivo no es una imagen válida.")
    imagen = ImageOps.exif_transpose(imagen)   # respeta la orientación de fotos de celular

    # --- 2. Catálogo desde la base de datos ---
    cultivo, enfermedades = await run_in_threadpool(repositorio.cargar_catalogo, crop_slug)
    clasificador: Classifier = request.app.state.classifier
    codigos = [config.CLASE_A_CODIGO.get(c) for c in clasificador.class_names]
    if cultivo is None or any(c is None or c not in enfermedades for c in codigos):
        raise HTTPException(500, "Catálogo incompleto. Ejecuta migrations/001_seed_catalogo.sql en Supabase.")

    # --- 3. Modelo ---
    probs = await run_in_threadpool(clasificador.predict, imagen)
    orden = np.argsort(probs)[::-1][:3]
    top = [
        {"disease_code": codigos[i],
         "confidence": round(float(probs[i]), 4)}
        for i in orden
    ]
    mejor = int(orden[0])
    confianza = round(float(probs[mejor]), 4)

    # --- 4. Umbral: bajo el umbral no se afirma ninguna enfermedad ---
    enfermedad = None
    if confianza >= clasificador.umbral:
        enfermedad = enfermedades[codigos[mejor]]

    # --- 5. Gemini: solo con enfermedad (no sana). La foto NO se envía a Gemini ---
    recomendaciones: list[str] = []
    if enfermedad is not None and not enfermedad["is_healthy"]:
        recomendaciones = await obtener_recomendaciones(enfermedad)

    # --- 6. Guardar foto en Storage y diagnóstico en la base de datos ---
    diag_id = str(uuid4())
    ruta = f"{usuario.id}/{diag_id}.jpg"
    http: httpx.AsyncClient = request.app.state.http
    try:
        await storage.subir_imagen(http, ruta, await run_in_threadpool(_a_jpeg, imagen))
    except httpx.HTTPError:
        log.exception("Falló la subida de la imagen a Storage")
        raise HTTPException(502, "No se pudo guardar la imagen. Intenta de nuevo.")

    registro = {
        "id": diag_id,
        "image_path": ruta,
        "created_at": datetime.now(timezone.utc),
        "model_version": config.MODEL_VERSION,
        "confidence": confianza,
        "top": top,
        "recommendations": recomendaciones,
        "crop": cultivo,
        "disease": enfermedad,
    }
    try:
        await run_in_threadpool(repositorio.guardar_diagnostico, {
            "id": diag_id,
            "user_id": usuario.id,
            "crop_id": cultivo["id"],
            "disease_id": enfermedad["id"] if enfermedad else None,
            "image_url": ruta,
            "ai_prediction": {
                "model_version": config.MODEL_VERSION,
                "confidence": confianza,
                "disease_name": enfermedad["name"] if enfermedad else "Planta sana",
                "scientific_name": (enfermedad.get("scientific_name") if enfermedad else None) or "No especificado",
                "top": top,
                "recommendations": recomendaciones,
            },
            "latitude": latitude,
            "longitude": longitude,
            "created_at": registro["created_at"],
        })
    except Exception:
        log.exception("Falló el guardado del diagnóstico")
        await storage.eliminar_imagen(http, ruta)   # no dejar fotos huérfanas
        raise HTTPException(500, "No se pudo guardar el diagnóstico.")

    return (await _responder(request, [registro]))[0]


@app.get("/diagnoses")
async def listar_diagnosticos(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    usuario: Usuario = Depends(usuario_actual),
):
    registros = await run_in_threadpool(repositorio.listar_diagnosticos, usuario.id, limit, offset)
    return await _responder(request, registros)


@app.get("/diagnoses/{diagnostico_id}")
async def obtener_diagnostico(
    diagnostico_id: UUID,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
):
    registro = await run_in_threadpool(
        repositorio.obtener_diagnostico, usuario.id, str(diagnostico_id)
    )
    if registro is None:   # no existe o es de otro usuario: misma respuesta
        raise HTTPException(404, "Diagnóstico no encontrado.")
    return (await _responder(request, [registro]))[0]
