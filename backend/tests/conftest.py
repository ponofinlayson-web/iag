"""Test fixtures: per-test SQLite DB with auto-seeded admin, session override."""
from __future__ import annotations
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.core.security import hash_password
from app.db import Base, build_engine, get_db
from app.main import app
from app.models.identity import Identity
from app.models.user import Role, User
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "adminpass123"
@pytest.fixture()
def client(tmp_path):
    db_file = tmp_path / f"test_{uuid.uuid4().hex}.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{db_file}")
    TestSessionLocal = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    initialized = False
    async def override():
        nonlocal initialized
        if not initialized:
            async with test_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with TestSessionLocal() as s:
                ident = Identity(
                    employee_id="E-ADMIN",
                    username=ADMIN_USERNAME,
                    email="admin@test.local",
                    first_name="Ada",
                    last_name="Minnie",
                )
                s.add(ident)
                await s.flush()
                s.add(User(
                    identity_id=ident.id,
                    password_hash=hash_password(ADMIN_PASSWORD),
                    role=Role.SYSTEM_ADMIN,
                ))
                await s.commit()
            initialized = True
        async with TestSessionLocal() as s:
            yield s
    app.dependency_overrides[get_db] = override
    app.state.test_db_path = str(db_file)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
@pytest.fixture()
def admin_client(client):
    r = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD,
    })
    assert r.status_code == 200, r.text
    return client
@pytest.fixture()
def worker_session(client):
    """Fresh async engine factory per call (run_pass driven under
    asyncio.run; pooled connections must never cross loops). Same
    per-test DB as TestClient."""
    from contextlib import asynccontextmanager
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    @asynccontextmanager
    async def _factory():
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{client.app.state.test_db_path}")
        maker = async_sessionmaker(engine, class_=AsyncSession,
                                   expire_on_commit=False, autoflush=False)
        try:
            yield maker
        finally:
            await engine.dispose()

    return _factory
