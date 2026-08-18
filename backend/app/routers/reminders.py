"""Reminder outbox: READ-ONLY visibility surface (fork A spec).

The only writer is the campaign lifecycle (enqueue/cancel) and the worker
(claim/finalize). This router never mutates a row.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.models.campaign import Campaign
from app.models.email import EmailOutbox
from app.routers.deps import CertAdminUser, DbSession

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

STATUSES = {"pending", "sending", "sent", "failed", "cancelled"}


def _row_out(row: EmailOutbox) -> dict:
    return {
        "id": row.id,
        "campaign_id": row.campaign_id,
        "review_id": row.review_id,
        "reviewer_id": row.reviewer_id,
        "recipient": row.recipient,
        "subject": row.subject,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "attempts": row.attempts,
        "status": row.status,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/outbox")
async def list_outbox(
    db: DbSession,
    user: CertAdminUser,
    campaign_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    if status is not None and status not in STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(STATUSES)}")
    stmt = select(EmailOutbox)
    if campaign_id is not None:
        stmt = stmt.where(EmailOutbox.campaign_id == campaign_id)
    if status is not None:
        stmt = stmt.where(EmailOutbox.status == status)
    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()
    rows = (await db.execute(
        stmt.order_by(EmailOutbox.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {"items": [_row_out(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


@router.get("/campaigns/{campaign_id}")
async def campaign_reminders(
    campaign_id: int,
    db: DbSession,
    user: CertAdminUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """Rows for one campaign. Mounts under /api/reminders to keep the read-only
    surface in one router; the campaign-exists check mirrors house 404 style."""
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    stmt = select(EmailOutbox).where(EmailOutbox.campaign_id == campaign_id)
    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()
    rows = (await db.execute(
        stmt.order_by(EmailOutbox.id).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    by_status: dict[str, int] = {}
    for r in (await db.execute(
        select(EmailOutbox.status, func.count())
        .where(EmailOutbox.campaign_id == campaign_id)
        .group_by(EmailOutbox.status)
    )).all():
        by_status[r[0]] = r[1]
    return {"campaign_id": campaign_id, "total": total, "by_status": by_status,
            "items": [_row_out(r) for r in rows],
            "page": page, "page_size": page_size}
