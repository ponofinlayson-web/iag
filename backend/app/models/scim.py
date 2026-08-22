"""ScimSettings: single-row SCIM server config + token hash (feature 6).

Token at rest is SHA-256 only (v1 stored it reversibly encrypted —
designed out; feature-4 key pattern): reveal-once at generation, never
readable back. enabled=false + null token by default: the surface is
OFF until an admin turns it on AND generates a token (two deliberate
acts; nothing listens until both).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.identity import utcnow


DEFAULT_SCIM_CONFIG = {"enabled": False}


class ScimSettings(Base):
    """Row id=1 only. config JSON replaced whole-value on write."""

    __tablename__ = "scim_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True)
    token_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def config_dict(self) -> dict:
        import json
        return json.loads(self.config)

    def __repr__(self) -> str:
        return f"<ScimSettings id={self.id} enabled={self.config_dict().get('enabled')}>"
