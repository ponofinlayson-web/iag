"""Connector sync worker tests: enqueue (due/manual/duplicate), claim
(exclusive + stuck reclaim + cancel skip), apply semantics (upsert, link,
missing-count), finalize (success/failure + audit + schedule advance).
SQLite; fetch stubbed per the email-worker test pattern."""
import asyncio
import io
import json
import sqlite3
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.core.sync_worker import (
    AccountRecord,
    SyncSnapshot,
    enqueue_manual,
    run_pass,
)
from app.models.identity import utcnow
from app.models.source import DataSource

CSV = ("employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
       "E-1,alice,alice@x.io,Alice,Andrews,Engineering,\n"
       "E-2,bob,bob@x.io,Bob,Brown,Engineering,E-1\n")


def _snapshot(*specs) -> SyncSnapshot:
    """specs: 'value:priv:ent1|ent2' convenience."""
    accounts = []
    for spec in specs:
        parts = spec.split(":")
        accounts.append(AccountRecord(
            value=parts[0],
            privilege=parts[1] or None,
            entitlements=tuple(p for p in parts[2].split("|") if p) if len(parts) > 2 else (),
        ))
    return SyncSnapshot(accounts=accounts)


@pytest.fixture()
def worker_session(client):
    """Fresh engine per call (run_pass driven under asyncio.run; pooled
    connections must never cross loops). Same per-test DB as TestClient."""
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


SETTINGS = Settings(connector_poll_seconds=1, connector_stuck_minutes=15,
                    connector_max_rows=50000, env="test")


def _make_source(admin_client, stype="sql", interval=60) -> int:
    admin_client.post("/api/identities/import",
                      files={"file": ("p.csv", io.BytesIO(CSV.encode()), "text/csv")})
    r = admin_client.post("/api/sources", json={"name": "SRC", "source_type": stype})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    return sid


async def _configure(worker_session, sid, interval=60, due_in_past=True):
    async with worker_session() as maker:
        async with maker() as s:
            src = await s.get(DataSource, sid)
            src.connector_config = json.dumps({"query": "SELECT 1"})
            src.connector_secret = "pw"
            src.sync_interval_minutes = interval
            src.next_sync_at = utcnow() - timedelta(minutes=5) if due_in_past else utcnow() + timedelta(hours=1)
            await s.commit()


async def _runs(worker_session):
    from app.models.sync import SyncRun
    async with worker_session() as maker:
        async with maker() as s:
            rows = (await s.execute(
                select(SyncRun).order_by(SyncRun.id)
            )).scalars().all()
            return [(r.id, r.status, r.triggered_by, r.stats, r.error) for r in rows]


def test_enqueue_due_then_sync(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))

    async def fetch_ok(config, secret):
        assert secret == "pw"
        return _snapshot("alice:high:Eng Admin", "bob:low:Read Only")

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch_ok, settings=SETTINGS)

    stats = asyncio.run(go())
    assert stats["enqueued"] == 1 and stats["claimed"] == 1 and stats["completed"] == 1
    rows = asyncio.run(_runs(worker_session))
    assert len(rows) == 1 and rows[0][1] == "done" and rows[0][2] == "schedule"
    det = json.loads(rows[0][3])
    assert det["accounts_created"] == 2 and det["entitlements_created"] == 2
    # identities linked by username (bulk-link semantics, exact match)
    assert det["identities_linked"] == 2
    # schedule advanced (checked via direct DB read)
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    try:
        row = con.execute(
            "SELECT last_sync_at, next_sync_at FROM data_sources WHERE id=?", (sid,)
        ).fetchone()
        assert row[0] is not None and row[1] is not None
    finally:
        con.close()


def test_second_pass_no_duplicates(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))

    async def fetch_ok(config, secret):
        return _snapshot("alice:high:Eng Admin", "bob:low:Read Only")

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch_ok, settings=SETTINGS)

    asyncio.run(go())
    stats = asyncio.run(go())
    # first pass advanced next_sync_at to +60m -> nothing due -> nothing enqueued
    assert stats["enqueued"] == 0 and stats["claimed"] == 0
    rows = asyncio.run(_runs(worker_session))
    assert len(rows) == 1
    # accounts NOT duplicated by re-apply (upsert contract)
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    try:
        n = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
        assert n == 2
    finally:
        con.close()


def test_manual_enqueue_and_duplicate_409_path(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))

    async def go():
        async with worker_session() as maker:
            async with maker() as s:
                r1 = await enqueue_manual(s, sid)
                r1_id = r1.id  # capture BEFORE the next call: rollback expires instances
                r2 = await enqueue_manual(s, sid)  # in-flight -> None (409 at API)
                return r1_id, r2

    r1_id, r2 = asyncio.run(go())
    assert r1_id is not None and r2 is None


def test_not_due_not_enqueued(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid, due_in_past=False))

    async def fetch_stub(config, secret):
        return _snapshot()

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch_stub, settings=SETTINGS)

    stats = asyncio.run(go())
    assert stats["enqueued"] == 0 and stats["claimed"] == 0


