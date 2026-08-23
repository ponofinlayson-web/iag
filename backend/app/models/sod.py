"""SoD rule: an incompatible entitlement pair. Reads evaluate; writes audit."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
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
class SodEvaluation(Base):
    """One manual rule run: violation evidence at run time, not live state.

    Violations live in a JSON blob (like risk factors): rule entitlement
    refs can change or vanish after the run, and the snapshot must not.
    """
    __tablename__ = "sod_evaluations"
    __table_args__ = (Index("ix_sod_evaluations_rule_id", "rule_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sod_rules.id", ondelete="CASCADE")
    )
    violation_count: Mapped[int] = mapped_column(Integer)
    violations: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    def __repr__(self) -> str:
        return f"<SodEvaluation run={self.run_id} rule={self.rule_id} n={self.violation_count}>"
