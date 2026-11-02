from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .base import Latitud, Longitud, OutBase


class FincaIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    department: str | None = Field(None, max_length=100)
    municipality: str | None = Field(None, max_length=100)
    address: str | None = None
    latitude: Latitud | None = None
    longitude: Longitud | None = None
    area_ha: float | None = Field(None, gt=0)


class FincaPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    department: str | None = Field(None, max_length=100)
    municipality: str | None = Field(None, max_length=100)
    address: str | None = None
    latitude: Latitud | None = None
    longitude: Longitud | None = None
    area_ha: float | None = Field(None, gt=0)


class FincaOut(OutBase):
    id: UUID
    owner_id: UUID
    name: str
    description: str | None = None
    department: str | None = None
    municipality: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    area_ha: float | None = None
    created_at: datetime
    updated_at: datetime
