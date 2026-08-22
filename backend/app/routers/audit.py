"""Audit router: viewer, chain verification, export."""
from __future__ import annotations
import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from app.core.audit_service import verify_chain
from app.models.audit import GENESIS, AuditEntry
from app.models.user import Role, User
from app.routers.deps import DbSession, require_roles
AuditViewer = Annotated[User, Depends(require_roles(Role.AUDITOR, Role.SYSTEM_ADMIN, Role.CERTIFICATION_ADMIN))]
router = APIRouter(prefix="/api/audit", tags=["audit"])
@router.get("")
async def list_audit(db: DbSession, user: AuditViewer, action: str = "",
                     entity_type: str = "", page: int = 1, page_size: int = 50):
    q = select(AuditEntry).order_by(AuditEntry.id.desc())
    if action:
        q = q.where(AuditEntry.action == action)
    if entity_type:
        q = q.where(AuditEntry.entity_type == entity_type)
    total = (await db.execute(select(func.count()).select_from(AuditEntry))).scalar_one()
    rows = (await db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {
        "total": total, "page": page,
        "items": [
            {
                "id": e.id,
                "ts": e.ts.isoformat() if e.ts else None,
                "actor_username": e.actor_username,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "details": e.details,
                "record_hash": e.record_hash[:16] + "...",
            }
            for e in rows
        ],
    }
@router.get("/verify")
async def verify(db: DbSession, user: AuditViewer):
    return await verify_chain(db)
@router.get("/export")
async def export_audit(db: DbSession, user: AuditViewer):
    rows = (await db.execute(select(AuditEntry).order_by(AuditEntry.id))).scalars().all()
    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "ts", "actor", "action", "entity_type", "entity_id", "prev_hash", "record_hash"])
        for e in rows:
            w.writerow([e.id, e.ts, e.actor_username, e.action, e.entity_type,
                        e.entity_id, e.prev_hash, e.record_hash])
        yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv")


FEED_DEFAULT_LIMIT = 500
FEED_MAX_LIMIT = 5000


def _feed_row(e: AuditEntry) -> dict:
    try:
        details = json.loads(e.details)
    except (TypeError, ValueError):
        details = e.details
    return {
        "id": e.id,
        "ts": e.ts.isoformat() if e.ts else None,
        "actor_id": e.actor_id,
        "actor_username": e.actor_username,
        "action": e.action,
        "entity_type": e.entity_type,
        "entity_id": e.entity_id,
        "details": details,
        "prev_hash": e.prev_hash,
        "record_hash": e.record_hash,
    }


@router.get("/feed")
async def siem_feed(
    db: DbSession,
    user: AuditViewer,
    after_id: int = 0,
    limit: int = FEED_DEFAULT_LIMIT,
):
    """Pull-only SIEM feed: JSONL pages of audit entries in id order."""
    limit = max(1, min(limit, FEED_MAX_LIMIT))
    rows = (
        await db.execute(
            select(AuditEntry)
            .where(AuditEntry.id > after_id)
            .order_by(AuditEntry.id.asc())
            .limit(limit)
        )
    ).scalars().all()
    last_id = rows[-1].id if rows else after_id
    head_row = (
        await db.execute(
            select(AuditEntry.id, AuditEntry.record_hash)
            .order_by(AuditEntry.id.desc())
            .limit(1)
        )
    ).first()
    head = head_row.record_hash if head_row else GENESIS

    def gen():
        for e in rows:
            yield json.dumps(_feed_row(e), separators=(",", ":")) + "\n"

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={
            "X-IAG-Last-Id": str(last_id),
            "X-IAG-Head": head,
        },
    )


@router.get("/feed/stats")
async def feed_stats(db: DbSession, user: AuditViewer):
    """Poller preflight: totals + chain health before pulling pages."""
    total = (
        await db.execute(select(func.count()).select_from(AuditEntry))
    ).scalar_one()
    last_row = (
        await db.execute(
            select(AuditEntry.id, AuditEntry.ts, AuditEntry.record_hash)
            .order_by(AuditEntry.id.desc())
            .limit(1)
        )
    ).first()
    chain = await verify_chain(db)
    return {
        "total_entries": total,
        "last_id": last_row.id if last_row else 0,
        "last_ts": last_row.ts.isoformat() if last_row else None,
        "chain_head": last_row.record_hash if last_row else GENESIS,
        "chain_valid": chain["valid"],
    }
