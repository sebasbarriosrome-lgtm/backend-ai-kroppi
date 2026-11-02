from datetime import datetime
from uuid import UUID

from .base import OutBase


class TipoCultivoOut(OutBase):
    """Catálogo de solo lectura (café, tomate...) con los umbrales de alerta."""

    id: UUID
    name: str
    scientific_name: str | None = None
    icon_url: str | None = None
    is_active: bool | None = None
    slug: str | None = None
    alert_threshold_pct: float
    danger_threshold_pct: float
    avg_yield_kg_per_ha: float | None = None
    created_at: datetime | None = None
