from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from .cosecha import Moneda, _limpiar


class PerdidaEstimadaCrear(BaseModel):
    """Entradas del agricultor. El resto (cosechado, pérdida, monto...) lo calcula el backend."""

    expected_yield_kg: Decimal = Field(gt=0)
    price_per_kg: Decimal = Field(ge=0)
    currency: Moneda = "COP"
    period_from: date
    period_to: date
    notes: str | None = None

    _notas = field_validator("notes")(lambda cls, v: _limpiar(v))

    @model_validator(mode="after")
    def _periodo(self):
        if self.period_to < self.period_from:
            raise ValueError("La fecha final del periodo no puede ser anterior a la inicial.")
        return self


class PerdidaEstimadaEditar(BaseModel):
    expected_yield_kg: Decimal | None = Field(None, gt=0)
    price_per_kg: Decimal | None = Field(None, ge=0)
    currency: Moneda | None = None
    period_from: date | None = None
    period_to: date | None = None
    notes: str | None = None

    _notas = field_validator("notes")(lambda cls, v: _limpiar(v))
