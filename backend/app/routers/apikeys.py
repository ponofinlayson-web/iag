"""API-key lifecycle: create (full key revealed once), list, soft revoke."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.core import apikeys as keyfns
from app.core.audit_service import append_audit
from app.models.apikey import ApiKey
from app.models.user import Role
from app.routers.deps import AdminUser, DbSession

KEY_ROLES = (Role.AUDITOR, Role.REPORT_VIEWER)
router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def _row_out(k: ApiKey) -> dict:
    return {
        "id": k.id,
        "name": k.name,
        "key_prefix": k.key_prefix,
        "role": k.role.value,
        "is_active": k.is_active,
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


class KeyIn(BaseModel):
    name: str
    role: str
    expires_at: datetime | None = None


@router.get("")
async def list_keys(db: DbSession, user: AdminUser):
    rows = (await db.execute(select(ApiKey).order_by(ApiKey.id.desc()))).scalars().all()
    return {"items": [_row_out(k) for k in rows]}


@router.post("", status_code=201)
async def create_key(body: KeyIn, db: DbSession, user: AdminUser):
    name = body.name.strip()
    if not name or len(name) > 100:
        raise HTTPException(400, "name must be 1-100 characters")
    try:
        role = Role(body.role)
    except ValueError:
        raise HTTPException(400, f"unknown role: {body.role}")
    if role not in KEY_ROLES:
        raise HTTPException(400, "API key role must be auditor or report_viewer")
    expires = None
    if body.expires_at is not None:
        if body.expires_at.tzinfo is not None:
            expires = body.expires_at.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            expires = body.expires_at
        if keyfns.is_expired(expires):
            raise HTTPException(400, "expires_at must be in the future")
    dup = (await db.execute(select(ApiKey).where(ApiKey.name == name))).scalars().first()
    if dup:
        raise HTTPException(409, "API key name already exists")
    row = ApiKey(name=name, key_prefix="", key_hash="", role=role,
                 is_active=True, expires_at=expires, created_by_id=user.id)
    db.add(row)
    await db.flush()
    full_key, prefix, digest = keyfns.generate_key(row.id)
    row.key_prefix = prefix
    row.key_hash = digest
    await append_audit(db, actor_id=user.id, actor_username=user.username or "",
                       action="api_key_created", entity_type="api_key", entity_id=row.id,
                       details={"name": row.name, "key_id": row.id, "role": row.role.value,
                                "expires_at": row.expires_at.isoformat() if row.expires_at else None})
    await db.commit()
    return {"key": full_key, **_row_out(row)}


@router.post("/{key_id}/revoke")
async def revoke_key(key_id: int, db: DbSession, user: AdminUser):
    row = await db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(404, "API key not found")
    if not row.is_active:
        return {"ok": True, "already_revoked": True}
    row.is_active = False
    await append_audit(db, actor_id=user.id, actor_username=user.username or "",
                       action="api_key_revoked", entity_type="api_key", entity_id=row.id,
                       details={"name": row.name, "key_id": row.id})
    await db.commit()
    return {"ok": True, "already_revoked": False}
