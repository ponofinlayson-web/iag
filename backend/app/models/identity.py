"""Identity: the governed person record. Canonical key = employee_id."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
def utcnow() -> datetime:
    # Naive-UTC by contract: DB columns are TIMESTAMP WITHOUT TIME ZONE and
    # asyncpg rejects aware datetimes for them. SQLite masks this by
    # round-tripping the offset, Postgres does not.
    return datetime.now(timezone.utc).replace(tzinfo=None)
class Identity(Base):
    __tablename__ = "identities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100), index=True)
    job_title: Mapped[str | None] = mapped_column(String(100))
    manager_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("identities.id", ondelete="SET NULL"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str | None] = mapped_column(String(50), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    manager = relationship("Identity", remote_side=[id], backref="direct_reports")
    accounts = relationship("Account", back_populates="identity")
    def __repr__(self) -> str:
        return f"<Identity {self.employee_id}>"
