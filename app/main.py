import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool as hilo
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app import config, repositorio, storage
from app.auth import Usuario, usuario_actual
from app.classifier import Classifier
from app.entradas import CultivoIn, CultivoPatch, LoteIn, LotePatch, MuestreoIn
from app.recommendations import obtener_recomendaciones
from app.repositorio import ReglaNegocio
from app.schemas import diagnostico_json, fecha_iso

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
    allow_origins=["*"],  # Permite cualquier origen en desarrollo
    allow_credentials=True,
    allow_methods=["*"],  # Permite todos los métodos (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],  # Permite cabeceras como Authorization
)


@app.exception_handler(ReglaNegocio)
async def _regla_negocio(_: Request, exc: ReglaNegocio):
    return JSONResponse({"detail": exc.mensaje}, status_code=exc.status)


# ------------------------------------------------------------------ utilidades
def _a_jpeg(imagen: Image.Image, max_lado: int = 1600) -> bytes:
    copia = imagen.convert("RGB")
    copia.thumbnail((max_lado, max_lado))
    buffer = io.BytesIO()
    copia.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


async def _responder(request: Request, registros: list[dict]) -> list[dict]:
    urls = await storage.firmar_urls(request.app.state.http, [r["image_path"] for r in registros])
    return [diagnostico_json(r, urls.get(r["image_path"], r["image_path"])) for r in registros]


def _fechas(d: dict, *campos: str) -> dict:
    """Pasa datetimes/fechas a texto ISO para el JSON."""
    for c in campos:
        v = d.get(c)
        if isinstance(v, datetime):
            d[c] = fecha_iso(v)
        elif v is not None:
            d[c] = v.isoformat()
    return d


def _cultivo_json(c: dict) -> dict:
    return _fechas(c, "planted_at", "expected_harvest_at")


def _lote_json(p: dict) -> dict:
    return _fechas(p, "last_sampled_at")


def _muestreo_json(m: dict) -> dict:
    return _fechas(m, "sampled_at")


@app.get("/health")
def health():
    return {"status": "ok", "model_version": config.MODEL_VERSION}


# ------------------------------------------------------------------ catálogo y cultivos
@app.get("/crop-types")
async def tipos_de_cultivo(_: Usuario = Depends(usuario_actual)):
    return await hilo(repositorio.listar_tipos)


@app.post("/crops", status_code=201)
async def crear_cultivo(body: CultivoIn, usuario: Usuario = Depends(usuario_actual)):
    return _cultivo_json(await hilo(repositorio.crear_cultivo, usuario.id, body.model_dump()))


@app.get("/crops")
async def listar_cultivos(archived: bool = False, usuario: Usuario = Depends(usuario_actual)):
    cultivos = await hilo(repositorio.listar_cultivos, usuario.id, archived)
    return [_cultivo_json(c) for c in cultivos]


