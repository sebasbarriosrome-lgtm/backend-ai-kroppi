"""Modelos que reflejan las tablas YA creadas en Supabase. No se usa create_all."""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (Boolean, Date, DateTime, FetchedValue, ForeignKey, Integer,
                        Numeric, Text, create_engine, func)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

UUIDStr = UUID(as_uuid=False)
Num = Numeric(asdecimal=False)
ESTADO = ENUM("HEALTHY", "ALERT", "DANGER", name="health_status", create_type=False)
METODO = ENUM("SAMPLING", "ESTIMATION", name="sample_method", create_type=False)


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class CropType(Base):
    """Catálogo (café, tomate...) con los umbrales de alerta."""
    __tablename__ = "crop_types"
    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean)
    alert_threshold_pct: Mapped[float] = mapped_column(Num)
    danger_threshold_pct: Mapped[float] = mapped_column(Num)
    avg_yield_kg_per_ha: Mapped[float | None] = mapped_column(Num, nullable=True)


class Crop(Base):
    """Cultivo registrado por el usuario."""
    __tablename__ = "crops"
    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(UUIDStr)
    crop_type_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("crop_types.id"))
    name: Mapped[str] = mapped_column(Text)
    planted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_harvest_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())
    crop_type: Mapped[CropType] = relationship()
    plots: Mapped[list["Plot"]] = relationship(back_populates="crop")


class Plot(Base):
    __tablename__ = "plots"
    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    crop_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("crops.id"))
    name: Mapped[str] = mapped_column(Text)
    area_ha: Mapped[float] = mapped_column(Num)
    plant_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variety: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Num, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Num, nullable=True)
    status: Mapped[str] = mapped_column(ESTADO, default="HEALTHY")
    last_sampled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())
    crop: Mapped[Crop] = relationship(back_populates="plots")


class PlotSample(Base):
    __tablename__ = "plot_samples"
    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=_uuid)
    plot_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("plots.id"))
    sampled_by: Mapped[str | None] = mapped_column(UUIDStr, nullable=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    method: Mapped[str] = mapped_column(METODO, default="SAMPLING")
    plants_evaluated: Mapped[int] = mapped_column(Integer)
    plants_affected: Mapped[int] = mapped_column(Integer)
    # Columna GENERADA en Postgres: nunca se inserta, solo se lee.
    incidence_pct: Mapped[float | None] = mapped_column(
        Num, nullable=True, server_default=FetchedValue(), server_onupdate=FetchedValue())
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Diagnosis(Base):
    """public.diagnostics. `image_url` guarda la RUTA en Storage (se firma al responder)."""
    __tablename__ = "diagnostics"
    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True)
    user_id: Mapped[str] = mapped_column(UUIDStr)
    crop_type_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("crop_types.id"))
    plot_id: Mapped[str | None] = mapped_column(UUIDStr, ForeignKey("plots.id"), nullable=True)
    image_url: Mapped[str] = mapped_column(Text)
    ai_prediction: Mapped[dict] = mapped_column(JSONB)
    predicted_label: Mapped[str | None] = mapped_column(Text, nullable=True)  # None = no concluyente
    confidence: Mapped[float | None] = mapped_column(Num, nullable=True)
    recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Num, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Num, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    crop_type: Mapped[CropType] = relationship()