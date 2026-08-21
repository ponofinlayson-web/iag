"""Remediation trigger E2E: revoke via API -> actions created in-TX."""
from __future__ import annotations

import io
import json

PEOPLE = (
    "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
    "E-1,alice,alice@x.io,Alice,Andrews,Engineering,\n"
    "E-2,bob,bob@x.io,Bob,Brown,Engineering,E-1\n"
)
ACCESS = (
    "account,entitlement,privilege\n"
    "alice,Engineering Admin,high\n"
    "bob,Read Only,low\n"
)


def _setup(admin_client, name_suffix="") -> tuple[int, list[int]]:
    """Import, source, upload, link, campaign, start -> (campaign_id, review_ids)."""
    r = admin_client.post("/api/identities/import",
                          files={"file": ("p.csv", io.BytesIO(PEOPLE.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    r = admin_client.post("/api/sources", json={
        "name": f"Remed Src {name_suffix}", "source_type": "csv",
        "owner_employee_id": "E-ADMIN",
    })
    assert r.status_code == 200, r.text
    src_id = r.json()["id"]
    r = admin_client.post(f"/api/sources/{src_id}/upload",
                          files={"file": ("a.csv", io.BytesIO(ACCESS.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    r = admin_client.post(f"/api/sources/{src_id}/accounts/bulk-link",
                          json={"match_on": "username"})
    assert r.status_code == 200, r.text
    r = admin_client.post("/api/campaigns", json={
        "name": f"Remed Campaign {name_suffix}", "review_mode": "source_owner"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    r = admin_client.post(f"/api/campaigns/{cid}/stage")
    assert r.status_code == 200, r.text
    r = admin_client.post(f"/api/campaigns/{cid}/start")
    assert r.status_code == 200, r.text
    r = admin_client.get("/api/reviews/queue")
    return cid, [it["id"] for it in r.json()["items"]]


def _actions(admin_client, review_id: int) -> list[dict]:
    """Phase D ships the API; until then read via DB (same-TX assertion)."""
    from app.models.remediation import RemediationAction
    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{admin_client.app.state.test_db_path}")
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, rule_id, action_type, status, requires_approval, snapshot "
            "FROM remediation_actions WHERE review_id = :rid ORDER BY id"
        ), {"rid": review_id}).mappings().all()
    engine.dispose()
    return [dict(r) for r in rows]


def test_revoke_creates_actions_per_matched_rules(admin_client):
    cid, rids = _setup(admin_client, "1")
    # one rule: source-scoped, high privilege, "admin" regex — matches only alice's row
    _make_rule(admin_client, name="r1", privilege="high", pattern="^Engineering")
    r = admin_client.post(f"/api/reviews/{rids[0]}/submit",
                          json={"decision": "revoke", "comments": "not needed"})
    assert r.status_code == 200, r.text
    actions = _actions(admin_client, rids[0])
    assert len(actions) == 1
    assert actions[0]["rule_id"] is not None
    assert actions[0]["action_type"] == "notify_owner"
    # high privilege + require_approval_for_high_risk default True -> gated
    assert actions[0]["status"] == "pending_approval"
    assert actions[0]["requires_approval"] == 1
    snap = json.loads(actions[0]["snapshot"])
    assert snap["entitlement_name"] == "Engineering Admin"
    assert snap["privilege_level"] == "high"
    assert snap["identity_name"] == "Alice Andrews"


def test_multiple_rules_multiple_actions(admin_client):
    cid, rids = _setup(admin_client, "2")
    _make_rule(admin_client, name="ra", privilege="high")
    _make_rule(admin_client, name="rb", pattern="Admin")
    r = admin_client.post(f"/api/reviews/{rids[0]}/submit",
                          json={"decision": "revoke", "comments": "x"})
    assert r.status_code == 200, r.text
    actions = _actions(admin_client, rids[0])
    assert len(actions) == 2
    assert {a["action_type"] for a in actions} == {"notify_owner"}


def test_no_match_no_default_config_off_creates_nothing(admin_client):
    cid, rids = _setup(admin_client, "3")
    # rule that will not match (regex matches neither entitlement name)
    _make_rule(admin_client, name="r-nomatch", pattern="^zzz-nomatch")
    r = admin_client.post(f"/api/reviews/{rids[0]}/submit",
                          json={"decision": "revoke", "comments": "x"})
    assert r.status_code == 200, r.text
    # default_action=notify_owner -> one default action expected (config on)
    actions = _actions(admin_client, rids[0])
    assert len(actions) == 1
    assert actions[0]["rule_id"] is None


def test_disabled_config_creates_nothing(admin_client):
    cid, rids = _setup(admin_client, "4")
    _set_config(admin_client, enabled=False)
    _make_rule(admin_client, name="r-off", pattern=".")
    r = admin_client.post(f"/api/reviews/{rids[0]}/submit",
                          json={"decision": "revoke", "comments": "x"})
    assert r.status_code == 200, r.text
    assert _actions(admin_client, rids[0]) == []


def test_approve_never_triggers(admin_client):
    cid, rids = _setup(admin_client, "5")
    _make_rule(admin_client, name="r-ap", pattern=".")
    r = admin_client.post(f"/api/reviews/{rids[0]}/submit",
                          json={"decision": "approve"})
    assert r.status_code == 200, r.text
    assert _actions(admin_client, rids[0]) == []


def test_bulk_revoke_triggers_per_review(admin_client):
    cid, rids = _setup(admin_client, "6")
    _make_rule(admin_client, name="r-blk", pattern=".")
    r = admin_client.post("/api/reviews/bulk-submit", json={
        "review_ids": rids, "decision": "revoke", "comments": "bulk cleanup"})
    assert r.status_code == 200, r.text
    assert r.json()["submitted"] == 2
    for rid in rids:
        assert len(_actions(admin_client, rid)) == 1


def test_rule_counters_bumped(admin_client):
    cid, rids = _setup(admin_client, "7")
    _make_rule(admin_client, name="r-cnt", pattern=".")
    admin_client.post(f"/api/reviews/{rids[0]}/submit",
                      json={"decision": "revoke", "comments": "x"})
    stats = _rule_stats(admin_client, "r-cnt")
    assert stats["times_triggered"] == 1


def test_audit_entry_and_chain_valid(admin_client):
    cid, rids = _setup(admin_client, "8")
    _make_rule(admin_client, name="r-aud", pattern=".")
    admin_client.post(f"/api/reviews/{rids[0]}/submit",
                      json={"decision": "revoke", "comments": "x"})
    r = admin_client.get("/api/audit/verify")
    assert r.status_code == 200
    assert r.json()["valid"] is True
    r = admin_client.get("/api/audit?action=remediation_actions_created")
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 1


def _make_rule(admin_client, name, source_id=None, privilege=None, pattern=None,
               action="notify_owner", require_approval=False, webhook_url=None):
    """Phase D ships the rules API; until then insert via DB."""
    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{admin_client.app.state.test_db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO remediation_rules "
            "(name, action, is_active, require_approval, data_source_id, "
            " privilege_level, entitlement_pattern, webhook_url, "
            " times_triggered, times_executed, times_failed, created_at, updated_at) "
            "VALUES (:name, :action, 1, :ra, :src, :priv, :pat, :url, 0, 0, 0, "
            " datetime('now'), datetime('now'))"
        ), {"name": name, "action": action, "ra": 1 if require_approval else 0,
            "src": source_id, "priv": privilege, "pat": pattern, "url": webhook_url})
    engine.dispose()


def _set_config(admin_client, enabled=True, default_action="notify_owner",
                require_high=True):
    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{admin_client.app.state.test_db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO remediation_settings (id, config) VALUES (1, :cfg) "
            "ON CONFLICT(id) DO UPDATE SET config = :cfg"
        ), {"cfg": json.dumps({"enabled": enabled, "default_action": default_action,
                               "require_approval_for_high_risk": require_high})})
    engine.dispose()


def _rule_stats(admin_client, name):
    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{admin_client.app.state.test_db_path}")
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT times_triggered, times_executed, times_failed "
            "FROM remediation_rules WHERE name = :n"
        ), {"n": name}).mappings().one()
    engine.dispose()
    return dict(row)
