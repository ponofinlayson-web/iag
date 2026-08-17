"""DataSource and Account: where access data comes from, and per-source rows."""
from __future__ import annotations

import enum
from datetime import datetime
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from app.models.identity import utcnow
class SourceType(str, enum.Enum):
    CSV = "csv"
    XLSX = "xlsx"
    LDAP = "ldap"
    ENTRA = "entra"
    SQL = "sql"
class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    source_type: Mapped[SourceType] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_identity_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("identities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    column_mapping: Mapped[dict | None] = mapped_column(Text, default=None)  # JSON blob
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    accounts = relationship("Account", back_populates="data_source", cascade="all, delete-orphan")
    entitlements = relationship("Entitlement", back_populates="data_source")
class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("data_source_id", "account_value", name="uq_account_per_source"),
        Index("ix_accounts_source_identity", "data_source_id", "identity_id"),
        Index("ix_accounts_privilege", "privilege_level"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    identity_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("identities.id", ondelete="SET NULL"), index=True
    )
    account_type: Mapped[str | None] = mapped_column(String(50))
    account_value: Mapped[str] = mapped_column(String(255))
    entitlement_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("entitlements.id", ondelete="SET NULL"), index=True
    )
    privilege_level: Mapped[str | None] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    data_source = relationship("DataSource", back_populates="accounts")
    identity = relationship("Identity", back_populates="accounts")
    entitlement = relationship("Entitlement")
    def __repr__(self) -> str:
        return f"<Account {self.account_value}>"
