from datetime import date, datetime, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from app.core.security import Usuario, usuario_actual
from app.schemas.modulos_lote import Granularidad
from app.services import reports_service, stats_service, timeline_service

router = APIRouter(tags=["módulos de lote"])
_BOGOTA = ZoneInfo("America/Bogota")


def _today() -> date:
    return datetime.now(_BOGOTA).date()


def _default_start() -> date:
    today = _today()
    month = today.month - 6
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(today.day, 28))


@router.get("/plots/{plot_id}/stats")
async def estadisticas(
    plot_id: UUID,
    desde: Annotated[date | None, Query(alias="from")] = None,
    hasta: Annotated[date | None, Query(alias="to")] = None,
    granularity: Granularidad = "month",
    usuario: Usuario = Depends(usuario_actual),
):
    end = hasta or _today()
    return await stats_service.obtener(
        usuario.id, str(plot_id), desde or _default_start(), end, granularity
    )


@router.get("/plots/{plot_id}/timeline")
async def historial_lote(
    plot_id: UUID,
    desde: Annotated[date | None, Query(alias="from")] = None,
    hasta: Annotated[date | None, Query(alias="to")] = None,
    types: str = "sample,diagnosis,care,harvest,loss,report",
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
    usuario: Usuario = Depends(usuario_actual),
):
    end = hasta or _today()
    start = desde or (end - timedelta(days=3 * 366))
    kinds = [item.strip() for item in types.split(",") if item.strip()]
    return await timeline_service.obtener(
        usuario.id, str(plot_id), start, end, kinds, limit, before
    )


@router.get("/plots/{plot_id}/report-data")
async def datos_informe(
    plot_id: UUID,
    request: Request,
    desde: Annotated[date, Query(alias="from")],
    hasta: Annotated[date, Query(alias="to")],
    usuario: Usuario = Depends(usuario_actual),
):
    return await reports_service.datos_informe(
        request.app.state.http, usuario.id, str(plot_id), desde, hasta
    )


@router.post("/plots/{plot_id}/reports", status_code=201)
async def crear_informe(
    plot_id: UUID,
    request: Request,
    period_from: date = Form(...),
    period_to: date = Form(...),
    file: UploadFile = File(...),
    usuario: Usuario = Depends(usuario_actual),
):
    contenido = await file.read(15 * 1024 * 1024 + 1)
    return await reports_service.subir_informe(
        request.app.state.http, usuario.id, str(plot_id), period_from, period_to,
        contenido, file.content_type,
    )


@router.get("/plots/{plot_id}/reports")
async def listar_informes(plot_id: UUID, usuario: Usuario = Depends(usuario_actual)):
    return await reports_service.listar_informes(usuario.id, str(plot_id))


@router.get("/reports/{report_id}")
async def obtener_informe(
    report_id: UUID, request: Request,
    usuario: Usuario = Depends(usuario_actual),
):
    return await reports_service.obtener_informe(
        request.app.state.http, usuario.id, str(report_id)
    )


@router.delete("/reports/{report_id}", status_code=204)
async def eliminar_informe(
    report_id: UUID, request: Request,
    usuario: Usuario = Depends(usuario_actual),
):
    await reports_service.eliminar_informe(
        request.app.state.http, usuario.id, str(report_id)
    )
