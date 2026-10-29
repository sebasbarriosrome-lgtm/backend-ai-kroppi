"""Modelos que reflejan las tablas YA creadas en Supabase (crops, diseases, diagnostics).
No se usa create_all: el esquema lo gestiona quien administra la base de datos."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

UUIDStr = UUID(as_uuid=False)


class Base(DeclarativeBase):
    pass


class Crop(Base):
    __tablename__ = "crops"
    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)


class Disease(Base):
    __tablename__ = "diseases"
    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True)
    crop_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("crops.id"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    scientific_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    pathogen_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    symptoms: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    general_recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    requires_agronomist: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Diagnosis(Base):
    """Tabla public.diagnostics. `ai_prediction` guarda
    {model_version, confidence, top, recommendations}. `image_url` guarda la RUTA
    dentro del bucket de Storage (la API la convierte en URL temporal al responder)."""
    __tablename__ = "diagnostics"
    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True)
    user_id: Mapped[str] = mapped_column(UUIDStr)
    crop_id: Mapped[str] = mapped_column(UUIDStr, ForeignKey("crops.id"))
    disease_id: Mapped[str | None] = mapped_column(UUIDStr, ForeignKey("diseases.id"), nullable=True)
    image_url: Mapped[str] = mapped_column(Text)
    ai_prediction: Mapped[dict] = mapped_column(JSONB)
    latitude: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    crop: Mapped[Crop] = relationship()
    disease: Mapped[Disease | None] = relationship()
