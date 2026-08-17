"""Campaign and Review: certification workflow."""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from app.models.identity import utcnow
class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    STAGED = "staged"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    REVOKED = "revoked"
class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus), default=CampaignStatus.DRAFT, index=True
    )
    review_mode: Mapped[str] = mapped_column(String(50), default="source_owner")
    scope: Mapped[str] = mapped_column(Text, default="{}")  # JSON, replaced whole-value
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    reviews = relationship("Review", back_populates="campaign", cascade="all, delete-orphan")
class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("campaign_id", "account_id", name="uq_review_per_campaign_account"),
        Index("ix_reviews_reviewer_status", "reviewer_id", "status"),
        Index("ix_reviews_campaign_status", "campaign_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus), default=ReviewStatus.PENDING)
    decision: Mapped[str | None] = mapped_column(String(50))
    comments: Mapped[str | None] = mapped_column(Text)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    campaign = relationship("Campaign", back_populates="reviews")
