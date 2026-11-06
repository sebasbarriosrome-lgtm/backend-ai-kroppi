from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from app.core.security import Usuario, usuario_actual
from app.services import diagnosis_service

router = APIRouter(tags=["diagnósticos"])


@router.post("/diagnoses", status_code=201)
async def crear_diagnostico(
    request: Request,
    file: UploadFile = File(...),
    plot_samples_id: UUID = Form(...),
    latitude: float | None = Form(None, ge=-90, le=90),
    longitude: float | None = Form(None, ge=-180, le=180),
    usuario: Usuario = Depends(usuario_actual),
):
    contenido = await file.read()
    return await diagnosis_service.crear_diagnostico(
        http=request.app.state.http,
        clasificador=request.app.state.classifier,
        user_id=usuario.id,
        contenido=contenido,
        content_type=file.content_type,
        plot_samples_id=str(plot_samples_id),
        latitude=latitude,
        longitude=longitude,
    )


@router.get("/diagnoses")
async def listar_diagnosticos(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    plot_id: UUID | None = None,
    usuario: Usuario = Depends(usuario_actual),
):
    return await diagnosis_service.listar_diagnosticos(
        request.app.state.http,
        usuario.id,
        limit,
        offset,
        str(plot_id) if plot_id else None,
    )


@router.get("/diagnoses/{diagnostico_id}")
async def obtener_diagnostico(
    diagnostico_id: UUID,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
):
    return await diagnosis_service.obtener_diagnostico(
        request.app.state.http, usuario.id, str(diagnostico_id)
    )
