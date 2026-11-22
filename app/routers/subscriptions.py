from fastapi import APIRouter, Depends

from app.core.security import Usuario, usuario_actual
from app.services import subscription_service

router = APIRouter(tags=["suscripciones"])


@router.get("/subscription")
async def suscripcion(usuario: Usuario = Depends(usuario_actual)):
    return await subscription_service.estado(usuario.id)
