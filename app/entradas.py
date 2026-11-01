from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


def _fechas_ok(planted, harvest):
    if planted and harvest and harvest < planted:
        raise ValueError("La cosecha estimada no puede ser anterior a la siembra.")


class CultivoIn(BaseModel):
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


class LoteIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    area_ha: float = Field(gt=0, le=100000)
    plant_count: int | None = Field(None, ge=1)
    variety: str | None = Field(None, max_length=100)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def _v(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Envía latitude y longitude juntas, o ninguna.")
        return self


class LotePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    area_ha: float | None = Field(None, gt=0, le=100000)
    plant_count: int | None = Field(None, ge=1)
    variety: str | None = Field(None, max_length=100)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)


class MuestreoIn(BaseModel):
    diagnostic_ids: list[UUID] = Field(min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=500)