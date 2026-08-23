"""One-shot E2E helper: create a dedicated system_admin user for browser passes.

Run inside an app container against the compose Postgres. Password is read
from the IAG_E2E_PW environment variable (never hardcoded, never logged).
"""
import asyncio
import os
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db import SessionLocal
from app.models.identity import Identity
from app.models.user import Role, User


async def main() -> int:
    pw = os.environ.get("IAG_E2E_PW")
    if not pw:
        print("IAG_E2E_PW not set", file=sys.stderr)
        return 2
    async with SessionLocal() as db:
        existing = (
            await db.execute(
                select(User).join(Identity, User.identity_id == Identity.id).where(Identity.username == "e2e_admin")
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.password_hash = hash_password(pw)
            existing.failed_attempts = 0
            existing.locked_until = None
            existing.role = Role.CERTIFICATION_ADMIN
            await db.commit()
            print(f"reset e2e_admin password + role=certification_admin (user id={existing.id})")
            return 0
        ident = Identity(
            employee_id="E-E2E",
            username="e2e_admin",
            email="e2e_admin@iag.local",
            first_name="E2E",
            last_name="Browser",
        )
        db.add(ident)
        await db.flush()
        user = User(
            identity_id=ident.id,
            password_hash=hash_password(pw),
            role=Role.SYSTEM_ADMIN,
        )
        db.add(user)
        await db.commit()
        print(f"created e2e_admin user id={user.id}")
        return 0


raise SystemExit(asyncio.run(main()))
