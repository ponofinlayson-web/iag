"""Reminder-email queue tests: enqueue, claim/send, no-double-send, retry,
dead-letter, cancel, read-only API + role checks. SQLite; send stubbed."""
import asyncio
import io
import json
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email_worker import run_pass
from app.core.settings import Settings

CSV = ("employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
       "E-1,alice,alice@x.io,Alice,Andrews,Engineering,\n"
       "E-2,bob,bob@x.io,Bob,Brown,Engineering,E-1\n")
SRC = "account,entitlement,privilege\nalice,Eng Admin,high\nbob,Read Only,low\n"

SENT: list[int] = []
FAILED: set[int] = set()


def _reset():
    SENT.clear()
    FAILED.clear()


async def stub_send(row):
    if row.id in FAILED:
        raise RuntimeError("smtp down")
    SENT.append(row.id)


def _start_campaign(admin_client) -> int:
    admin_client.post("/api/identities/import",
                      files={"file": ("p.csv", io.BytesIO(CSV.encode()), "text/csv")})
    r = admin_client.post("/api/sources", json={
        "name": "Dir", "source_type": "csv", "owner_employee_id": "E-ADMIN"})
    sid = r.json()["id"]
    admin_client.post(f"/api/sources/{sid}/upload",
                      files={"file": ("a.csv", io.BytesIO(SRC.encode()), "text/csv")})
    admin_client.post(f"/api/sources/{sid}/accounts/bulk-link", json={"match_on": "username"})
    r = admin_client.post("/api/campaigns", json={"name": "R", "review_mode": "source_owner"})
    cid = r.json()["id"]
    admin_client.post(f"/api/campaigns/{cid}/stage")
    r = admin_client.post(f"/api/campaigns/{cid}/start")
    assert r.status_code == 200, r.text
    return cid


@pytest.fixture()
def worker_session(client):
    """Returns an async context manager factory bound to a FRESH engine per
    call. run_pass is driven under asyncio.run(): each call gets its own loop,
    so pooled connections must never cross loops (aiosqlite would reject them).
    Same per-test DB file as the TestClient override."""
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


SETTINGS = Settings(reminder_delay_minutes=0, reminder_poll_seconds=1,
                    reminder_max_attempts=3, reminder_stuck_minutes=15,
                    reminder_batch_size=25, env="test")


async def _run(worker_session):
    async with worker_session() as maker:
        return await run_pass(maker, send=stub_send, settings=SETTINGS)


def _audit_entries(admin_client):
    r = admin_client.get("/api/audit")
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _make_due(admin_client):
    """Enqueue sets due_at = now + delay; tests need it due NOW."""
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    try:
        con.execute("UPDATE email_outbox SET due_at = '2000-01-01 00:00:00'")
        con.commit()
    finally:
        con.close()


def _outbox_rows(admin_client, cid=None):
    q = f"/api/reminders/outbox" + (f"?campaign_id={cid}" if cid else "")
    r = admin_client.get(q)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_enqueue_on_start(admin_client):
    _reset()
    cid = _start_campaign(admin_client)
    rows = _outbox_rows(admin_client, cid)
    assert len(rows) == 2  # one per review (alice, bob accounts)
    assert all(r["status"] == "pending" for r in rows)
    assert all(r["due_at"] is not None for r in rows)
    assert all(r["sent_at"] is None for r in rows)
    # recipient resolved at enqueue time from the reviewer identity
    assert all(r["recipient"] for r in rows)  # admin has email admin@test.local


def test_claim_and_send(worker_session, admin_client):
    _reset()
    cid = _start_campaign(admin_client)
    _make_due(admin_client)
    stats = asyncio.run(_run(worker_session))
    assert stats["claimed"] == 2 and stats["sent"] == 2
    rows = _outbox_rows(admin_client, cid)
    assert all(r["status"] == "sent" for r in rows)
    assert all(r["sent_at"] for r in rows)
    assert sorted(SENT) == sorted(r["id"] for r in rows)
    # audit entries written by the worker, chain still valid
    r = admin_client.get("/api/audit/verify")
    assert r.json()["valid"] is True
    actions = [e["action"] for e in _audit_entries(admin_client)]
    assert actions.count("email_sent") == 2


def test_no_double_send(worker_session, admin_client):
    _reset()
    cid = _start_campaign(admin_client)
    _make_due(admin_client)
    first = asyncio.run(_run(worker_session))
    assert first["claimed"] == 2 and first["sent"] == 2
    second = asyncio.run(_run(worker_session))  # rows now sent; claim finds nothing
    assert second["claimed"] == 0 and second["sent"] == 0
    assert len(SENT) == 2  # exactly one send per row, ever


def test_retry_then_dead_letter(worker_session, admin_client):
    _reset()
    cid = _start_campaign(admin_client)
    _make_due(admin_client)
    rows = _outbox_rows(admin_client, cid)
    victim = rows[0]["id"]
    FAILED.add(victim)
    for i in range(3):
        stats = asyncio.run(_run(worker_session))
        assert stats["claimed"] >= 1
    state = {r["id"]: r for r in _outbox_rows(admin_client, cid)}
    assert state[victim]["status"] == "failed"  # dead-lettered at max attempts
    assert state[victim]["attempts"] == 3
    assert state[victim]["last_error"]
    healthy = [r for r in state.values() if r["id"] != victim]
    assert all(r["status"] == "sent" for r in healthy)
    actions = [e["action"] for e in _audit_entries(admin_client)]
    assert actions.count("email_failed") == 3
    failed_entries = [e for e in _audit_entries(admin_client)
                      if e["action"] == "email_failed"]
    assert sum(1 for e in failed_entries
               if json.loads(e["details"]).get("dead_letter")) == 1
    assert admin_client.get("/api/audit/verify").json()["valid"] is True


def test_cancel_cancels(worker_session, admin_client):
    _reset()
    cid = _start_campaign(admin_client)
    assert admin_client.post(f"/api/campaigns/{cid}/cancel").status_code == 200
    rows = _outbox_rows(admin_client, cid)
    assert len(rows) == 2
    assert all(r["status"] == "cancelled" for r in rows)
    _make_due(admin_client)
    stats = asyncio.run(_run(worker_session))  # cancelled rows are never claimed
    assert stats["claimed"] == 0
    assert SENT == []


def test_role_checks(client):
    # no cookie -> 401 on both read endpoints
    assert client.get("/api/reminders/outbox").status_code == 401
    assert client.get("/api/reminders/campaigns/1").status_code == 401
    # reviewer role must be 403 (CertAdminUser only)
    from app.core.security import hash_password
    from app.db import Base, build_engine
    from app.models.identity import Identity
    from app.models.user import Role, User
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = build_engine(f"sqlite+aiosqlite:///{client.app.state.test_db_path}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def seed():
        async with maker() as s:
            ident = Identity(employee_id="E-REV", username="rev1", email="rev1@x.io",
                             first_name="R", last_name="V")
            s.add(ident)
            await s.flush()
            s.add(User(identity_id=ident.id, password_hash=hash_password("revpass123"),
                       role=Role.REVIEWER))
            await s.commit()

    asyncio.run(seed())
    r = client.post("/api/auth/login", json={"username": "rev1", "password": "revpass123"})
    assert r.status_code == 200, r.text
    assert client.get("/api/reminders/outbox").status_code == 403
    assert client.get("/api/reminders/campaigns/1").status_code == 403


def test_worker_boots_with_testclient(client):
    """Lifespan starts the worker task on client context entry; if lifespan
    raised, this fixture would have errored before the test body ran. Health
    staying green while the worker polls is the boot proof."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
