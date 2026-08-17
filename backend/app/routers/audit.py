"""Audit router: viewer, chain verification, export."""
from __future__ import annotations
import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from app.core.audit_service import verify_chain
from app.models.audit import AuditEntry
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
