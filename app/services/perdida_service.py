from datetime import date, timedelta

from fastapi.concurrency import run_in_threadpool as hilo

from app.core.exceptions import ReglaNegocio
from app.repository import cosecha_perdida_repository as repo
from app.repository import plot_modules_repository as modulos
from app.services import tiempo
from app.services.perdidas_calculo import (
    _fecha, a_json, calcular_perdida, dec, normalizar_estimacion, redondear_kg,
)

AVISO_FUTURO = "El periodo termina en el futuro: la estimación cambiará al registrar más cosechas"
AVISO_SIN_COSECHAS = "No hay cosechas registradas en este periodo"


def _mas_anios(d: date, anios: int) -> date:
    try:
        return d.replace(year=d.year + anios)
    except ValueError:  # 29 de febrero
        return d.replace(year=d.year + anios, day=28)


def _menos_meses(d: date, meses: int) -> date:
    anio, mes = divmod(d.month - 1 - meses, 12)
    return date(d.year + anio, mes + 1, min(d.day, 28))


def item(row: dict, warnings: list[str] | None = None) -> dict:
    e = normalizar_estimacion(row)
    return a_json({
        "id": e.get("id"),
        "plot_id": e["plot_id"],
        "expected_yield_kg": e["expected_yield_kg"],
        "harvested_kg": e["harvested_kg"],
        "lost_kg": e["lost_kg"],
        "loss_pct": e["loss_pct"],
        "surplus_kg": e["surplus_kg"],
        "price_per_kg": e["price_per_kg"],
        "currency": e["currency"],
        "estimated_loss_amount": e["estimated_loss_amount"],
        "period_from": e["period_from"],
        "period_to": e["period_to"],
        "explanation": e.get("explanation"),
        "notes": e.get("notes"),
        "warnings": warnings or [],
        "harvests_in_period": e["harvests_in_period"],
        "created_at": e.get("created_at"),
        "updated_at": e.get("updated_at"),
    })


async def _lote(user_id: str, plot_id: str) -> dict:
    return await hilo(modulos.lote_propietario, user_id, plot_id)


async def _estimacion_propia(user_id: str, estimation_id: str) -> dict:
    """404 también si el lote de la estimación no es del usuario."""
    row = await hilo(repo.estimacion_por_id, estimation_id)
    try:
        await _lote(user_id, row["plot_id"])
    except ReglaNegocio as error:
        if error.status == 404:
            raise ReglaNegocio(404, "Estimación no encontrada.") from error
        raise
    return row


async def _calcular(
    plot_id: str, datos: dict, excluir_id: str | None = None
) -> tuple[dict, list[str]]:
    """Valida el periodo y calcula la pérdida con las cosechas actuales del lote."""
    desde, hasta = datos["period_from"], datos["period_to"]
    if hasta < desde:
        raise ReglaNegocio(422, "La fecha final del periodo no puede ser anterior a la inicial.")
    if hasta > _mas_anios(desde, 2):
        raise ReglaNegocio(422, "El periodo no puede superar 2 años.")

    # Sin traslapes: evita contar dos veces las mismas pérdidas en los acumulados.
    for otra in map(normalizar_estimacion, await hilo(repo.estimaciones, plot_id)):
        if otra["id"] == excluir_id or not otra["period_from"] or not otra["period_to"]:
            continue
        if desde <= otra["period_to"] and otra["period_from"] <= hasta:
            raise ReglaNegocio(
                422,
                "Este periodo se cruza con otra estimación ya guardada ("
                f"{otra['period_from'].strftime('%d/%m/%Y')} – "
                f"{otra['period_to'].strftime('%d/%m/%Y')})",
            )

    cosechas = await hilo(repo.cosechas, plot_id, desde, hasta)
    cosechado = sum((dec(c["quantity_kg"]) for c in cosechas), dec(0))
    resultado = calcular_perdida(
        datos["expected_yield_kg"], cosechado, datos["price_per_kg"], datos["currency"]
    )
    warnings = []
    if hasta > tiempo.hoy():
        warnings.append(AVISO_FUTURO)
    if not cosechas:
        warnings.append(AVISO_SIN_COSECHAS)
    return {**resultado, "harvests_in_period": len(cosechas)}, warnings


def _registro(plot_id: str, datos: dict, calculo: dict) -> dict:
    """Columnas a guardar. `inputs` se sigue llenando por compatibilidad."""
    return {
        "plot_id": plot_id,
        "expected_yield_kg": calculo["expected_yield_kg"],
        "price_per_kg": datos["price_per_kg"],
        "currency": datos["currency"],
        "period_from": datos["period_from"],
        "period_to": datos["period_to"],
        "notes": datos.get("notes"),
        "harvested_kg": calculo["harvested_kg"],
        "lost_kg": calculo["lost_kg"],
        "loss_pct": calculo["loss_pct"],
        "estimated_loss_amount": calculo["estimated_loss_amount"],
        "explanation": calculo["explanation"],
        "source": "RULES",
        "inputs": a_json({
            "expected_yield_kg": calculo["expected_yield_kg"],
            "harvested_kg": calculo["harvested_kg"],
            "lost_kg": calculo["lost_kg"],
            "loss_pct": calculo["loss_pct"],
            "period_from": datos["period_from"],
            "period_to": datos["period_to"],
            "harvests_in_period": calculo["harvests_in_period"],
        }),
        "updated_at": tiempo.ahora(),
    }


