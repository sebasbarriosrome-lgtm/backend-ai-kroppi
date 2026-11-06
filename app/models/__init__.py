"""Tipos de fila que representan las tablas del esquema Supabase de Kroppi."""

from datetime import date, datetime
from typing import Literal, TypedDict


HealthStatus = Literal["HEALTHY", "ALERT", "DANGER"]
SampleMethod = Literal["SAMPLING", "ESTIMATION"]


class CropType(TypedDict):
    id: str
    name: str
    scientific_name: str | None
    icon_url: str | None
    slug: str | None
    is_active: bool
    alert_threshold_pct: float
    danger_threshold_pct: float
    avg_yield_kg_per_ha: float | None
    created_at: datetime | str


class Crop(TypedDict):
    id: str
    farm_id: str
    crop_type_id: str
    name: str
    planted_at: date | str | None
    expected_harvest_at: date | str | None
    is_active: bool
    created_at: datetime | str
    updated_at: datetime | str


class Plot(TypedDict):
    id: str
    crop_id: str
    name: str
    area_ha: float
    plant_count: int | None
    variety: str | None
    latitude: float | None
    longitude: float | None
    status: HealthStatus
    last_sampled_at: datetime | str | None
    created_at: datetime | str
    updated_at: datetime | str


class PlotSample(TypedDict):
    id: str
    plot_id: str
    sampled_by: str | None
    sampled_at: datetime | str
    method: SampleMethod
    plants_evaluated: int
    plants_affected: int
    incidence_pct: float | None
    notes: str | None


class Diagnosis(TypedDict):
    id: str
    user_id: str
    image_url: str
    ai_prediction: dict
    latitude: float | None
    longitude: float | None
    user_feedback: str | None
    created_at: datetime | str
    predicted_label: str | None
    confidence: float | None
    recommendations: list | None
    plot_samples_id: str


class Farm(TypedDict):
    id: str
    owner_id: str
    name: str
    description: str | None
    department: str | None
    municipality: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    area_ha: float | None
    created_at: datetime | str
    updated_at: datetime | str


class Profile(TypedDict):
    id: str
    full_name: str | None
    phone_number: str | None
    role: str | None
    municipality: str | None
    department: str | None
    created_at: datetime | str
    updated_at: datetime | str
    avatar_url: str | None


class User(TypedDict):
    id: str
    full_name: str | None
    email: str | None
    avatar_url: str | None
    auth_provider: str | None
    created_at: datetime | str
    updated_at: datetime | str


class Harvest(TypedDict):
    id: str
    plot_id: str
    harvested_at: date
    quantity_kg: float
    price_per_kg: float | None
    notes: str | None


class LossEstimation(TypedDict):
    id: str
    plot_id: str
    created_at: datetime | str
    expected_yield_kg: float
    price_per_kg: float
    estimated_loss_amount: float
    currency: str
    source: str
    inputs: dict
    explanation: str | None


__all__ = [
    "Crop",
    "CropType",
    "Diagnosis",
    "Farm",
    "Harvest",
    "HealthStatus",
    "LossEstimation",
    "Profile",
    "Plot",
    "PlotSample",
    "SampleMethod",
    "User",
]
