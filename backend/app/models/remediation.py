"""Remediation rules, actions, and the single-row settings store.

Feature-3 spec (RATIFIED 2026-08-20): remediation is the workflow layer —
decide, record, notify, hand off (D1). It never mutates the access
mirror or auth state; enforcement write-back is feature 6's scope.
Delivery (email or webhook) is executed by the in-replica worker
(fork-A), and the action row itself is the delivery record (D2).
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.identity import utcnow


class RemediationStatus:
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RemediationActionType:
    NOTIFY_OWNER = "notify_owner"
    WEBHOOK = "webhook"
    ENFORCE = "enforce"


class RemediationEnforceTarget:
    """feature-6 D6: least-destructive default for the most dangerous class."""

    REMOVE_ENTITLEMENT = "remove_entitlement"
    DISABLE_ACCOUNT = "disable_account"


ENFORCE_TARGETS = {
    RemediationEnforceTarget.REMOVE_ENTITLEMENT,
    RemediationEnforceTarget.DISABLE_ACCOUNT,
}


# Single-row settings store (D4). Whole-value JSON replaced on write.
DEFAULT_CONFIG = {
    "enabled": True,
    "default_action": RemediationActionType.NOTIFY_OWNER,
    "require_approval_for_high_risk": True,
}


class RemediationRule(Base):
    """Trigger conditions (AND; all-null filters = catch-all) + action."""

    __tablename__ = "remediation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    privilege_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Python regex, case-insensitive against entitlement NAME; compiled
    # (validated) at rule save (D6) — see routers/remediation.py.
    entitlement_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(50), default=RemediationActionType.NOTIFY_OWNER)
    # feature-6: enforce rules pick a directory write-back target; null =
    # remove_entitlement (D6 least-destructive default). Plain column, no enum.
    target: Mapped[str | None] = mapped_column(String(20), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    times_triggered: Mapped[int] = mapped_column(Integer, default=0)
    times_executed: Mapped[int] = mapped_column(Integer, default=0)
    times_failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return f"<RemediationRule {self.name} ({self.action})>"


class RemediationAction(Base):
    """One matched (or default) follow-up for one revoked review.

    Multiple rules may match one revocation, so there is NO unique
    constraint on review_id. `snapshot` freezes the display payload at
    trigger time; it survives FK deaths and is the webhook/email body's
    data source. The action row IS the delivery record (D2).
    """

    __tablename__ = "remediation_actions"
    __table_args__ = (Index("ix_remediation_actions_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("remediation_rules.id", ondelete="SET NULL"), nullable=True
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    snapshot: Mapped[str] = mapped_column(Text)  # JSON blob, frozen at creation
    action_type: Mapped[str] = mapped_column(String(50))
    # Plain TEXT status per house convention; values in RemediationStatus.
    status: Mapped[str] = mapped_column(String(20), default=RemediationStatus.APPROVED)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    def snapshot_dict(self) -> dict:
        return json.loads(self.snapshot)

    def __repr__(self) -> str:
        return f"<RemediationAction {self.id} {self.action_type} -> {self.status}>"


class RemediationSettings(Base):
    """Row id=1 only. config JSON replaced whole-value on write."""

    __tablename__ = "remediation_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[str] = mapped_column(Text)

    def config_dict(self) -> dict:
        return json.loads(self.config)
