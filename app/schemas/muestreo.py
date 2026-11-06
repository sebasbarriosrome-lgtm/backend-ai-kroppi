from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from .base import MetodoMuestreo, OutBase


def _plantas_ok(evaluadas, afectadas):
    if evaluadas is not None and afectadas is not None and afectadas > evaluadas:
        raise ValueError("Las plantas afectadas no pueden superar las evaluadas.")


class MuestreoIn(BaseModel):
    sampled_at: datetime
    method: MetodoMuestreo = "SAMPLING"
    plants_evaluated: int = Field(gt=0)
    plants_affected: int = Field(ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def _v(self):
        _plantas_ok(self.plants_evaluated, self.plants_affected)
        return self


class MuestreoPatch(BaseModel):
    sampled_at: datetime | None = None
    method: MetodoMuestreo | None = None
    plants_evaluated: int | None = Field(None, gt=0)
    plants_affected: int | None = Field(None, ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def _v(self):
        _plantas_ok(self.plants_evaluated, self.plants_affected)
        return self


class MuestreoOut(OutBase):
    id: UUID
    plot_id: UUID
    sampled_by: UUID | None = None
    sampled_at: datetime
    method: MetodoMuestreo
    plants_evaluated: int
    plants_affected: int
    incidence_pct: float | None = None
    notes: str | None = None
