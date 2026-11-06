from datetime import datetime
from uuid import UUID

from .base import OutBase


class UsuarioOut(OutBase):
    id: UUID
    full_name: str | None = None
    email: str
    avatar_url: str | None = None
    auth_provider: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
