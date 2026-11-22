from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import Usuario, usuario_actual
from app.schemas.cosecha import CosechaCrear, CosechaEditar
from app.services import cosecha_service, subscription_service

router = APIRouter(tags=["cosechas"])


@router.get("/plots/{plot_id}/harvests")
async def listar_cosechas(
    plot_id: UUID,
    desde: Annotated[date | None, Query(alias="from")] = None,
    hasta: Annotated[date | None, Query(alias="to")] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    usuario: Usuario = Depends(subscription_service.usuario_premium),
):
    return await cosecha_service.listar(usuario.id, str(plot_id), desde, hasta, limit, offset)


@router.post("/plots/{plot_id}/harvests", status_code=201)
async def crear_cosecha(
    plot_id: UUID, body: CosechaCrear, usuario: Usuario = Depends(usuario_actual)
):
    acceso = await subscription_service.acceso(usuario.id)
    return await cosecha_service.crear(
        usuario.id, str(plot_id), body.model_dump(),
        incluir_estimaciones=subscription_service.es_premium(acceso),
    )


@router.get("/harvests/{harvest_id}")
async def obtener_cosecha(harvest_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    return await cosecha_service.obtener(usuario.id, str(harvest_id))


@router.patch("/harvests/{harvest_id}")
async def editar_cosecha(
    harvest_id: UUID, body: CosechaEditar, usuario: Usuario = Depends(usuario_actual)
):
    acceso = await subscription_service.acceso(usuario.id)
    return await cosecha_service.actualizar(
        usuario.id, str(harvest_id), body.model_dump(exclude_unset=True),
        incluir_estimaciones=subscription_service.es_premium(acceso),
    )


@router.delete("/harvests/{harvest_id}")
async def eliminar_cosecha(harvest_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    """Devuelve `affects_estimations` para que la app sugiera recalcularlas."""
    acceso = await subscription_service.acceso(usuario.id)
    return await cosecha_service.eliminar(
        usuario.id, str(harvest_id), incluir_estimaciones=subscription_service.es_premium(acceso),
    )
