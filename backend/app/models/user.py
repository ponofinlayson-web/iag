"""User: a login account backed by exactly one Identity."""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from app.models.identity import utcnow
class Role(str, enum.Enum):
    SYSTEM_ADMIN = "system_admin"
    CERTIFICATION_ADMIN = "certification_admin"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"
    REPORT_VIEWER = "report_viewer"
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("identities.id", ondelete="CASCADE"), unique=True, index=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.REVIEWER, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    identity = relationship("Identity", backref="user_account", uselist=False, lazy="joined")
    @property
    def username(self) -> str | None:
        return self.identity.username if self.identity else None
    @property
    def email(self) -> str | None:
        identity = self.identity
        return identity.email if identity else None
