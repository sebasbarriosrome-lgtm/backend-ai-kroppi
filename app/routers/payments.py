from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.security import Usuario, usuario_actual
from app.schemas.pagos import PagoCrearOut
from app.services import payment_service

router = APIRouter(tags=["pagos"])


@router.post("/payments/create", response_model=PagoCrearOut, status_code=201)
async def crear_pago(usuario: Usuario = Depends(usuario_actual)) -> PagoCrearOut:
    return await payment_service.crear_pago(usuario.id)


@router.post("/payments/webhook")
async def webhook_wompi(request: Request) -> dict[str, bool]:
    try:
        evento: Any = await request.json()
    except ValueError as error:
        raise HTTPException(400, "El evento recibido no es JSON válido.") from error
    if not isinstance(evento, dict):
        raise HTTPException(400, "El evento recibido no tiene un formato válido.")

    await payment_service.procesar_evento(request.app.state.http, evento)
    return {"received": True}
