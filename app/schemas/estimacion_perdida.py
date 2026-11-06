from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OutBase


class EstimacionPerdidaIn(BaseModel):
    plot_id: UUID
    expected_yield_kg: float | None = Field(None, ge=0)
    price_per_kg: float | None = Field(None, ge=0)
    estimated_loss_amount: float | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    source: str = Field(min_length=1, max_length=50)
    inputs: dict | None = None
    explanation: str | None = None


class EstimacionPerdidaOut(OutBase):
    id: UUID
    plot_id: UUID
    created_at: datetime | None = None
    expected_yield_kg: float | None = None
    price_per_kg: float | None = None
    estimated_loss_amount: float | None = None
    currency: str | None = None
    source: str
    inputs: dict | None = None
    explanation: str | None = None
