from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OutBase


class PerfilPatch(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=150)
    phone_number: str | None = Field(None, max_length=30)
    municipality: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)
    avatar_url: str | None = None


class PerfilOut(OutBase):
    id: UUID
    full_name: str
    phone_number: str | None = None
    role: str | None = None
    municipality: str | None = None
    department: str | None = None
    avatar_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