def test_fetch_failure_fails_run_with_audit(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))

    async def fetch_boom(config, secret):
        raise RuntimeError("wire down")

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch_boom, settings=SETTINGS)

    stats = asyncio.run(go())
    assert stats["failed"] == 1, stats
    rows = asyncio.run(_runs(worker_session))
    assert rows[0][1] == "failed" and "wire down" in rows[0][4]
    r = admin_client.get("/api/audit")
    actions = [i["action"] for i in r.json()["items"]]
    assert "connector_sync_failed" in actions
    # chain still verifies
    assert admin_client.get("/api/audit/verify").json()["valid"] is True


def test_missing_accounts_counted_not_deleted(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))

    async def fetch_full(config, secret):
        return _snapshot("alice:high:Eng Admin", "bob:low:Read Only", "carol::")

    async def fetch_part(config, secret):
        return _snapshot("alice:high:Eng Admin")

    async def go(fetch):
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch, settings=SETTINGS)

    asyncio.run(go(fetch_full))
    # force next_sync due again
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    con.execute("UPDATE data_sources SET next_sync_at = '2000-01-01 00:00:00'")
    con.commit(); con.close()
    asyncio.run(go(fetch_part))
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    try:
        n = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
        assert n == 3  # bob + carol still there
    finally:
        con.close()
    rows = asyncio.run(_runs(worker_session))
    det = json.loads(rows[-1][3])
    assert det["missing_from_snapshot"] == 2


def test_stuck_syncing_reclaimed(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))

    async def fetch_stub(config, secret):
        return _snapshot()

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch_stub, settings=SETTINGS)

    asyncio.run(go())
    # simulate a crashed replica: run back to syncing, started_at ancient
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    con.execute("UPDATE sync_runs SET status='syncing', started_at='2000-01-01 00:00:00'")
    con.execute("UPDATE data_sources SET next_sync_at='2000-01-01 00:00:00'")
    con.commit(); con.close()
    stats = asyncio.run(go())
    assert stats["claimed"] == 1  # stuck reclaim picked it up
    rows = asyncio.run(_runs(worker_session))
    assert len(rows) == 1 and rows[0][1] == "done"


def test_cancelled_run_never_resurrected(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))

    async def fetch_stub(config, secret):
        return _snapshot()

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch_stub, settings=SETTINGS)

    # Scenario: replica A claims a run (pending->syncing), then an admin
    # cancels it before finalize. The finalize must NOT resurrect it: the
    # fresh-status check sends it to skipped_cancelled instead of done.
    async def seed_then_claim():
        async with worker_session() as maker:
            async with maker() as s:
                await enqueue_manual(s, sid)
                from sqlalchemy import select
                from app.models.sync import SyncRun, SyncStatus
                run = (await s.execute(
                    select(SyncRun)
                )).scalars().first()
                run.status = SyncStatus.SYNCING  # claimed by replica A
                await s.commit()
                return run.id

    async def cancel_mid_flight(rid):
        from app.models.sync import SyncRun, SyncStatus
        async with worker_session() as maker:
            async with maker() as s:
                run = await s.get(SyncRun, rid)
                run.status = SyncStatus.CANCELLED
                await s.commit()

    rid = asyncio.run(seed_then_claim())
    asyncio.run(cancel_mid_flight(rid))
    stats = asyncio.run(go())
    # A new scheduled run MAY be enqueued+completed (source still due) —
    # that is correct. The CONTRACT is about the cancelled run itself:
    assert stats["skipped_cancelled"] + stats["completed"] >= 1, stats

    async def check():
        async with worker_session() as maker:
            async with maker() as s:
                from sqlalchemy import select
                from app.models.sync import SyncRun
                rows = (await s.execute(select(SyncRun).order_by(SyncRun.id))).scalars().all()
                cancelled = [r for r in rows if r.id == rid][0]
                return cancelled.status, cancelled.finished_at, cancelled.stats

    status, finished, stat_blob = asyncio.run(check())
    assert status == "cancelled", status  # never resurrected
    assert finished is None and stat_blob is None  # never finalized


def test_max_rows_exceeded_fails(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))
    # Settings ignores field-name kwargs (alias-only mode), so build via env
    import os as _os
    _os.environ["IAG_CONNECTOR_MAX_ROWS"] = "1"
    tight = Settings(env="test")
    assert tight.connector_max_rows == 1
    del _os.environ["IAG_CONNECTOR_MAX_ROWS"]

    async def fetch_big(config, secret):
        return _snapshot("alice::", "bob::")

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch_big, settings=tight)

    stats = asyncio.run(go())
    assert stats["failed"] == 1, stats
    rows = asyncio.run(_runs(worker_session))
    assert "MAX_ROWS" in rows[0][4]


def test_chain_valid_after_syncs(admin_client, worker_session):
    sid = _make_source(admin_client)
    asyncio.run(_configure(worker_session, sid))

    async def fetch_ok(config, secret):
        return _snapshot("alice:high:Eng Admin", "bob:low:Read Only")

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, fetch=fetch_ok, settings=SETTINGS)

    asyncio.run(go())
    v = admin_client.get("/api/audit/verify").json()
    assert v["valid"] is True and v["entries"] >= 1
