"""SyncRun: one connector synchronization job per data source.

Feature-2 spec: worker claims a run (fork-A shape), fetches the remote
snapshot OUTSIDE any transaction, then applies it + one audit entry in a
single finalizing commit. The partial unique index allows at most one
in-flight (pending/syncing) run per source, which is what makes duplicate
enqueues from N replicas impossible: second INSERT loses the index race.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.identity import utcnow


class SyncStatus:
    PENDING = "pending"
    SYNCING = "syncing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Triggered:
    MANUAL = "manual"
    SCHEDULE = "schedule"


# Partial unique index, one in-flight run per source. Both dialects take a
# SQL expression (plain strings are not coerced by SQLAlchemy 2.x).
_INFLIGHT = text("status IN ('pending', 'syncing')")


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index(
            "uq_sync_run_inflight",
            "data_source_id",
            unique=True,
            postgresql_where=_INFLIGHT,
            sqlite_where=_INFLIGHT,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    # Plain TEXT status (not a DB enum) per house convention (OutboxStatus).
    status: Mapped[str] = mapped_column(String(20), default=SyncStatus.PENDING)
    triggered_by: Mapped[str] = mapped_column(String(20), default=Triggered.MANUAL)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stats: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def __repr__(self) -> str:
        return f"<SyncRun {self.id} source={self.data_source_id} {self.status}>"
