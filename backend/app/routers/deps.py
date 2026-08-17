"""Shared FastAPI dependencies: settings, current user, role guards."""
from __future__ import annotations
from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import verify_session_token
from app.core.settings import Settings
from app.db import get_db
from app.models.user import Role, User
_settings = Settings()
def get_settings() -> Settings:
    return _settings
async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    token = request.cookies.get("iag_session")
    payload = verify_session_token(_settings.secret_key, token)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user
def require_roles(*roles: Role):
    async def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user
    return checker
AdminUser = Annotated[User, Depends(require_roles(Role.SYSTEM_ADMIN))]
CertAdminUser = Annotated[
    User, Depends(require_roles(Role.SYSTEM_ADMIN, Role.CERTIFICATION_ADMIN))
]
AnyUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
