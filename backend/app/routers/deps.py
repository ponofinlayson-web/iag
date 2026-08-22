"""Shared FastAPI dependencies: settings, current user, role guards, API-key principal."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core import apikeys as keyfns
from app.core.security import verify_session_token
from app.core.settings import Settings
from app.db import get_db
from app.models.apikey import ApiKey
from app.models.identity import utcnow
from app.models.user import Role, User
_settings = Settings()

@dataclass(frozen=True)
class ApiKeyPrincipal:
    """A resolved API key acting as request principal (spec D2/D4).

    Not a User row: no password, no identity, no session. Guards and
    endpoints that only read .role / .id accept it unchanged; anything
    personal must depend on SessionUser instead.
    """
    key_id: int
    name: str
    role: Role
    is_api_key: bool = True

    @property
    def id(self) -> int:
        return self.key_id

Principal = User | ApiKeyPrincipal

def get_settings() -> Settings:
    return _settings

async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return await _resolve_api_key(request, db, auth[7:].strip())
    token = request.cookies.get("iag_session")
    payload = verify_session_token(_settings.secret_key, token)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user

async def _resolve_api_key(
    request: Request, db: AsyncSession, presented: str
) -> ApiKeyPrincipal:
    # Choke 1 (D1): keys are read-only. One check covers every write
    # endpoint that exists or will exist.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys are read-only")
    # Choke 2: a leaked key must never be able to mint friends.
    if request.url.path.startswith("/api/api-keys"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys cannot manage API keys")
    parsed = keyfns.parse_key(presented)
    if parsed is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    key_id, full_key = parsed
    row = await db.get(ApiKey, key_id)
    if row is None or not keyfns.verify_key(full_key, row.key_hash):
        # Same message as malformed - no oracle about which part failed.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if not row.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key revoked")
    if keyfns.is_expired(row.expires_at):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key expired")
    await _touch_last_used(db, row)
    return ApiKeyPrincipal(key_id=row.id, name=row.name, role=row.role)

async def _touch_last_used(db: AsyncSession, row: ApiKey) -> None:
    """Best-effort usage evidence, one write per 60s (D6); never fails
    the request it is measuring."""
    now = utcnow()
    if row.last_used_at is not None and (
        now - row.last_used_at
    ).total_seconds() < keyfns.LAST_USED_THROTTLE_SECONDS:
        return
    try:
        row.last_used_at = now
        await db.commit()
    except Exception:
        await db.rollback()

def require_roles(*roles: Role):
    async def checker(user: Annotated[Principal, Depends(get_current_user)]) -> Principal:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user
    return checker

AdminUser = Annotated[Principal, Depends(require_roles(Role.SYSTEM_ADMIN))]
CertAdminUser = Annotated[
    Principal, Depends(require_roles(Role.SYSTEM_ADMIN, Role.CERTIFICATION_ADMIN))
]
ReportViewer = Annotated[
    Principal,
    Depends(require_roles(Role.REPORT_VIEWER, Role.AUDITOR, Role.CERTIFICATION_ADMIN, Role.SYSTEM_ADMIN)),
]
AnyUser = Annotated[Principal, Depends(get_current_user)]

async def get_session_user(
    principal: Annotated[Principal, Depends(get_current_user)],
) -> User:
    """D4: personal endpoints are cookie-only; a key principal gets 403
    instead of quietly empty or garbage personal data."""
    if isinstance(principal, ApiKeyPrincipal):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "API keys cannot access personal endpoints"
        )
    return principal

SessionUser = Annotated[User, Depends(get_session_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
