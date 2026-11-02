from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config
from app.core import ReglaNegocio
from app.routers import crops, diagnoses, health, plots, samples
from app.services.classifier import Classifier


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.classifier = Classifier()
    app.state.http = httpx.AsyncClient(timeout=20)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Kroppi API", version=config.MODEL_VERSION, lifespan=lifespan)

# allow_origins=["*"] + allow_credentials=True no es válido en el navegador.
# Se refleja el Origin de la petición para aceptar cualquier origen con credenciales.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=r".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.exception_handler(ReglaNegocio)
async def _regla_negocio(_: Request, exc: ReglaNegocio):
    return JSONResponse({"detail": exc.mensaje}, status_code=exc.status)


app.include_router(health.router)
app.include_router(crops.router)
app.include_router(plots.router)
app.include_router(samples.router)
app.include_router(diagnoses.router)
