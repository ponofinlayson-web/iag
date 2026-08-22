"""Feature 6 Phase D: enforcement write-back arms (spec Part 2).

Real code paths, built-in mocks only — ldap3 MOCK strategy for the
directory (no server), httpx.MockTransport for Graph, real SQLite files
for sql sources. Every test drives the REAL remediation worker run_pass
with the DEFAULT deliverer registry (no overrides): trigger -> approve
(if gated) -> claim -> write-back -> finalize, end to end.
"""
from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.remediation_worker import run_pass  # noqa: E402
from app.core.settings import Settings  # noqa: E402
from app.models.source import DataSource  # noqa: E402

from tests.test_remediation_trigger import _make_rule  # noqa: F401,E402

# The trigger suite's _setup builds a csv-shaped world; enforcement needs
# connector sources, so this suite has its own thinner setup: identities +
# an ldap/entra/sql source + accounts + a campaign, via API where possible.


PEOPLE = (
    "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
    "E-1,alice,alice@x.io,Alice,Andrews,Engineering,\n"
    "E-2,bob,bob@x.io,Bob,Brown,Engineering,E-1\n"
)
ACCESS = (
    "account,entitlement,privilege\n"
    "alice,Eng-Admins,high\n"
    "bob,Read-Only,low\n"
)


def _db_engine(admin_client):
    from sqlalchemy import create_engine

    return create_engine(f"sqlite:///{admin_client.app.state.test_db_path}")


def _row(admin_client, sql, params=None):
    from sqlalchemy import text

    engine = _db_engine(admin_client)
    with engine.connect() as conn:
        row = conn.execute(text(sql), params or {}).mappings().one()
    engine.dispose()
    return dict(row)


def _rows(admin_client, sql, params=None):
    from sqlalchemy import text

    engine = _db_engine(admin_client)
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().all()
    engine.dispose()
    return [dict(r) for r in rows]


def _action(admin_client, action_id):
    return _row(
        admin_client,
        "SELECT id, action_type, status, attempts, result, executed_at "
        "FROM remediation_actions WHERE id = :i",
        {"i": action_id},
    )


