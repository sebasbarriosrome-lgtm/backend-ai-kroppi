from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from .base import OutBase


def _fechas_ok(planted, harvest):
    if planted and harvest and harvest < planted:
        raise ValueError("La cosecha estimada no puede ser anterior a la siembra.")


class CultivoIn(BaseModel):
    farm_id: UUID
    crop_type_id: UUID
    name: str = Field(min_length=1, max_length=100)
    planted_at: date | None = None
    expected_harvest_at: date | None = None

    @model_validator(mode="after")
    def _v(self):
        _fechas_ok(self.planted_at, self.expected_harvest_at)
        return self


class CultivoPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    planted_at: date | None = None
    expected_harvest_at: date | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _v(self):
        _fechas_ok(self.planted_at, self.expected_harvest_at)
        return self


class CultivoOut(OutBase):
    id: UUID
    farm_id: UUID
    crop_type_id: UUID
    name: str
    planted_at: date | None = None
    expected_harvest_at: date | None = None
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
