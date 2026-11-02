from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .base import Latitud, Longitud, OutBase


class DiagnosticoIn(BaseModel):
    """Datos que acompañan a la imagen al pedir un diagnóstico."""

    plot_samples_id: UUID
    latitude: Latitud | None = None
    longitude: Longitud | None = None


class DiagnosticoFeedback(BaseModel):
    user_feedback: str = Field(min_length=1, max_length=500)


class DiagnosticoOut(OutBase):
    id: UUID
    user_id: UUID
    plot_samples_id: UUID
    image_url: str  # URL firmada; en BD se guarda la ruta en Storage
    ai_prediction: dict
    predicted_label: str | None = None
    confidence: float | None = None
    recommendations: list | None = None
    latitude: float | None = None
    longitude: float | None = None
    user_feedback: str | None = None
    created_at: datetime | None = None
