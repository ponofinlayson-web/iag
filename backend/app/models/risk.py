"""RiskSnapshot: one identity's score in one scoring run. Trend evidence."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.identity import utcnow
class RiskSnapshot(Base):
    __tablename__ = "risk_snapshots"
    __table_args__ = (
        Index("ix_risk_snapshots_run_id", "run_id"),
        Index("ix_risk_snapshots_identity_computed_at", "identity_id", "computed_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36))
    identity_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("identities.id", ondelete="SET NULL"), nullable=True
    )
    identity_employee_id: Mapped[str] = mapped_column(String(100))
    score: Mapped[float] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(10))
    signals: Mapped[str] = mapped_column(Text, default="{}")  # JSON {signal: points}
    factors: Mapped[str] = mapped_column(Text, default="{}")  # JSON detail rows
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    def __repr__(self) -> str:
        return f"<RiskSnapshot {self.identity_employee_id} {self.score:.1f} {self.band}>"
