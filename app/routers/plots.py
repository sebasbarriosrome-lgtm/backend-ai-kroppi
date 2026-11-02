from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.security import Usuario, usuario_actual
from app.schemas import LoteIn, LotePatch
from app.services import plot_service

router = APIRouter(tags=["lotes"])


@router.post("/crops/{crop_id}/plots", status_code=201)
async def crear_lote(crop_id: UUID, body: LoteIn, usuario: Usuario = Depends(usuario_actual)):
    return await plot_service.crear_lote(usuario.id, str(crop_id), body.model_dump())


@router.get("/crops/{crop_id}/plots")
async def listar_lotes(crop_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    return await plot_service.listar_lotes(usuario.id, str(crop_id))


@router.get("/plots/{plot_id}")
async def obtener_lote(plot_id: UUID, request: Request, usuario: Usuario = Depends(usuario_actual)):
    return await plot_service.obtener_lote(usuario.id, str(plot_id), request.app.state.http)


@router.patch("/plots/{plot_id}")
async def editar_lote(plot_id: UUID, body: LotePatch, usuario: Usuario = Depends(usuario_actual)):
    return await plot_service.actualizar_lote(
        usuario.id, str(plot_id), body.model_dump(exclude_unset=True)
    )
