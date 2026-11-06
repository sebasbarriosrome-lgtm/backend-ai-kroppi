from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from app.core.security import Usuario, usuario_actual
from app.schemas.cuidado import CuidadoCrear, CuidadoPatch, TipoCuidado
from app.services import care_service

router = APIRouter(tags=["cuidados"])


@router.post("/plots/{plot_id}/care-activities", status_code=201)
async def crear_cuidado(
    plot_id: UUID, body: CuidadoCrear,
    usuario: Usuario = Depends(usuario_actual),
):
    return await care_service.crear(
        usuario.id, str(plot_id), body.model_dump()
    )


@router.get("/plots/{plot_id}/care-activities")
async def listar_cuidados(
    plot_id: UUID,
    request: Request,
    desde: Annotated[date | None, Query(alias="from")] = None,
    hasta: Annotated[date | None, Query(alias="to")] = None,
    tipo: Annotated[TipoCuidado | None, Query(alias="type")] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    usuario: Usuario = Depends(usuario_actual),
):
    return await care_service.listar(
        request.app.state.http, usuario.id, str(plot_id), desde, hasta, tipo, limit, offset
    )


@router.get("/care-activities/{activity_id}")
async def obtener_cuidado(
    activity_id: UUID, request: Request,
    usuario: Usuario = Depends(usuario_actual),
):
    return await care_service.obtener(request.app.state.http, usuario.id, str(activity_id))


@router.patch("/care-activities/{activity_id}")
async def actualizar_cuidado(
    activity_id: UUID, body: CuidadoPatch, request: Request,
    usuario: Usuario = Depends(usuario_actual),
):
    return await care_service.actualizar(
        request.app.state.http, usuario.id, str(activity_id),
        body.model_dump(exclude_unset=True, mode="json"),
    )


@router.delete("/care-activities/{activity_id}", status_code=204)
async def eliminar_cuidado(
    activity_id: UUID, request: Request,
    usuario: Usuario = Depends(usuario_actual),
):
    await care_service.eliminar(request.app.state.http, usuario.id, str(activity_id))


@router.put("/care-activities/{activity_id}/evidence")
async def subir_evidencia(
    activity_id: UUID, request: Request, file: UploadFile = File(...),
    usuario: Usuario = Depends(usuario_actual),
):
    contenido = await file.read(10 * 1024 * 1024 + 1)
    return await care_service.subir_evidencia(
        request.app.state.http, usuario.id, str(activity_id), contenido, file.content_type
    )


@router.delete("/care-activities/{activity_id}/evidence", status_code=204)
async def eliminar_evidencia(
    activity_id: UUID, request: Request,
    usuario: Usuario = Depends(usuario_actual),
):
    await care_service.eliminar_evidencia(request.app.state.http, usuario.id, str(activity_id))