async def defaults(user_id: str, plot_id: str) -> dict:
    lote = await _lote(user_id, plot_id)
    crop_type = lote["crop"]["crop_type"]
    rendimiento = dec(crop_type.get("avg_yield_kg_per_ha"))
    area = dec(lote.get("area_ha"))
    esperado = redondear_kg(rendimiento * area) if rendimiento and area else None

    estimaciones = [normalizar_estimacion(r) for r in await hilo(repo.estimaciones, plot_id)]
    con_precio = [
        c for c in await hilo(repo.cosechas, plot_id) if c.get("price_per_kg") is not None
    ]
    precio, moneda, fuente_precio = None, "COP", None
    if con_precio:
        precio = dec(con_precio[0]["price_per_kg"])
        moneda = (con_precio[0].get("currency") or "COP").strip()
        fuente_precio = "última cosecha"
    elif estimaciones and estimaciones[0]["price_per_kg"] is not None:
        precio, moneda = estimaciones[0]["price_per_kg"], estimaciones[0]["currency"]
        fuente_precio = "última estimación"

    hoy = tiempo.hoy()
    fines = [e["period_to"] for e in estimaciones if e["period_to"]]
    siembra = _fecha(lote["crop"].get("planted_at"))
    if fines:
        desde = max(fines) + timedelta(days=1)
    elif siembra:
        desde = siembra
    else:
        desde = _menos_meses(hoy, 6)
    return a_json({
        "expected_yield_kg": esperado,
        "expected_yield_source": "avg_yield_kg_per_ha × area_ha" if esperado is not None else None,
        "price_per_kg": precio,
        "price_source": fuente_precio,
        "currency": moneda,
        "period_from": desde,
        "period_to": max(hoy, desde),
    })


async def preview(
    user_id: str, plot_id: str, datos: dict, excluir_id: str | None = None
) -> dict:
    """Calcula sin guardar. Al editar, `excluir_id` evita que la estimación
    choque consigo misma en la validación de traslape (igual que el PATCH)."""
    await _lote(user_id, plot_id)
    if excluir_id is not None:
        propia = await _estimacion_propia(user_id, excluir_id)
        if propia["plot_id"] != plot_id:
            raise ReglaNegocio(404, "Estimación no encontrada.")
    calculo, warnings = await _calcular(plot_id, datos, excluir_id=excluir_id)
    return item({**_registro(plot_id, datos, calculo), "id": None, "created_at": None}, warnings)


async def crear(user_id: str, plot_id: str, datos: dict) -> dict:
    await _lote(user_id, plot_id)
    calculo, warnings = await _calcular(plot_id, datos)
    row = await hilo(repo.crear_estimacion, {
        **_registro(plot_id, datos, calculo),
        "created_by": user_id,
        "created_at": tiempo.ahora(),
    })
    return item(row, warnings)


async def listar(user_id: str, plot_id: str, limite: int, offset: int) -> dict:
    await _lote(user_id, plot_id)
    rows = await hilo(repo.estimaciones, plot_id, limite + 1, offset)
    return {
        "items": [item(r) for r in rows[:limite]],
        "next_offset": offset + limite if len(rows) > limite else None,
    }


async def obtener(user_id: str, estimation_id: str) -> dict:
    return item(await _estimacion_propia(user_id, estimation_id))


async def actualizar(user_id: str, estimation_id: str, cambios: dict) -> dict:
    """Combina los cambios con lo guardado y siempre recalcula con las cosechas actuales."""
    actual = normalizar_estimacion(await _estimacion_propia(user_id, estimation_id))
    datos = {
        campo: actual.get(campo)
        for campo in (
            "expected_yield_kg", "price_per_kg", "currency", "period_from", "period_to", "notes",
        )
    }
    datos.update({k: v for k, v in cambios.items() if v is not None or k == "notes"})
    if datos["expected_yield_kg"] is None or datos["price_per_kg"] is None:
        raise ReglaNegocio(422, "Indica los kilos esperados y el precio por kg.")
    if not datos["period_from"] or not datos["period_to"]:
        raise ReglaNegocio(422, "Indica el periodo de la estimación.")
    calculo, warnings = await _calcular(actual["plot_id"], datos, excluir_id=estimation_id)
    row = await hilo(
        repo.actualizar_estimacion, estimation_id, _registro(actual["plot_id"], datos, calculo)
    )
    return item(row, warnings)


async def eliminar(user_id: str, estimation_id: str) -> None:
    await _estimacion_propia(user_id, estimation_id)
    await hilo(repo.borrar_estimacion, estimation_id)
