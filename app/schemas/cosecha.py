from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Moneda = Literal["COP", "USD"]


def _limpiar(value: str | None) -> str | None:
    value = value.strip() if value is not None else None
    return value or None


class CosechaCrear(BaseModel):
    harvested_at: date
    quantity_kg: Decimal = Field(gt=0)
    price_per_kg: Decimal | None = Field(None, ge=0)
    currency: Moneda = "COP"
    notes: str | None = None

    _notas = field_validator("notes")(lambda cls, v: _limpiar(v))


class CosechaEditar(BaseModel):
    harvested_at: date | None = None
    quantity_kg: Decimal | None = Field(None, gt=0)
    price_per_kg: Decimal | None = Field(None, ge=0)
    currency: Moneda | None = None
    notes: str | None = None

    _notas = field_validator("notes")(lambda cls, v: _limpiar(v))
