"""E2E smoke: in-process TestClient (sandbox blocks raw socket binds).

Boots a fresh sqlite dev DB (iag_dev_smoke.db), runs bootstrap, then
proves: SPA served at /, login, session, protected dashboard.
Run:  cd backend && uv run python smoke_testclient.py
Delete iag_dev_smoke.db first for a clean rerun (or bootstrap skips).
"""
import asyncio
import os
import sys

sys.path.insert(0, ".")
os.environ["IAG_ENV"] = "development"
os.environ["IAG_BOOTSTRAP_ADMIN_PASSWORD"] = "Admin123!secret"
os.environ["IAG_DATABASE_URL"] = "sqlite+aiosqlite:///./iag_dev_smoke.db"

from fastapi.testclient import TestClient

from app.db import Base, build_engine
from app.main import app

test_engine = build_engine("sqlite+aiosqlite:///./iag_dev_smoke.db")


async def init_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(init_db())
from app.bootstrap import main as bootstrap_main

print("BOOTSTRAP rc:", asyncio.run(bootstrap_main()))

with TestClient(app) as c:
    h = c.get("/api/health")
    print("HEALTH:", h.status_code, h.json()["status"])
    root = c.get("/")
    ok_root = root.status_code == 200 and 'id="root"' in root.text and "assets/index-" in root.text
    print("ROOT:", root.status_code, "spa-served:", ok_root)
    login = c.post("/api/auth/login", json={"username": "admin", "password": "Admin123!secret"})
    print("LOGIN:", login.status_code)
    me = c.get("/api/auth/me")
    print("ME:", me.status_code, me.json().get("username"), me.json().get("role"))
    dash = c.get("/api/dashboard")
    print("DASH:", dash.status_code, dash.json())
