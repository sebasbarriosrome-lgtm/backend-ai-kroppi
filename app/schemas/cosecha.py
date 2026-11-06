from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OutBase


class CosechaIn(BaseModel):
    plot_id: UUID
    harvested_at: date
    quantity_kg: float = Field(gt=0)
    price_per_kg: float | None = Field(None, ge=0)
    notes: str | None = None


class CosechaPatch(BaseModel):
    harvested_at: date | None = None
    quantity_kg: float | None = Field(None, gt=0)
    price_per_kg: float | None = Field(None, ge=0)
    notes: str | None = None


class CosechaOut(OutBase):
    id: UUID
    plot_id: UUID
    harvested_at: date
    quantity_kg: float
    price_per_kg: float | None = None
    notes: str | None = None
