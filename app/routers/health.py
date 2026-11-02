from fastapi import APIRouter

from app import config

router = APIRouter(tags=["salud"])


@router.get("/health")
def health():
    return {"status": "ok", "model_version": config.MODEL_VERSION}
