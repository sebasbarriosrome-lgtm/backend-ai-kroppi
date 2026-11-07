from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi.concurrency import run_in_threadpool as hilo

from app.core.exceptions import ReglaNegocio
from app.repository import cosecha_perdida_repository as repo
from app.repository import plot_modules_repository as modulos
from app.services import tiempo
from app.services.perdidas_calculo import (
    _fecha, a_json, dec, normalizar_estimacion, redondear_kg, redondear_monto,
)


def item(row: dict) -> dict:
    kg = dec(row["quantity_kg"])
    precio = dec(row.get("price_per_kg"))
    moneda = (row.get("currency") or "COP").strip()
    return a_json({
        "id": row["id"],
        "plot_id": row["plot_id"],
        "harvested_at": row["harvested_at"],
        "quantity_kg": kg,
        "price_per_kg": precio,
        "currency": moneda,
        "value": redondear_monto(kg * precio, moneda) if precio is not None else None,
        "notes": row.get("notes"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    })


def totales(rows: list[dict]) -> dict:
    """Totales sin mezclar monedas: los ingresos van agrupados por `currency`."""
    kg = Decimal(0)
    por_moneda: dict[str, dict] = defaultdict(lambda: {"revenue": Decimal(0), "harvests_with_price": 0})
    sin_precio = 0
    for row in rows:
        cantidad = dec(row["quantity_kg"])
        kg += cantidad
        precio = dec(row.get("price_per_kg"))
        if precio is None:
            sin_precio += 1
            continue
        moneda = (row.get("currency") or "COP").strip()
        por_moneda[moneda]["revenue"] += cantidad * precio
        por_moneda[moneda]["harvests_with_price"] += 1
    return a_json({
        "quantity_kg": redondear_kg(kg),
        "by_currency": [
            {"currency": moneda, "revenue": redondear_monto(v["revenue"], moneda),
             "harvests_with_price": v["harvests_with_price"]}
            for moneda, v in sorted(por_moneda.items())
        ],
        "harvests_without_price": sin_precio,
    })


async def _lote(user_id: str, plot_id: str) -> dict:
    return await hilo(modulos.lote_propietario, user_id, plot_id)


async def _cosecha_propia(user_id: str, harvest_id: str) -> tuple[dict, dict]:
    """Devuelve (cosecha, lote). 404 también si el lote no es del usuario."""
    row = await hilo(repo.cosecha_por_id, harvest_id)
    try:
        lote = await _lote(user_id, row["plot_id"])
    except ReglaNegocio as error:
        if error.status == 404:
            raise ReglaNegocio(404, "Cosecha no encontrada.") from error
        raise
    return row, lote


def _validar_fecha(fecha: date, lote: dict) -> None:
    if fecha > tiempo.hoy():
        raise ReglaNegocio(400, "La fecha de cosecha no puede ser futura.")
    siembra = _fecha(lote["crop"].get("planted_at"))
    if siembra and fecha < siembra:
        raise ReglaNegocio(
            400,
            "La fecha de cosecha no puede ser anterior a la siembra del cultivo "
            f"({siembra.strftime('%d/%m/%Y')}).",
        )


async def _estimaciones_afectadas(plot_id: str, fechas: list[date]) -> list[str]:
    rows = [normalizar_estimacion(r) for r in await hilo(repo.estimaciones, plot_id)]
    return [
        r["id"] for r in rows
        if r["period_from"] and r["period_to"]
        and any(r["period_from"] <= f <= r["period_to"] for f in fechas)
    ]


async def listar(
    user_id: str, plot_id: str, desde: date | None, hasta: date | None, limite: int, offset: int,
) -> dict:
    if desde and hasta and desde > hasta:
        raise ReglaNegocio(400, "La fecha inicial debe ser anterior a la final.")
    await _lote(user_id, plot_id)
    pagina = await hilo(repo.cosechas, plot_id, desde, hasta, limite + 1, offset)
    todas = await hilo(repo.cosechas, plot_id, desde, hasta)
    return {
        "items": [item(r) for r in pagina[:limite]],
        "totals": totales(todas),
        "next_offset": offset + limite if len(pagina) > limite else None,
    }


async def obtener(user_id: str, harvest_id: str) -> dict:
    row, _ = await _cosecha_propia(user_id, harvest_id)
    return item(row)


async def crear(user_id: str, plot_id: str, datos: dict) -> dict:
    lote = await _lote(user_id, plot_id)
    _validar_fecha(datos["harvested_at"], lote)
    ahora = tiempo.ahora()
    row = await hilo(repo.crear_cosecha, {
        **datos, "plot_id": plot_id, "created_by": user_id,
        "created_at": ahora, "updated_at": ahora,
    })
    return {
        **item(row),
        "affects_estimations": await _estimaciones_afectadas(plot_id, [datos["harvested_at"]]),
    }


async def actualizar(user_id: str, harvest_id: str, datos: dict) -> dict:
    actual, lote = await _cosecha_propia(user_id, harvest_id)
    if "harvested_at" in datos:
        if datos["harvested_at"] is None:
            raise ReglaNegocio(400, "La fecha de cosecha es obligatoria.")
        _validar_fecha(datos["harvested_at"], lote)
    if "quantity_kg" in datos and datos["quantity_kg"] is None:
        raise ReglaNegocio(400, "La cantidad cosechada es obligatoria.")
    if "currency" in datos and datos["currency"] is None:
        datos["currency"] = "COP"
    row = await hilo(repo.actualizar_cosecha, harvest_id, {**datos, "updated_at": tiempo.ahora()})
    fechas = {_fecha(actual["harvested_at"]), _fecha(row["harvested_at"])}
    return {
        **item(row),
        "affects_estimations": await _estimaciones_afectadas(actual["plot_id"], list(fechas)),
    }


async def eliminar(user_id: str, harvest_id: str) -> dict:
    actual, _ = await _cosecha_propia(user_id, harvest_id)
    await hilo(repo.borrar_cosecha, harvest_id)
    return {
        "affects_estimations": await _estimaciones_afectadas(
            actual["plot_id"], [_fecha(actual["harvested_at"])]
        ),
    }
