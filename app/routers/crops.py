from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.security import Usuario, usuario_actual
from app.schemas import CultivoIn, CultivoPatch
from app.services import crop_service

router = APIRouter(tags=["cultivos"])


@router.get("/crop-types")
async def tipos_de_cultivo(_: Usuario = Depends(usuario_actual)):
    return await crop_service.listar_tipos()


@router.post("/crops", status_code=201)
async def crear_cultivo(body: CultivoIn, usuario: Usuario = Depends(usuario_actual)):
    return await crop_service.crear_cultivo(usuario.id, body.model_dump())


@router.get("/crops")
async def listar_cultivos(archived: bool = False, usuario: Usuario = Depends(usuario_actual)):
    return await crop_service.listar_cultivos(usuario.id, archived)


@router.get("/crops/{crop_id}")
async def obtener_cultivo(crop_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    return await crop_service.obtener_cultivo(usuario.id, str(crop_id))


@router.patch("/crops/{crop_id}")
async def editar_cultivo(crop_id: UUID, body: CultivoPatch, usuario: Usuario = Depends(usuario_actual)):
    return await crop_service.actualizar_cultivo(
        usuario.id, str(crop_id), body.model_dump(exclude_unset=True)
    )


@router.delete("/crops/{crop_id}")
async def archivar_cultivo(crop_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    """No borra: archiva (is_active=false) para conservar el historial."""
    return await crop_service.archivar_cultivo(usuario.id, str(crop_id))
