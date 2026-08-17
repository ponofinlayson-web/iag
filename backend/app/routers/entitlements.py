"""Entitlement catalog router."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from app.core.audit_service import append_audit
from app.models.entitlement import Entitlement
from app.routers.deps import AnyUser, CertAdminUser, DbSession
router = APIRouter(prefix="/api/entitlements", tags=["entitlements"])
PRIVILEGE_LEVELS = {"low", "moderate", "high", "very_high"}
class PrivilegeIn(BaseModel):
    privilege_level: str
@router.get("")
async def list_entitlements(db: DbSession, user: AnyUser, q: str = "",
                            privilege: str = "", source_id: int = 0,
                            page: int = 1, page_size: int = 50):
    filters = []
    if q:
        like = f"%{q.lower()}%"
        filters.append(func.lower(Entitlement.name).like(like))
    if privilege:
        filters.append(Entitlement.privilege_level == privilege)
    if source_id:
        filters.append(Entitlement.data_source_id == source_id)
    total = (
        await db.execute(select(func.count()).select_from(Entitlement).where(*filters))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Entitlement).where(*filters).order_by(Entitlement.id)
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": e.id,
                "catalog_id": e.catalog_id,
                "name": e.name,
                "description": e.description,
                "privilege_level": e.privilege_level,
                "source_id": e.data_source_id,
                "last_seen_at": e.last_seen_at.isoformat() if e.last_seen_at else None,
            }
            for e in rows
        ],
    }
@router.get("/stats")
async def entitlement_stats(db: DbSession, user: AnyUser):
    total = (await db.execute(select(func.count()).select_from(Entitlement))).scalar_one()
    classified = (
        await db.execute(
            select(func.count()).select_from(Entitlement).where(
                Entitlement.privilege_level.is_not(None))
        )
    ).scalar_one()
    by_level = dict(
        (await db.execute(
            select(Entitlement.privilege_level, func.count())
            .where(Entitlement.privilege_level.is_not(None))
            .group_by(Entitlement.privilege_level)
        )).all()
    )
    return {
        "total": total,
        "classified": classified,
        "unclassified": total - classified,
        "by_level": {k or "none": v for k, v in by_level.items()},
    }
@router.put("/{entitlement_id}/privilege")
async def set_privilege(entitlement_id: int, body: PrivilegeIn, db: DbSession, user: CertAdminUser):
    if body.privilege_level not in PRIVILEGE_LEVELS:
        raise HTTPException(400, "privilege_level must be low, moderate, high, or very_high")
    e = await db.get(Entitlement, entitlement_id)
    if e is None:
        raise HTTPException(404, "Entitlement not found")
    old = e.privilege_level
    e.privilege_level = body.privilege_level
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="entitlement_privilege_set", entity_type="entitlement",
                       entity_id=entitlement_id,
                       details={"old": old, "new": body.privilege_level})
    await db.commit()
    return {"ok": True}
