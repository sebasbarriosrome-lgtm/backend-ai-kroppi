from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.core.security import Usuario, usuario_actual
from app.schemas import MuestreoIn, MuestreoPatch
from app.services import sample_service

router = APIRouter(tags=["muestreos"])


@router.post("/plots/{plot_id}/samples", status_code=201)
async def crear_muestreo(
    plot_id: UUID, body: MuestreoIn, usuario: Usuario = Depends(usuario_actual)
):
    return await sample_service.crear_muestreo(usuario.id, str(plot_id), body.model_dump())


@router.get("/plots/{plot_id}/samples")
async def historial_muestreos(
    plot_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    usuario: Usuario = Depends(usuario_actual),
):
    return await sample_service.listar_muestreos(usuario.id, str(plot_id), limit)


@router.patch("/samples/{sample_id}")
async def editar_muestreo(
    sample_id: UUID, body: MuestreoPatch, usuario: Usuario = Depends(usuario_actual)
):
    return await sample_service.actualizar_muestreo(
        usuario.id, str(sample_id), body.model_dump(exclude_unset=True)
    )


@router.delete("/samples/{sample_id}", status_code=204)
async def eliminar_muestreo(
    sample_id: UUID, request: Request, usuario: Usuario = Depends(usuario_actual)
):
    await sample_service.eliminar_muestreo(request.app.state.http, usuario.id, str(sample_id))
