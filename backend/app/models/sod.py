"""SoD rule: an incompatible entitlement pair. Reads evaluate; writes audit."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.identity import utcnow
class SodRule(Base):
    __tablename__ = "sod_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entitlement_a_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entitlements.id", ondelete="CASCADE"), index=True
    )
    entitlement_b_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entitlements.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[str] = mapped_column(String(20), default="high")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    def __repr__(self) -> str:
        return f"<SodRule {self.name}>"
