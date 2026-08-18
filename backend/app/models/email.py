"""EmailOutbox: one outbound reminder per review, claimed by the in-app worker.

Outbound only (ARCHITECTURE design slot): rows are enqueued on campaign start
and delivered by a worker inside each app replica. Never a writer of app state
beyond its own delivery bookkeeping.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.identity import utcnow


class OutboxStatus:
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        UniqueConstraint("review_id", name="uq_email_outbox_review"),
        Index("ix_email_outbox_status_due", "status", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    review_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reviews.id", ondelete="CASCADE")
    )
    reviewer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE")
    )
    recipient: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Plain TEXT status (not a DB enum) per fork-A spec; values in OutboxStatus.
    status: Mapped[str] = mapped_column(String(20), default=OutboxStatus.PENDING)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Claim/finalize bumps drive stuck-row reclaim (sending too long).
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:
        return f"<EmailOutbox {self.id} {self.status}>"
