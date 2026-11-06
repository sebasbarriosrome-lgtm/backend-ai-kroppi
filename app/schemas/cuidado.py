from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TipoCuidado = Literal[
    "FERTILIZATION", "FUNGICIDE", "INSECTICIDE", "HERBICIDE", "PRUNING",
    "WEEDING", "IRRIGATION", "CULTURAL_CONTROL", "OTHER",
]
UnidadCantidad = Literal["kg", "g", "L", "mL", "unit"]
MetodoAplicacion = Literal["SPRAYING", "DRENCH", "BROADCAST", "MANUAL", "DRIP", "OTHER"]


class CuidadoCrear(BaseModel):
    applied_at: date
    activity_type: TipoCuidado
    product_name: str | None = None
    active_ingredient: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    quantity_unit: UnidadCantidad | None = None
    application_method: MetodoAplicacion | None = None
    target_disease_code: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("product_name", "active_ingredient", "target_disease_code", "notes")
    @classmethod
    def limpiar_texto(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None

    @model_validator(mode="after")
    def validar_unidad(self):
        if (self.quantity is None) != (self.quantity_unit is None):
            raise ValueError("La cantidad y su unidad deben enviarse juntas.")
        return self


class CuidadoPatch(BaseModel):
    applied_at: date | None = None
    activity_type: TipoCuidado | None = None
    product_name: str | None = None
    active_ingredient: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    quantity_unit: UnidadCantidad | None = None
    application_method: MetodoAplicacion | None = None
    target_disease_code: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("product_name", "active_ingredient", "target_disease_code", "notes")
    @classmethod
    def limpiar_texto(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None

    @model_validator(mode="after")
    def validar_requeridos(self):
        enviados = self.model_fields_set
        if "applied_at" in enviados and self.applied_at is None:
            raise ValueError("La fecha de aplicación no puede ser nula.")
        if "activity_type" in enviados and self.activity_type is None:
            raise ValueError("El tipo de actividad no puede ser nulo.")
        return self
