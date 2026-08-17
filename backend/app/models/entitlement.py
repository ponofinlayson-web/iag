"""Entitlement: normalized catalog of access rights per source."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from app.models.identity import utcnow
class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (
        UniqueConstraint(
            "data_source_id", "source_column", "source_value",
            name="uq_entitlement_natural_key",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    catalog_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    privilege_level: Mapped[str | None] = mapped_column(String(20), index=True)
    source_column: Mapped[str | None] = mapped_column(String(255))
    source_value: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    data_source = relationship("DataSource", back_populates="entitlements")
    def __repr__(self) -> str:
        return f"<Entitlement {self.catalog_id}: {self.name}>"