@app.get("/crops/{crop_id}")
async def obtener_cultivo(crop_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    return _cultivo_json(await hilo(repositorio.obtener_cultivo, usuario.id, str(crop_id)))


@app.patch("/crops/{crop_id}")
async def editar_cultivo(crop_id: UUID, body: CultivoPatch, usuario: Usuario = Depends(usuario_actual)):
    c = await hilo(repositorio.actualizar_cultivo, usuario.id, str(crop_id),
                   body.model_dump(exclude_unset=True))
    return _cultivo_json(c)


@app.delete("/crops/{crop_id}")
async def archivar_cultivo(crop_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    """No borra: archiva (is_active=false) para conservar el historial."""
    c = await hilo(repositorio.actualizar_cultivo, usuario.id, str(crop_id), {"is_active": False})
    return _cultivo_json(c)


# ------------------------------------------------------------------ lotes
@app.post("/crops/{crop_id}/plots", status_code=201)
async def crear_lote(crop_id: UUID, body: LoteIn, usuario: Usuario = Depends(usuario_actual)):
    return _lote_json(await hilo(repositorio.crear_lote, usuario.id, str(crop_id), body.model_dump()))


@app.get("/crops/{crop_id}/plots")
async def listar_lotes(crop_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    lotes = await hilo(repositorio.listar_lotes, usuario.id, str(crop_id))
    return [_lote_json(p) for p in lotes]


@app.get("/plots/{plot_id}")
async def obtener_lote(plot_id: UUID, request: Request, usuario: Usuario = Depends(usuario_actual)):
    lote = await hilo(repositorio.obtener_lote, usuario.id, str(plot_id))
    if lote["last_sample"]:
        _muestreo_json(lote["last_sample"])
    recientes = await hilo(repositorio.diagnosticos_de_lote, usuario.id, str(plot_id), 10)
    lote["recent_diagnostics"] = await _responder(request, recientes)
    return _lote_json(lote)


@app.patch("/plots/{plot_id}")
async def editar_lote(plot_id: UUID, body: LotePatch, usuario: Usuario = Depends(usuario_actual)):
    p = await hilo(repositorio.actualizar_lote, usuario.id, str(plot_id),
                   body.model_dump(exclude_unset=True))
    return _lote_json(p)


# ------------------------------------------------------------------ muestreo
@app.post("/plots/{plot_id}/samples", status_code=201)
async def cerrar_muestreo(plot_id: UUID, body: MuestreoIn, usuario: Usuario = Depends(usuario_actual)):
    m = await hilo(repositorio.crear_muestreo, usuario.id, str(plot_id),
                   [str(i) for i in body.diagnostic_ids], body.notes)
    return _muestreo_json(m)


@app.get("/plots/{plot_id}/samples")
async def historial_muestreos(plot_id: UUID, limit: int = Query(50, ge=1, le=200),
                              usuario: Usuario = Depends(usuario_actual)):
    muestreos = await hilo(repositorio.listar_muestreos, usuario.id, str(plot_id), limit)
    return [_muestreo_json(m) for m in muestreos]


# ------------------------------------------------------------------ diagnósticos
@app.post("/diagnoses", status_code=201)
async def crear_diagnostico(
    request: Request,
    file: UploadFile = File(...),
    crop_slug: str = Form("cafe"),
    plot_id: UUID | None = Form(None),
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
    imagen = ImageOps.exif_transpose(imagen)

    # --- 2. Tipo de cultivo y (si viene) lote del usuario ---
    tipo = await hilo(repositorio.tipo_por_slug, crop_slug)
    if tipo is None:
        raise HTTPException(500, f"Falta '{crop_slug}' en la tabla crop_types.")
    if plot_id is not None:
        tipo_lote = await hilo(repositorio.tipo_del_lote, usuario.id, str(plot_id))  # 404 si no es suyo
        if tipo_lote != tipo["id"]:
            raise HTTPException(400, "El lote pertenece a otro tipo de cultivo.")

    # --- 3. Modelo ---
    clasificador: Classifier = request.app.state.classifier
    codigos = [config.CLASE_A_CODIGO[c] for c in clasificador.class_names]
    probs = await hilo(clasificador.predict, imagen)
    orden = np.argsort(probs)[::-1][:3]
    top = [{"disease_code": codigos[i], "confidence": round(float(probs[i]), 4)} for i in orden]
    mejor = int(orden[0])
    confianza = round(float(probs[mejor]), 4)

    # --- 4. Umbral: bajo el umbral no se afirma nada (predicted_label = None) ---
    etiqueta = codigos[mejor] if confianza >= clasificador.umbral else None
    enfermedad = config.ENFERMEDADES[etiqueta] if etiqueta else None

    # --- 5. Gemini solo si hay enfermedad. La foto NO se envía a Gemini ---
    recomendaciones: list[str] = []
    if enfermedad is not None and not enfermedad["is_healthy"]:
        recomendaciones = await obtener_recomendaciones(enfermedad)

    # --- 6. Guardar foto y diagnóstico ---
    diag_id = str(uuid4())
    ruta = f"{usuario.id}/{diag_id}.jpg"
    http: httpx.AsyncClient = request.app.state.http
    try:
        await storage.subir_imagen(http, ruta, await hilo(_a_jpeg, imagen))
    except httpx.HTTPError:
        log.exception("Falló la subida de la imagen a Storage")
        raise HTTPException(502, "No se pudo guardar la imagen. Intenta de nuevo.")

    ahora = datetime.now(timezone.utc)
    registro = {
        "id": diag_id, "image_path": ruta, "created_at": ahora,
        "model_version": config.MODEL_VERSION, "confidence": confianza, "top": top,
        "recommendations": recomendaciones, "crop": tipo,
        "plot_id": str(plot_id) if plot_id else None, "disease": enfermedad,
    }
    try:
        await hilo(repositorio.guardar_diagnostico, {
            "id": diag_id, "user_id": usuario.id, "crop_type_id": tipo["id"],
            "plot_id": registro["plot_id"], "image_url": ruta,
            "predicted_label": etiqueta, "confidence": confianza,
            "recommendations": recomendaciones,
            "ai_prediction": {
                "model_version": config.MODEL_VERSION, "confidence": confianza,
                "disease_code": etiqueta,
                "disease_name": enfermedad["name"] if enfermedad else "Planta sana",
                "scientific_name": (enfermedad["scientific_name"] if enfermedad else None) or "No especificado",
                "pathogen_type": enfermedad["pathogen_type"] if enfermedad else None,
                "symptoms": enfermedad["symptoms"] if enfermedad else [],
                "top": top, "recommendations": recomendaciones,
            },
            "latitude": latitude, "longitude": longitude, "created_at": ahora,
        })
    except Exception:
        log.exception("Falló el guardado del diagnóstico")
        await storage.eliminar_imagen(http, ruta)
        raise HTTPException(500, "No se pudo guardar el diagnóstico.")

    return (await _responder(request, [registro]))[0]


@app.get("/diagnoses")
async def listar_diagnosticos(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    plot_id: UUID | None = None,
    usuario: Usuario = Depends(usuario_actual),
):
    registros = await hilo(repositorio.listar_diagnosticos, usuario.id, limit, offset,
                           str(plot_id) if plot_id else None)
    return await _responder(request, registros)


@app.get("/diagnoses/{diagnostico_id}")
async def obtener_diagnostico(diagnostico_id: UUID, request: Request,
                              usuario: Usuario = Depends(usuario_actual)):
    registro = await hilo(repositorio.obtener_diagnostico, usuario.id, str(diagnostico_id))
    return (await _responder(request, [registro]))[0]