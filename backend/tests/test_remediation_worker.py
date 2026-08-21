"""Remediation worker: claim -> deliver -> finalize (fork-A discipline)."""
from __future__ import annotations

import asyncio
import io
import json
import threading

import pytest

from app.core.remediation_worker import run_pass
from app.models.remediation import RemediationStatus


# Reuse the trigger-suite scaffolding (setup -> revoke -> actions exist).
from tests.test_remediation_trigger import _make_rule, _setup  # noqa: F401

from sqlalchemy import create_engine, text


def _db_engine(admin_client):
    return create_engine(f"sqlite:///{admin_client.app.state.test_db_path}")


def _revoke_low(admin_client, rule_name, **rule_kw):
    """Revoke bob's 'Read Only' (low) review under a catch-all rule so the
    created action is APPROVED (not high-risk gated) and worker-claimable."""
    _make_rule(admin_client, name=rule_name, pattern=".", **rule_kw)
    engine = _db_engine(admin_client)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT r.id FROM reviews r JOIN accounts a ON a.id = r.account_id "
            "WHERE a.privilege_level = 'low' LIMIT 1"
        )).mappings().one()
    engine.dispose()
    r = admin_client.post(f"/api/reviews/{row['id']}/submit",
                          json={"decision": "revoke", "comments": "worker test"})
    assert r.status_code == 200, r.text
    return row["id"]


def _pending_actions(admin_client):
    from sqlalchemy import text
    engine = _db_engine(admin_client)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, action_type, status, attempts, result FROM remediation_actions "
            "ORDER BY id"
        )).mappings().all()
    engine.dispose()
    return [dict(r) for r in rows]


def _action_row(admin_client, action_id):
    from sqlalchemy import text
    engine = _db_engine(admin_client)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id, action_type, status, attempts, result, executed_at "
            "FROM remediation_actions WHERE id = :i"
        ), {"i": action_id}).mappings().one()
    engine.dispose()
    return dict(row)


def test_completed_notify_owner_with_fake_delivery(admin_client, worker_session):
    cid, rids = _setup(admin_client, "w1")
    _revoke_low(admin_client, "w-ok")
    actions = _pending_actions(admin_client)
    assert len(actions) == 1
    # low privilege + require_approval_for_high_risk -> approved, ready to claim
    assert actions[0]["status"] == "approved"

    delivered = []

    async def fake_deliver(session, action, settings):
        delivered.append(action.id)
        return "email sent to owner@test.local"

    async def run():
        async with worker_session() as maker:
            return await run_pass(maker, deliver_overrides={"notify_owner": fake_deliver})

    stats = asyncio.run(run())
    assert stats == {"claimed": 1, "completed": 1, "requeued": 0, "failed": 0}
    assert delivered == [actions[0]["id"]]
    row = _action_row(admin_client, actions[0]["id"])
    assert row["status"] == "completed"
    assert row["result"] == "email sent to owner@test.local"
    assert row["executed_at"] is not None


def test_failure_requeues_then_dead_letters(admin_client, worker_session):
    cid, rids = _setup(admin_client, "w2")
    _revoke_low(admin_client, "w-fail")

    calls = []

    async def failing(session, action, settings):
        calls.append(action.id)
        raise RuntimeError("SMTP down")

    async def run():
        async with worker_session() as maker:
            return await run_pass(maker, deliver_overrides={"notify_owner": failing})

    s1 = asyncio.run(run())
    assert s1 == {"claimed": 1, "requeued": 1, "completed": 0, "failed": 0}
    row = _action_row(admin_client, calls[0])
    assert row["status"] == "approved"  # retryable
    assert row["attempts"] == 1
    assert "SMTP down" in row["result"]

    s2 = asyncio.run(run())
    assert s2["requeued"] == 1
    s3 = asyncio.run(run())
    assert s3["failed"] == 1  # attempts==max (3) -> terminal
    row = _action_row(admin_client, calls[0])
    assert row["status"] == "failed"
    assert row["attempts"] == 3


def test_pending_approval_never_claimed(admin_client, worker_session):
    cid, rids = _setup(admin_client, "w3")
    _make_rule(admin_client, name="w-gate", pattern=".", privilege="high")
    admin_client.post(f"/api/reviews/{rids[0]}/submit",
                      json={"decision": "revoke", "comments": "x"})
    actions = _pending_actions(admin_client)
    assert actions[0]["status"] == "pending_approval"

    async def run():
        async with worker_session() as maker:
            return await run_pass(maker)

    stats = asyncio.run(run())
    assert stats["claimed"] == 0


def test_cancelled_mid_flight_never_resurrected(admin_client, worker_session):
    cid, rids = _setup(admin_client, "w4")
    _revoke_low(admin_client, "w-cancel")
    action_id = _pending_actions(admin_client)[0]["id"]

    from sqlalchemy import text

    async def run(deliver):
        async with worker_session() as maker:
            return await run_pass(maker, deliver_overrides={"notify_owner": deliver})

    # Simulate cancel during flight: flip status to cancelled BEFORE finalize.
    async def cancel_mid_flight(session, action, settings):
        engine = _db_engine(admin_client)
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE remediation_actions SET status='cancelled' WHERE id=:i"
            ), {"i": action.id})
        engine.dispose()
        return "sent before cancel"

    asyncio.run(run(cancel_mid_flight))
    row = _action_row(admin_client, action_id)
    assert row["status"] == "cancelled"  # finalize skipped; not resurrected


def test_webhook_success_via_local_http(admin_client, worker_session):
    cid, rids = _setup(admin_client, "w5")
    _revoke_low(admin_client, "w-hook", action="webhook",
                webhook_url="http://127.0.0.1:8641/hook")
    action_id = _pending_actions(admin_client)[0]["id"]

    received = []

    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(n)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 8641), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        async def run():
            async with worker_session() as maker:
                return await run_pass(maker)
        stats = asyncio.run(run())
    finally:
        server.shutdown()
        t.join(timeout=2)
    assert stats["completed"] == 1
    row = _action_row(admin_client, action_id)
    assert row["status"] == "completed"
    assert row["result"].startswith("webhook 200")
    payload = received[0]
    assert payload["action_type"] == "webhook"
    assert payload["action_id"] == action_id
    assert "entitlement_name" in payload


def test_webhook_missing_url_fails_clearly(admin_client, worker_session):
    cid, rids = _setup(admin_client, "w6")
    # webhook rule whose URL is somehow absent (rule deleted post-trigger)
    _revoke_low(admin_client, "w-nourl", action="webhook", webhook_url=None)
    action_id = _pending_actions(admin_client)[0]["id"]

    async def run():
        async with worker_session() as maker:
            return await run_pass(maker)

    stats = asyncio.run(run())
    assert stats["requeued"] + stats["failed"] >= 1
    row = _action_row(admin_client, action_id)
    assert "webhook_url" in (row["result"] or "")


def test_notify_owner_without_smtp_config_fails(admin_client, worker_session):
    cid, rids = _setup(admin_client, "w7")
    _revoke_low(admin_client, "w-nosmtp")
    action_id = _pending_actions(admin_client)[0]["id"]

    async def run():
        async with worker_session() as maker:
            return await run_pass(maker)

    # Tests run with IAG_SMTP_HOST unset -> the D2 hard-failure path.
    stats = asyncio.run(run())
    row = _action_row(admin_client, action_id)
    assert row["status"] in ("approved", "failed")  # requeued or terminal
    assert "IAG_SMTP_HOST" in (row["result"] or "")