def _setup_world(admin_client, suffix: str, source_type: str,
                 connector_config: dict) -> int:
    """Identities + connector source + csv-shaped accounts via upload is NOT
    possible for connector sources (upload is csv-only), so accounts are
    seeded directly through the DB — the same truth a sync would build."""
    r = admin_client.post("/api/identities/import",
                          files={"file": ("p.csv", io.BytesIO(PEOPLE.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    async def seed():
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{admin_client.app.state.test_db_path}")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            src = DataSource(
                name=f"Enforce Src {suffix}",
                source_type=source_type,
                connector_config=json.dumps(connector_config),
                connector_secret="",
            )
            s.add(src)
            await s.flush()
            from app.models.entitlement import Entitlement
            from app.models.identity import Identity
            from app.models.source import Account
            ents = {}
            for i, name in enumerate(("Eng-Admins", "Read-Only"), start=1):
                e = Entitlement(
                    data_source_id=src.id, name=name,
                    catalog_id=f"ENT-{suffix}-{i}",
                )
                s.add(e)
                await s.flush()
                ents[name] = e.id
            idents = {
                i.username: i.id
                for i in (await s.execute(select(Identity))).scalars()
                if i.username
            }
            s.add(Account(data_source_id=src.id, account_value="alice",
                          account_type="username", privilege_level="high",
                          entitlement_id=ents["Eng-Admins"],
                          identity_id=idents.get("alice")))
            s.add(Account(data_source_id=src.id, account_value="bob",
                          account_type="username", privilege_level="low",
                          entitlement_id=ents["Read-Only"],
                          identity_id=idents.get("bob")))
            await s.commit()
            return src.id

    src_id = asyncio.run(seed())
    # campaign over the seeded accounts: manager mode, no manager on the
    # identities -> reviewer falls back to the creator (admin)
    r = admin_client.post("/api/campaigns", json={
        "name": f"Enforce Campaign {suffix}", "review_mode": "manager",
        "scope": {"data_source_ids": [src_id]},
    })
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    r = admin_client.post(f"/api/campaigns/{cid}/stage")
    assert r.status_code == 200, r.text
    r = admin_client.post(f"/api/campaigns/{cid}/start")
    assert r.status_code == 200, r.text
    return src_id


def _make_enforce_rule(admin_client, name: str, target: str | None = None,
                       require_approval: bool | None = False,
                       data_source_id: int | None = None):
    """Create an enforce rule through the REAL rules API (phase-C surface);
    exercising it here doubles as an E2E check of rule->trigger->snapshot.
    Default require_approval=False is the admin's documented D6 opt-out —
    without it every action gates behind PUT approve (the gated test
    exercises that path on purpose). Any prior enforce rules are
    deactivated first: feature-3 fires ALL matched rules, so stacked
    catch-alls would fan one revoke out to N actions."""
    body = {"name": name, "action": "enforce",
            "entitlement_pattern": ".",
            "require_approval": require_approval}
    if target is not None:
        body["target"] = target
    if data_source_id is not None:
        body["data_source_id"] = data_source_id
    rules = admin_client.get("/api/remediation/rules").json()["items"]
    for rule in rules:
        if rule["action"] == "enforce" and rule["is_active"] and rule["name"] != name:
            r = admin_client.put(f"/api/remediation/rules/{rule['id']}", json={
                **{k: rule[k] for k in (
                    "name", "description", "data_source_id", "privilege_level",
                    "entitlement_pattern", "action", "target", "webhook_url",
                    "require_approval")},
                "is_active": False,
            })
            assert r.status_code == 200, r.text
    r = admin_client.post("/api/remediation/rules", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _revoke_bob(admin_client, rule_name: str, target: str | None = None,
                src_id: int | None = None):
    """Revoke bob's low-privilege review under a catch-all enforce rule ->
    APPROVED action (low privilege skips the high-risk gate). Scoped to one
    world's source (several tests build a second world for a second run —
    a review can only be decided once). Returns (review_id, action_id)."""
    _make_enforce_rule(admin_client, rule_name, target=target)
    if src_id is None:
        review = _row(
            admin_client,
            "SELECT r.id FROM reviews r JOIN accounts a ON a.id = r.account_id "
            "WHERE a.privilege_level = 'low' AND r.decision IS NULL "
            "ORDER BY r.id LIMIT 1",
        )
    else:
        review = _row(
            admin_client,
            "SELECT r.id FROM reviews r JOIN accounts a ON a.id = r.account_id "
            "WHERE a.privilege_level = 'low' AND a.data_source_id = :s "
            "AND r.decision IS NULL ORDER BY r.id LIMIT 1",
            {"s": src_id},
        )
    r = admin_client.post(f"/api/reviews/{review['id']}/submit",
                          json={"decision": "revoke", "comments": "enforce test"})
    assert r.status_code == 200, r.text
    action = _row(
        admin_client,
        "SELECT id FROM remediation_actions WHERE review_id = :r ORDER BY id",
        {"r": review["id"]},
    )
    return review["id"], action["id"]


def _run_worker(worker_session):
    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, settings=Settings())

    return asyncio.run(go())


def _approve(admin_client, action_id):
    r = admin_client.put(f"/api/remediation/actions/{action_id}",
                         json={"op": "approve"})
    assert r.status_code == 200, r.text


def _mirror_state(admin_client, src_id):
    return _rows(
        admin_client,
        "SELECT account_value, privilege_level, entitlement_id FROM accounts "
        "WHERE data_source_id = :s ORDER BY account_value",
        {"s": src_id},
    ), _rows(
        admin_client,
        "SELECT name FROM entitlements WHERE data_source_id = :s ORDER BY name",
        {"s": src_id},
    )


# ---------------------------------------------------------------- LDAP


def _mock_ldap_writeable():
    """MOCK-sync server + connection seeded with a writable person/group
    shape (group as cn= under ou=groups, mirroring AD; memberOf on users)."""
    from ldap3 import MOCK_SYNC
    from ldap3 import Connection as LdapConnection
    from ldap3 import Server

    server = Server("mock.local", get_info=MOCK_SYNC)
    conn = LdapConnection(
        server,
        user="cn=admin,dc=example,dc=com",
        password="pw",
        client_strategy=MOCK_SYNC,
    )
    conn.bind()
    for dn, attrs in [
        (
            "cn=alice,ou=people,dc=example,dc=com",
            {
                "objectClass": ["person"],
                "sAMAccountName": ["alice"],
                "memberOf": ["CN=Eng-Admins,OU=groups,DC=example,DC=com"],
            },
        ),
        (
            "cn=bob,ou=people,dc=example,dc=com",
            {
                "objectClass": ["person"],
                "sAMAccountName": ["bob"],
                "memberOf": ["CN=Read-Only,OU=groups,DC=example,DC=com"],
            },
        ),
        (
            "CN=Eng-Admins,OU=groups,DC=example,DC=com",
            {"objectClass": ["group"], "member": ["cn=alice,ou=people,dc=example,dc=com"]},
        ),
        (
            "CN=Read-Only,OU=groups,DC=example,DC=com",
            {"objectClass": ["group"], "member": ["cn=bob,ou=people,dc=example,dc=com"]},
        ),
    ]:
        assert conn.add(dn, ["top"], attrs), f"mock seed failed for {dn}"
    return conn


LDAP_CFG = {
    "url": "ldap://mock.local:389",
    "base_dn": "dc=example,dc=com",
    "bind_dn": "cn=admin,dc=example,dc=com",
    "account_attr": "sAMAccountName",
    "entitlements_attr": "memberOf",
}


def _patch_ldap(monkeypatch, conn):
    monkeypatch.setattr(
        "app.core.enforcement._ldap_connect_write", lambda *a, **k: conn
    )


def _ensure_bound(conn):
    """The enforcement arm unbinds in its finally block (correct for real
    servers); MOCK connections re-bind without losing their entries."""
    if conn.closed:
        conn.bind()


def _group_members(conn, group_dn):
    from ldap3 import MOCK_SYNC  # noqa: F401

    _ensure_bound(conn)
    conn.search(group_dn, "(objectClass=*)", attributes=["member"])
    entries = conn.entries
    if not entries:
        return []
    vals = entries[0].entry_attributes_as_dict.get("member") or []
    return [str(v) for v in vals]


GROUP_DN = "CN=Eng-Admins,OU=groups,DC=example,DC=com"


def test_ldap_remove_entitlement_e2e(admin_client, worker_session, monkeypatch):
    conn = _mock_ldap_writeable()
    _patch_ldap(monkeypatch, conn)
    src_id = _setup_world(admin_client, "ldap1", "ldap", LDAP_CFG)
    before_accounts, before_ents = _mirror_state(admin_client, src_id)
    review_id, action_id = _revoke_bob(admin_client, "ldap-rm", target="remove_entitlement")

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1 and stats["claimed"] == 1, stats
    row = _action(admin_client, action_id)
    assert row["status"] == "completed"
    assert "target=remove_entitlement" in row["result"]
    assert "ldap remove_entitlement: removed bob from Read-Only" in row["result"]
    # the write landed: bob's DN gone from the group entry
    assert "cn=bob,ou=people,dc=example,dc=com" not in _group_members(conn, GROUP_DN)
    # ...and alice's untouched membership survives
    assert "cn=alice,ou=people,dc=example,dc=com" in _group_members(conn, GROUP_DN)
    # mirror untouched (spec: enforcement never deletes mirror rows)
    after_accounts, after_ents = _mirror_state(admin_client, src_id)
    assert after_accounts == before_accounts and after_ents == before_ents


def test_ldap_remove_entitlement_already_clean(admin_client, worker_session, monkeypatch):
    conn = _mock_ldap_writeable()
    _patch_ldap(monkeypatch, conn)
    # directory already drifted clean: bob was removed from his group
    from ldap3 import MODIFY_DELETE

    assert conn.modify(
        "CN=Read-Only,OU=groups,DC=example,DC=com",
        {"member": [(MODIFY_DELETE, ["cn=bob,ou=people,dc=example,dc=com"])]},
    )
    _setup_world(admin_client, "ldap2", "ldap", LDAP_CFG)
    review_id, action_id = _revoke_bob(admin_client, "ldap-clean")

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row = _action(admin_client, action_id)
    assert row["status"] == "completed"
    assert "already clean" in row["result"]


def test_ldap_disable_account_e2e(admin_client, worker_session, monkeypatch):
    conn = _mock_ldap_writeable()
    _patch_ldap(monkeypatch, conn)
    cfg = dict(LDAP_CFG, disable_attr="nsAccountLock", disable_value="true")
    _setup_world(admin_client, "ldap3", "ldap", cfg)
    review_id, action_id = _revoke_bob(admin_client, "ldap-dis", target="disable_account")

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row = _action(admin_client, action_id)
    assert "target=disable_account" in row["result"]
    assert "nsAccountLock=true" in row["result"]
    # the write landed on bob's entry
    _ensure_bound(conn)
    conn.search("cn=bob,ou=people,dc=example,dc=com", "(objectClass=*)",
                attributes=["nsAccountLock"])
    vals = conn.entries[0].entry_attributes_as_dict["nsAccountLock"]
    assert str(vals[0]) == "true"
    # already-clean second run: a FRESH review (reviews are one-shot) in a
    # fresh world; the attribute is already flipped so no write happens
    _setup_world(admin_client, "ldap3b", "ldap", cfg)
    review2_id, action2_id = _revoke_bob(admin_client, "ldap-dis2",
                                         target="disable_account")
    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row2 = _action(admin_client, action2_id)
    assert "already clean" in row2["result"]


def test_ldap_disable_needs_config(admin_client, worker_session, monkeypatch):
    conn = _mock_ldap_writeable()
    _patch_ldap(monkeypatch, conn)
    _setup_world(admin_client, "ldap4", "ldap", LDAP_CFG)  # no disable_attr
    review_id, action_id = _revoke_bob(admin_client, "ldap-dis3", target="disable_account")

    stats = _run_worker(worker_session)
    assert stats["requeued"] == 1, stats
    row = _action(admin_client, action_id)
    assert "disable_attr" in row["result"]


def test_ldap_user_not_found_fails_clear(admin_client, worker_session, monkeypatch):
    conn = _mock_ldap_writeable()
    _patch_ldap(monkeypatch, conn)
    _setup_world(admin_client, "ldap5", "ldap", LDAP_CFG)
    review_id, action_id = _revoke_bob(admin_client, "ldap-ghost")
    # snapshot now points at an account the directory does not know
    from sqlalchemy import text

    engine = _db_engine(admin_client)
    with engine.begin() as c:
        snap = json.loads(c.execute(
            text("SELECT snapshot FROM remediation_actions WHERE id = :i"),
            {"i": action_id},
        ).scalar())
        snap["account_value"] = "ghost"
        c.execute(text("UPDATE remediation_actions SET snapshot = :s WHERE id = :i"),
                  {"s": json.dumps(snap), "i": action_id})
    engine.dispose()

    stats = _run_worker(worker_session)
    assert stats["requeued"] == 1, stats
    row = _action(admin_client, action_id)
    assert "user not found" in row["result"]


def test_ldap_no_entitlement_guard(admin_client, worker_session, monkeypatch):
    conn = _mock_ldap_writeable()
    _patch_ldap(monkeypatch, conn)
    _setup_world(admin_client, "ldap6", "ldap", LDAP_CFG)
    review_id, action_id = _revoke_bob(admin_client, "ldap-noent")
    engine = _db_engine(admin_client)
    from sqlalchemy import text

    with engine.begin() as c:
        snap = json.loads(c.execute(
            text("SELECT snapshot FROM remediation_actions WHERE id = :i"),
            {"i": action_id},
        ).scalar())
        snap["entitlement_name"] = None
        c.execute(text("UPDATE remediation_actions SET snapshot = :s WHERE id = :i"),
                  {"s": json.dumps(snap), "i": action_id})
    engine.dispose()

    stats = _run_worker(worker_session)
    assert stats["requeued"] == 1, stats
    row = _action(admin_client, action_id)
    assert "no entitlement in snapshot" in row["result"]


# --------------------------------------------------------------- Entra


def _entra_transport(state):
    """MockTransport covering: token, user-by-UPN filter, group-by-name
    filter, member $ref DELETE, user GET/PATCH. `state` is a dict the
    handler mutates (calls recorded, membership toggled). Route on
    request.url.path + decoded .params — raw query strings percent-encode
    '$' as '%24', so substring checks against str(url) never match."""
    state.setdefault("users", {
        "alice@x.io": {"id": "u-1", "accountEnabled": True},
        "bob@x.io": {"id": "u-2", "accountEnabled": True},
    })
    state.setdefault("groups", {"Eng-Admins": "g-1", "Read-Only": "g-2"})
    state.setdefault("members", {"g-2": {"u-2"}})  # bob in Read-Only
    users = state["users"]
    groups = state["groups"]
    members = state["members"]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = request.url.params
        state.setdefault("calls", []).append(f"{request.method} {path}?{str(params)}")
        if "login.microsoftonline.com" in request.url.host:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        filt = params.get("$filter") or ""
        if path.endswith("/users") and filt:
            matches = [
                {"id": u["id"], "userPrincipalName": upn}
                for upn, u in users.items()
                if f"userPrincipalName eq '{upn}'" == filt
            ]
            return httpx.Response(200, json={"value": matches})
        if path.endswith("/groups") and filt:
            matches = [
                {"id": gid, "displayName": name}
                for name, gid in groups.items() if f"displayName eq '{name}'" == filt
            ]
            return httpx.Response(200, json={"value": matches})
        if request.method == "DELETE" and "/members/" in path and path.endswith("/$ref"):
            uid = path.split("/members/")[1].split("/")[0]
            gid = path.split("/groups/")[1].split("/")[0]
            if uid not in members.get(gid, set()):
                return httpx.Response(404, json={"error": {"message": "not a member"}})
            members[gid].discard(uid)
            return httpx.Response(204)
        if "/users/" in path and request.method == "GET":
            uid = path.split("/users/")[1].split("/")[0]
            for upn, u in users.items():
                if u["id"] == uid:
                    return httpx.Response(200, json={
                        "id": uid, "userPrincipalName": upn,
                        "accountEnabled": u["accountEnabled"],
                    })
            return httpx.Response(404)
        if "/users/" in path and request.method == "PATCH":
            uid = path.split("/users/")[1].split("/")[0]
            for upn, u in users.items():
                if u["id"] == uid:
                    u["accountEnabled"] = False
                    return httpx.Response(204)
            return httpx.Response(404)
        return httpx.Response(404, json={"error": "no route"})

    return httpx.MockTransport(handler)


def _upn_matches(upn, filt):  # pragma: no cover - helper kept for clarity
    return f"userPrincipalName eq '{upn}'" == filt


ENTRA_CFG = {"tenant_id": "t-1", "client_id": "c-1"}


def _patch_entra(monkeypatch, transport):
    monkeypatch.setattr(
        "app.core.connectors._entra_async_client",
        lambda timeout: httpx.AsyncClient(transport=transport, timeout=timeout),
    )


def test_entra_remove_entitlement_e2e(admin_client, worker_session, monkeypatch):
    state: dict = {}
    transport = _entra_transport(state)
    _patch_entra(monkeypatch, transport)
    src_id = _setup_world(admin_client, "entra1", "entra", ENTRA_CFG)
    before_accounts, _ = _mirror_state(admin_client, src_id)
    # snapshot account_value must be the UPN the directory knows
    review_id, action_id = _revoke_bob(admin_client, "entra-rm")
    engine = _db_engine(admin_client)
    from sqlalchemy import text

    with engine.begin() as c:
        snap = json.loads(c.execute(
            text("SELECT snapshot FROM remediation_actions WHERE id = :i"),
            {"i": action_id},
        ).scalar())
        snap["account_value"] = "bob@x.io"
        c.execute(text("UPDATE remediation_actions SET snapshot = :s WHERE id = :i"),
                  {"s": json.dumps(snap), "i": action_id})
    engine.dispose()

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row = _action(admin_client, action_id)
    assert "entra remove_entitlement: removed bob@x.io from Read-Only" in row["result"]
    assert state["members"]["g-2"] == set()
    calls = " ".join(state["calls"])
    assert "DELETE" in calls and "/groups/g-2/members/u-2/$ref" in calls.replace(
        "%24ref", "$ref")
    assert _mirror_state(admin_client, src_id)[0] == before_accounts


def test_entra_remove_entitlement_already_clean(admin_client, worker_session, monkeypatch):
    state: dict = {}
    state["members"] = {"g-2": set()}  # bob already out of Read-Only
    transport = _entra_transport(state)
    _patch_entra(monkeypatch, transport)
    _setup_world(admin_client, "entra2", "entra", ENTRA_CFG)
    review_id, action_id = _revoke_bob(admin_client, "entra-clean")
    from sqlalchemy import text

    engine = _db_engine(admin_client)
    with engine.begin() as c:
        snap = json.loads(c.execute(
            text("SELECT snapshot FROM remediation_actions WHERE id = :i"),
            {"i": action_id},
        ).scalar())
        snap["account_value"] = "bob@x.io"
        c.execute(text("UPDATE remediation_actions SET snapshot = :s WHERE id = :i"),
                  {"s": json.dumps(snap), "i": action_id})
    engine.dispose()

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row = _action(admin_client, action_id)
    assert "already clean" in row["result"]


def test_entra_disable_account_e2e(admin_client, worker_session, monkeypatch):
    state: dict = {}
    transport = _entra_transport(state)
    _patch_entra(monkeypatch, transport)
    _setup_world(admin_client, "entra3", "entra", ENTRA_CFG)
    review_id, action_id = _revoke_bob(admin_client, "entra-dis", target="disable_account")
    from sqlalchemy import text

    engine = _db_engine(admin_client)
    with engine.begin() as c:
        snap = json.loads(c.execute(
            text("SELECT snapshot FROM remediation_actions WHERE id = :i"),
            {"i": action_id},
        ).scalar())
        snap["account_value"] = "bob@x.io"
        c.execute(text("UPDATE remediation_actions SET snapshot = :s WHERE id = :i"),
                  {"s": json.dumps(snap), "i": action_id})
    engine.dispose()

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row = _action(admin_client, action_id)
    assert "entra disable_account: accountEnabled=false" in row["result"]
    assert state["users"]["bob@x.io"]["accountEnabled"] is False
    # second run: fresh world + review; already disabled -> clean, no PATCH
    _setup_world(admin_client, "entra3b", "entra", ENTRA_CFG)
    review2_id, action2_id = _revoke_bob(admin_client, "entra-dis2",
                                         target="disable_account")
    engine = _db_engine(admin_client)
    with engine.begin() as c:
        snap = json.loads(c.execute(
            text("SELECT snapshot FROM remediation_actions WHERE id = :i"),
            {"i": action2_id},
        ).scalar())
        snap["account_value"] = "bob@x.io"
        c.execute(text("UPDATE remediation_actions SET snapshot = :s WHERE id = :i"),
                  {"s": json.dumps(snap), "i": action2_id})
    engine.dispose()
    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row2 = _action(admin_client, action2_id)
    assert "already clean" in row2["result"]


def test_entra_user_not_found(admin_client, worker_session, monkeypatch):
    state: dict = {}
    transport = _entra_transport(state)
    _patch_entra(monkeypatch, transport)
    _setup_world(admin_client, "entra4", "entra", ENTRA_CFG)
    review_id, action_id = _revoke_bob(admin_client, "entra-ghost")
    from sqlalchemy import text

    engine = _db_engine(admin_client)
    with engine.begin() as c:
        snap = json.loads(c.execute(
            text("SELECT snapshot FROM remediation_actions WHERE id = :i"),
            {"i": action_id},
        ).scalar())
        snap["account_value"] = "ghost@x.io"
        c.execute(text("UPDATE remediation_actions SET snapshot = :s WHERE id = :i"),
                  {"s": json.dumps(snap), "i": action_id})
    engine.dispose()

    stats = _run_worker(worker_session)
    assert stats["requeued"] == 1, stats
    row = _action(admin_client, action_id)
    assert "entra user not found" in row["result"]


# ----------------------------------------------------------------- SQL


def _seed_access_db(tmp_dir):
    db = Path(tmp_dir) / "access.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE access (account TEXT, entitlement TEXT, privilege TEXT);
        INSERT INTO access VALUES ('alice', 'Eng-Admins', 'high');
        INSERT INTO access VALUES ('bob', 'Read-Only', 'low');
        """
    )
    con.commit()
    con.close()
    return db


SQL_CFG = {
    "url": "sqlite:///{db}",
    "query": "SELECT account, entitlement, privilege FROM access",
    "remove_entitlement_sql":
        "DELETE FROM access WHERE account = :account_value "
        "AND entitlement = :entitlement_name",
    "disable_account_sql":
        "UPDATE access SET privilege = 'disabled' WHERE account = :account_value",
}


def _sql_cfg(admin_client, tmp_dir):
    db = _seed_access_db(Path(admin_client.app.state.test_db_path).parent)
    cfg = dict(SQL_CFG)
    cfg["url"] = f"sqlite:///{db}"
    return cfg, db


def test_sql_remove_entitlement_e2e(admin_client, worker_session):
    cfg, db = _sql_cfg(admin_client, None)
    src_id = _setup_world(admin_client, "sql1", "sql", cfg)
    before_accounts, _ = _mirror_state(admin_client, src_id)
    review_id, action_id = _revoke_bob(admin_client, "sql-rm")

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row = _action(admin_client, action_id)
    assert "sql remove_entitlement" in row["result"]
    assert "1 row(s) affected" in row["result"]
    con = sqlite3.connect(db)
    remaining = con.execute(
        "SELECT account, entitlement FROM access ORDER BY 1, 2"
    ).fetchall()
    con.close()
    assert remaining == [("alice", "Eng-Admins")]
    assert _mirror_state(admin_client, src_id)[0] == before_accounts


def test_sql_disable_account_e2e(admin_client, worker_session):
    cfg, db = _sql_cfg(admin_client, None)
    _setup_world(admin_client, "sql2", "sql", cfg)
    review_id, action_id = _revoke_bob(admin_client, "sql-dis", target="disable_account")

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row = _action(admin_client, action_id)
    assert "sql disable_account" in row["result"]
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT account, privilege FROM access ORDER BY 1"
    ).fetchall()
    con.close()
    assert rows == [("alice", "high"), ("bob", "disabled")]


def test_sql_missing_statement_fails_clear(admin_client, worker_session):
    cfg, db = _sql_cfg(admin_client, None)
    del cfg["remove_entitlement_sql"]
    _setup_world(admin_client, "sql3", "sql", cfg)
    review_id, action_id = _revoke_bob(admin_client, "sql-missing")

    stats = _run_worker(worker_session)
    assert stats["requeued"] == 1, stats
    row = _action(admin_client, action_id)
    assert "remove_entitlement_sql" in row["result"]


def test_sql_bind_params_bound_not_interpolated(admin_client, worker_session):
    """The statement must receive values as bind params — an entitlement
    name that looks like SQL must never execute as SQL."""
    cfg, db = _sql_cfg(admin_client, None)
    _setup_world(admin_client, "sql4", "sql", cfg)
    review_id, action_id = _revoke_bob(admin_client, "sql-inject")
    from sqlalchemy import text

    engine = _db_engine(admin_client)
    with engine.begin() as c:
        snap = json.loads(c.execute(
            text("SELECT snapshot FROM remediation_actions WHERE id = :i"),
            {"i": action_id},
        ).scalar())
        snap["entitlement_name"] = "x' OR '1'='1"
        c.execute(text("UPDATE remediation_actions SET snapshot = :s WHERE id = :i"),
                  {"s": json.dumps(snap), "i": action_id})
    engine.dispose()

    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats  # bind param, not syntax error
    con = sqlite3.connect(db)
    n = con.execute("SELECT count(*) FROM access").fetchone()[0]
    con.close()
    assert n == 2  # nothing deleted — the name matched no real row


# ---------------------------------------------------- dispatch + guards


def test_csv_source_enforce_fails_clear(admin_client, worker_session):
    """csv/xlsx sources have no write-back arm; the action fails honestly
    (config error: enforce rule must target a connector source)."""
    r = admin_client.post("/api/sources", json={
        "name": "Enforce csv src", "source_type": "csv",
        "owner_employee_id": "E-ADMIN",
    })
    assert r.status_code == 200, r.text
    from sqlalchemy import text

    engine = _db_engine(admin_client)
    with engine.begin() as c:
        # give the source one low account + review so a rule can trigger
        src_id = c.execute(text(
            "SELECT id FROM data_sources WHERE name = 'Enforce csv src'"
        )).scalar()
        c.execute(text(
            "INSERT INTO accounts (data_source_id, account_value, "
            " account_type, privilege_level, created_at) "
            "VALUES (:s, 'bob', 'user', 'low', datetime('now'))"
        ), {"s": src_id})
        ent = c.execute(text(
            "INSERT INTO entitlements (data_source_id, name, catalog_id, is_active, "
            " created_at) VALUES (:s, 'Read-Only', 'ENT-csv-1', 1, datetime('now')) "
            "RETURNING id"
        ), {"s": src_id}).scalar()
        c.execute(text(
            "UPDATE accounts SET entitlement_id = :e "
            "WHERE account_value = 'bob' AND data_source_id = :s"
        ), {"e": ent, "s": src_id})
        camp = c.execute(text(
            "INSERT INTO campaigns (name, review_mode, status, scope, "
            " created_at, updated_at) "
            "VALUES ('enforce-csv-c', 'manager', 'ACTIVE', '{}', "
            " datetime('now'), datetime('now')) RETURNING id"
        )).scalar()
        acct = c.execute(text(
            "SELECT id FROM accounts WHERE account_value = 'bob' "
            "AND data_source_id = :s"
        ), {"s": src_id}).scalar()
        review = c.execute(text(
            "INSERT INTO reviews (campaign_id, account_id, reviewer_id, status, "
            " assigned_at) VALUES (:c, :a, 1, 'PENDING', datetime('now')) "
            "RETURNING id"
        ), {"c": camp, "a": acct}).scalar()
    engine.dispose()
    _make_enforce_rule(admin_client, "csv-guard")
    r = admin_client.post(f"/api/reviews/{review}/submit",
                          json={"decision": "revoke", "comments": "x"})
    assert r.status_code == 200, r.text

    stats = _run_worker(worker_session)
    assert stats["requeued"] == 1, stats
    action = _row(
        admin_client,
        "SELECT result FROM remediation_actions ORDER BY id DESC LIMIT 1",
    )
    assert "no enforcement write-back" in action["result"] or \
        "enforcement needs a configured ldap/entra/sql source" in action["result"]


def test_gated_enforce_requires_approval_then_delivers(
    admin_client, worker_session, monkeypatch
):
    """The approval gate applies to enforce actions: high-privilege revoke
    starts pending_approval; only after PUT approve does the worker claim."""
    conn = _mock_ldap_writeable()
    _patch_ldap(monkeypatch, conn)
    cfg = dict(LDAP_CFG)
    cfg["disable_attr"] = "nsAccountLock"
    cfg["disable_value"] = "true"
    _setup_world(admin_client, "gate1", "ldap", cfg)

    # D6 default: require_approval unset -> ON for enforce. The gate test
    # deliberately does NOT opt out.
    _make_enforce_rule(admin_client, "gate-high", target="disable_account",
                       require_approval=None)
    alice_review = _row(
        admin_client,
        "SELECT r.id FROM reviews r JOIN accounts a ON a.id = r.account_id "
        "WHERE a.privilege_level = 'high' LIMIT 1",
    )
    r = admin_client.post(f"/api/reviews/{alice_review['id']}/submit",
                          json={"decision": "revoke", "comments": "gate test"})
    assert r.status_code == 200, r.text
    gated = _row(
        admin_client,
        "SELECT id, status FROM remediation_actions "
        "WHERE review_id = :r ORDER BY id DESC LIMIT 1",
        {"r": alice_review["id"]},
    )
    assert gated["status"] == "pending_approval"  # high risk -> gated by default

    stats = _run_worker(worker_session)  # nothing claimable while gated
    assert stats["claimed"] == 0, stats
    _ensure_bound(conn)
    conn.search("cn=alice,ou=people,dc=example,dc=com", "(objectClass=*)",
                attributes=["nsAccountLock"])
    assert not conn.entries[0].entry_attributes_as_dict.get("nsAccountLock")

    _approve(admin_client, gated["id"])
    stats = _run_worker(worker_session)
    assert stats["completed"] == 1, stats
    row = _action(admin_client, gated["id"])
    assert row["status"] == "completed"
    assert "target=disable_account" in row["result"]
    _ensure_bound(conn)
    conn.search("cn=alice,ou=people,dc=example,dc=com", "(objectClass=*)",
                attributes=["nsAccountLock"])
    assert str(conn.entries[0].entry_attributes_as_dict["nsAccountLock"][0]) == "true"


def test_audit_written_for_enforce_execution(admin_client, worker_session, monkeypatch):
    conn = _mock_ldap_writeable()
    _patch_ldap(monkeypatch, conn)
    _setup_world(admin_client, "aud1", "ldap", LDAP_CFG)
    review_id, action_id = _revoke_bob(admin_client, "audit-rm")
    _run_worker(worker_session)

    r = admin_client.get("/api/audit?action=remediation_action_executed")
    assert r.status_code == 200
    items = r.json()["items"]

    def _details(it):
        # /api/audit returns details as the raw JSON string; parse like the
        # feed router does (json.loads with raw fallback).
        d = it.get("details")
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except ValueError:
                return {}
        return d if isinstance(d, dict) else {}

    assert any(
        _details(it).get("action_type") == "enforce" and
        "target=remove_entitlement" in (_details(it).get("result") or "")
        for it in items
    ), items[-3:]
    r = admin_client.get("/api/audit/verify")
    assert r.json()["valid"] is True
