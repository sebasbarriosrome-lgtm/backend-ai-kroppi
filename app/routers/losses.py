from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import Usuario
from app.schemas.estimacion_perdida import PerdidaEstimadaCrear, PerdidaEstimadaEditar
from app.services import perdida_service
from app.services.subscription_service import usuario_premium

router = APIRouter(tags=["pérdida estimada"])


@router.get("/plots/{plot_id}/loss-estimations/defaults")
async def valores_sugeridos(plot_id: UUID, usuario: Usuario = Depends(usuario_premium)):
    return await perdida_service.defaults(usuario.id, str(plot_id))


@router.post("/plots/{plot_id}/loss-estimations/preview")
async def previsualizar(
    plot_id: UUID,
    body: PerdidaEstimadaCrear,
    exclude_id: UUID | None = Query(None, description="Estimación que se está editando"),
    usuario: Usuario = Depends(usuario_premium),
):
    return await perdida_service.preview(
        usuario.id, str(plot_id), body.model_dump(), str(exclude_id) if exclude_id else None
    )


@router.post("/plots/{plot_id}/loss-estimations", status_code=201)
async def crear_estimacion(
    plot_id: UUID, body: PerdidaEstimadaCrear, usuario: Usuario = Depends(usuario_premium)
):
    return await perdida_service.crear(usuario.id, str(plot_id), body.model_dump())


@router.get("/plots/{plot_id}/loss-estimations")
async def listar_estimaciones(
    plot_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    usuario: Usuario = Depends(usuario_premium),
):
    return await perdida_service.listar(usuario.id, str(plot_id), limit, offset)


@router.get("/loss-estimations/{estimation_id}")
async def obtener_estimacion(estimation_id: UUID, usuario: Usuario = Depends(usuario_premium)):
    return await perdida_service.obtener(usuario.id, str(estimation_id))


@router.patch("/loss-estimations/{estimation_id}")
async def editar_estimacion(
    estimation_id: UUID, body: PerdidaEstimadaEditar, usuario: Usuario = Depends(usuario_premium)
):
    return await perdida_service.actualizar(
        usuario.id, str(estimation_id), body.model_dump(exclude_unset=True)
    )


@router.delete("/loss-estimations/{estimation_id}", status_code=204)
async def eliminar_estimacion(estimation_id: UUID, usuario: Usuario = Depends(usuario_premium)):
    await perdida_service.eliminar(usuario.id, str(estimation_id))
