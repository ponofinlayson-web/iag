"""Auth router: login, me, logout, password change."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.core.audit_service import append_audit
from app.core.security import hash_password, new_session_token, verify_password
from app.models.identity import Identity, utcnow
from app.models.user import Role, User
from app.routers.deps import DbSession, SessionUser, _settings
router = APIRouter(prefix="/api/auth", tags=["auth"])
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)
def _session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "iag_session",
        token,
        max_age=_settings.session_expire_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=_settings.env not in ("development", "test"),
    )
@router.post("/login")
async def login(body: LoginRequest, response: Response, db: DbSession):
    result = await db.execute(
        select(User).join(Identity, User.identity_id == Identity.id).where(
            Identity.username == body.username
        )
    )
    user = result.scalars().first()
    if user is None or not verify_password(body.password, user.password_hash):
        if user is not None:
            user.failed_attempts += 1
            if user.failed_attempts >= _settings.max_login_attempts:
                user.locked_until = utcnow() + timedelta(
                    minutes=_settings.lockout_duration_minutes
                )
            await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if user.locked_until and user.locked_until > utcnow():
        raise HTTPException(status.HTTP_423_LOCKED, "Account locked")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    user.failed_attempts = 0
    user.locked_until = None
    token = new_session_token(
        _settings.secret_key,
        user.id,
        user.identity.username,
        user.role.value,
        _settings.session_expire_minutes,
    )
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=body.username,
        action="login",
        entity_type="user",
        entity_id=user.id,
        details={"role": user.role.value},
    )
    await db.commit()
    _session_cookie(response, token)
    return {"ok": True, "role": user.role.value}
@router.get("/me")
async def me(user: SessionUser):
    ident = user.identity
    return {
        "id": user.id,
        "username": ident.username,
        "email": ident.email,
        "role": user.role.value,
        "must_change_password": user.must_change_password,
    }
@router.post("/logout")
async def logout(response: Response, user: SessionUser):
    response.delete_cookie("iag_session")
    return {"ok": True}
@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user: SessionUser, db: DbSession):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password incorrect")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=user.identity.username or "",
        action="password_changed",
        entity_type="user",
        entity_id=user.id,
    )
    await db.commit()
    return {"ok": True}