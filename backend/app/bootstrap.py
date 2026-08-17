"""One-shot admin bootstrap: run inside the migrate container after Alembic.
Creates the first admin identity+user if none exists, using env-provided
credentials. Exits non-zero on failure. Never runs again once users exist.
"""
from __future__ import annotations
import asyncio
import sys
from sqlalchemy import func, select
from app.core.security import hash_password
from app.core.settings import Settings
from app.db import SessionLocal, build_engine, engine
from app.models.identity import Identity
from app.models.user import Role, User
async def main() -> int:
    s = Settings()
    if not s.bootstrap_admin_password:
        print("[bootstrap] no IAG_BOOTSTRAP_ADMIN_PASSWORD set; skipping", flush=True)
        return 0
    async with SessionLocal() as db:
        user_count = (
            await db.execute(select(func.count()).select_from(User))
        ).scalar_one()
        if user_count > 0:
            print(f"[bootstrap] {user_count} users exist; skipping", flush=True)
            return 0
        username = s.bootstrap_admin_username
        ident = Identity(
            employee_id="E-ADMIN",
            username=username,
            email=f"{username}@iag.local",
            first_name="System",
            last_name="Admin",
        )
        db.add(ident)
        await db.flush()
        user = User(
            identity_id=ident.id,
            password_hash=hash_password(s.bootstrap_admin_password),
            role=Role.SYSTEM_ADMIN,
        )
        db.add(user)
        await db.commit()
        print(f"[bootstrap] created admin user {username}", flush=True)
    return 0
if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
