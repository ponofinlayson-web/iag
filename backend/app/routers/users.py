"""Users router: admin management of login accounts (Feature 7, D1).

Every state change is audit-chained in the same transaction. No DELETE:
deactivation preserves audit referential integrity instead. Guards read
the DB row each request (deps.get_current_user), so role/status/unlock
changes apply on the caller's next request with no token versioning.
"""
from __future__ import annotations

from datetime import timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from app.core.audit_service import append_audit
from app.core.security import hash_password
from app.models.audit import AuditEntry
from app.models.identity import Identity, utcnow
from app.models.user import Role, User
from app.routers.deps import AdminUser, DbSession

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    identity_id: int
    role: Role
    password: str = Field(min_length=8, max_length=200)


class RoleChange(BaseModel):
    role: Role


class StatusChange(BaseModel):
    is_active: bool


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=200)


def _actor_name(principal: AdminUser) -> str:
    # API-key principals cannot reach these write routes (read-only choke),
    # but the read routes accept any system_admin principal shape.
    ident = getattr(principal, "identity", None)
    return ident.username if ident is not None else principal.name


def _serialize(user: User, last_login=None) -> dict:
    ident = user.identity
    return {
        "id": user.id,
        "identity_id": user.identity_id,
        "username": ident.username if ident else None,
        "email": ident.email if ident else None,
        "first_name": ident.first_name if ident else None,
        "last_name": ident.last_name if ident else None,
        "department": ident.department if ident else None,
        "role": user.role.value,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "failed_attempts": user.failed_attempts,
        "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        "last_login": last_login.isoformat() if last_login else None,
    }


async def _last_logins(db: DbSession) -> dict[int, object]:
    rows = await db.execute(
        select(AuditEntry.actor_id, func.max(AuditEntry.ts))
        .where(AuditEntry.action == "login", AuditEntry.actor_id.is_not(None))
        .group_by(AuditEntry.actor_id)
    )
    return {actor: ts for actor, ts in rows.all()}


async def _get_or_404(db: DbSession, user_id: int) -> User:
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    return u


@router.get("")
async def list_users(db: DbSession, user: AdminUser):
    users = (await db.execute(select(User).order_by(User.id))).scalars().all()
    last = await _last_logins(db)
    return {"items": [_serialize(u, last.get(u.id)) for u in users]}


@router.get("/{user_id}")
async def get_user(user_id: int, db: DbSession, user: AdminUser):
    u = await _get_or_404(db, user_id)
    last = await _last_logins(db)
    since = utcnow() - timedelta(days=30)
    activity = await db.scalar(
        select(func.count())
        .select_from(AuditEntry)
        .where(AuditEntry.actor_id == user_id, AuditEntry.ts >= since)
    )
    out = _serialize(u, last.get(user_id))
    out["recent_activity_count"] = activity or 0
    return out


@router.post("")
async def create_user(body: UserCreate, db: DbSession, user: AdminUser):
    ident = await db.get(Identity, body.identity_id)
    if ident is None:
        raise HTTPException(404, "Identity not found")
    taken = await db.scalar(
        select(func.count()).select_from(User).where(User.identity_id == body.identity_id)
    )
    if taken:
        raise HTTPException(409, "Identity already has a login account")
    u = User(
        identity_id=body.identity_id,
        password_hash=hash_password(body.password),
        role=body.role,
        must_change_password=True,
    )
    db.add(u)
    await db.flush()
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=_actor_name(user),
        action="user_created",
        entity_type="user",
        entity_id=u.id,
        details={"username": ident.username, "role": body.role.value},
    )
    await db.commit()
    return _serialize(u)


@router.put("/{user_id}/role")
async def change_role(user_id: int, body: RoleChange, db: DbSession, user: AdminUser):
    if user_id == user.id:
        raise HTTPException(400, "Cannot change your own role")
    u = await _get_or_404(db, user_id)
    previous = u.role
    u.role = body.role
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=_actor_name(user),
        action="user_role_changed",
        entity_type="user",
        entity_id=user_id,
        details={"from": previous.value, "to": body.role.value},
    )
    await db.commit()
    return _serialize(u)


@router.put("/{user_id}/status")
async def change_status(user_id: int, body: StatusChange, db: DbSession, user: AdminUser):
    u = await _get_or_404(db, user_id)
    if user_id == user.id and not body.is_active:
        raise HTTPException(400, "Cannot deactivate your own account")
    u.is_active = body.is_active
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=_actor_name(user),
        action="user_status_changed",
        entity_type="user",
        entity_id=user_id,
        details={"is_active": body.is_active},
    )
    await db.commit()
    return _serialize(u)


@router.put("/{user_id}/unlock")
async def unlock_user(user_id: int, db: DbSession, user: AdminUser):
    # Self-unlock is allowed: a locked-out admin holding a live session is
    # exactly the case this route exists for.
    u = await _get_or_404(db, user_id)
    u.failed_attempts = 0
    u.locked_until = None
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=_actor_name(user),
        action="user_unlocked",
        entity_type="user",
        entity_id=user_id,
        details={"self": user_id == user.id},
    )
    await db.commit()
    return _serialize(u)


@router.put("/{user_id}/reset-password")
async def reset_password(user_id: int, body: PasswordReset, db: DbSession, user: AdminUser):
    u = await _get_or_404(db, user_id)
    u.password_hash = hash_password(body.password)
    u.must_change_password = True
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=_actor_name(user),
        action="password_reset",
        entity_type="user",
        entity_id=user_id,
        details={"target_username": _actor_name(u) if u.identity else None},
    )
    await db.commit()
    return _serialize(u)
