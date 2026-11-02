from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .base import EstadoSalud, Latitud, Longitud, OutBase


class LoteIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    area_ha: float = Field(gt=0)
    plant_count: int | None = Field(None, ge=0)
    variety: str | None = Field(None, max_length=100)
    latitude: Latitud | None = None
    longitude: Longitud | None = None


class LotePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    area_ha: float | None = Field(None, gt=0)
    plant_count: int | None = Field(None, ge=0)
    variety: str | None = Field(None, max_length=100)
    latitude: Latitud | None = None
    longitude: Longitud | None = None


class LoteOut(OutBase):
    id: UUID
    crop_id: UUID
    name: str
    area_ha: float
    plant_count: int | None = None
    variety: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: EstadoSalud
    last_sampled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
