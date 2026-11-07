"""Cálculo de pérdida estimada y formato de cifras. Funciones puras (sin BD)."""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.services.tiempo import BOGOTA

_KG = Decimal("0.01")
_DECIMALES_MONTO = {"COP": Decimal("1"), "USD": Decimal("0.01")}


def dec(value) -> Decimal | None:
    """Convierte números de la BD/JSON a Decimal sin pasar por float."""
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def redondear_kg(value: Decimal) -> Decimal:
    return value.quantize(_KG, rounding=ROUND_HALF_UP)


def redondear_monto(value: Decimal, currency: str) -> Decimal:
    return value.quantize(_DECIMALES_MONTO.get(currency, _KG), rounding=ROUND_HALF_UP)


def _miles(value: Decimal, decimales: int, sep_miles: str, sep_dec: str) -> str:
    texto = f"{value:,.{decimales}f}"
    return texto.replace(",", "\0").replace(".", sep_dec).replace("\0", sep_miles)


def formato_kg(value: Decimal) -> str:
    """1200 -> '1.200 kg'; 12.5 -> '12,5 kg' (formato colombiano, hasta 2 decimales)."""
    texto = _miles(redondear_kg(value), 2, ".", ",")
    entero, _, decimales = texto.partition(",")
    decimales = decimales.rstrip("0")
    return f"{entero},{decimales} kg" if decimales else f"{entero} kg"


def formato_moneda(value: Decimal, currency: str) -> str:
    """COP -> '$2.700.000'; USD -> 'US$2,700.50'."""
    if currency == "USD":
        return "US$" + _miles(redondear_monto(value, "USD"), 2, ",", ".")
    return "$" + _miles(redondear_monto(value, "COP"), 0, ".", ",")


def calcular_perdida(
    expected_yield_kg: Decimal, harvested_kg: Decimal, price_per_kg: Decimal, currency: str
) -> dict:
    expected = dec(expected_yield_kg)
    if expected is None or expected <= 0:
        raise ValueError("Los kilos esperados deben ser mayores que cero.")
    harvested = redondear_kg(dec(harvested_kg))
    price = dec(price_per_kg)
    lost = redondear_kg(max(expected - harvested, Decimal(0)))
    surplus = redondear_kg(max(harvested - expected, Decimal(0)))
    loss_pct = redondear_kg(lost / expected * 100)
    amount = redondear_monto(lost * price, currency)

    if lost == 0:
        explicacion = "No hay pérdidas respecto a lo esperado"
        if surplus > 0:
            explicacion += f"; se superó lo esperado en {formato_kg(surplus)}"
        explicacion += "."
    else:
        explicacion = (
            f"Se esperaban {formato_kg(expected)} y se cosecharon {formato_kg(harvested)}; "
            f"faltaron {formato_kg(lost)} × {formato_moneda(price, currency)}/kg = "
            f"{formato_moneda(amount, currency)}"
        )
    return {
        "expected_yield_kg": redondear_kg(expected),
        "harvested_kg": harvested,
        "lost_kg": lost,
        "loss_pct": loss_pct,
        "surplus_kg": surplus,
        "estimated_loss_amount": amount,
        "explanation": explicacion,
    }


def _fecha(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    texto = str(value)
    if len(texto) == 10:
        return date.fromisoformat(texto)
    parsed = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BOGOTA)
    return parsed.astimezone(BOGOTA).date()


def normalizar_estimacion(row: dict) -> dict:
    """Lee primero las columnas nuevas y, si son nulas, `inputs` (registros antiguos)."""
    inputs = row.get("inputs") or {}

    def campo(nombre: str):
        valor = row.get(nombre)
        return valor if valor is not None else inputs.get(nombre)

    expected = dec(campo("expected_yield_kg"))
    harvested = dec(campo("harvested_kg"))
    surplus = (
        redondear_kg(max(harvested - expected, Decimal(0)))
        if expected is not None and harvested is not None else None
    )
    creado = _fecha(row.get("created_at"))
    return {
        **row,
        "expected_yield_kg": expected,
        "harvested_kg": harvested,
        "lost_kg": dec(campo("lost_kg")),
        "loss_pct": dec(campo("loss_pct")),
        "surplus_kg": surplus,
        "price_per_kg": dec(row.get("price_per_kg")),
        "estimated_loss_amount": dec(row.get("estimated_loss_amount")),
        "currency": (row.get("currency") or "COP").strip(),
        "period_from": _fecha(campo("period_from")) or creado,
        "period_to": _fecha(campo("period_to")) or creado,
        "harvests_in_period": inputs.get("harvests_in_period"),
    }


def a_json(value):
    """Decimal -> float y date -> ISO para las respuestas."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: a_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [a_json(v) for v in value]
    return value
