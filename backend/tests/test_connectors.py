"""Adapter unit tests (Feature 2 Phase C): real code paths, built-in
mocks only — ldap3 MOCK strategy (no server), httpx.MockTransport (no
network), sql against a real SQLite file through the real engine path.
Plus registry shape and one full worker pass via the real registry."""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.connectors import (  # noqa: E402
    EntraAdapter,
    LdapAdapter,
    SqlAdapter,
    get_adapter,
)
from app.core.sync_worker import run_pass  # noqa: E402

# ---------------------------------------------------------------- LDAP


def _mock_ldap_entries():
    """Real ldap3 MOCK strategy server + connection with seeded entries."""
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
                "userPrincipalName": ["alice@x.io"],
                "memberOf": [
                    "CN=Eng-Admins,OU=groups,DC=example,DC=com",
                    "CN=Payroll-Vault,OU=groups,DC=example,DC=com",
                ],
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
    ]:
        conn.add(dn, ["person"], attrs)
    return conn


LDAP_CFG = {
    "url": "ldap://mock.local:389",
    "base_dn": "dc=example,dc=com",
    "bind_dn": "cn=admin,dc=example,dc=com",
    "account_attr": "sAMAccountName",
    "entitlements_attr": "memberOf",
}


def _patch_connect(monkeypatch, conn):
    monkeypatch.setattr(
        "app.core.connectors._ldap_connect", lambda *a, **k: conn
    )


def test_ldap_fetch_maps_entries(monkeypatch):
    conn = _mock_ldap_entries()
    _patch_connect(monkeypatch, conn)
    snap = asyncio.run(LdapAdapter().fetch(LDAP_CFG, "pw"))
    by_value = {a.value: a for a in snap.accounts}
    assert set(by_value) == {"alice", "bob"}
    assert by_value["alice"].entitlements == ("Eng-Admins", "Payroll-Vault")
    assert by_value["bob"].entitlements == ("Read-Only",)


def test_ldap_validate_bad_credentials(monkeypatch):
    def boom(*a, **k):
        from ldap3.core.exceptions import LDAPBindError

        raise LDAPBindError("invalid credentials")

    monkeypatch.setattr("app.core.connectors._ldap_connect", boom)
    with pytest.raises(ValueError, match="ldap connect failed"):
        LdapAdapter().validate(LDAP_CFG, "wrong-pw")


def test_ldap_missing_base_dn_rejected():
    with pytest.raises(ValueError, match="base_dn"):
        LdapAdapter().validate({"url": "ldap://x"}, "")


def test_ldap_validate_size_limit_is_success(monkeypatch):
    """Real directories answer a size-limited base probe with result 4
    (sizeLimitExceeded); that proves reachability, not failure (found
    live against osixia OpenLDAP 1.5.0 in the phase-E proof)."""
    conn = _mock_ldap_entries()

    def search(*args, **kwargs):
        conn.result = {"result": 4, "description": "sizeLimitExceeded"}

    conn.search = search
    _patch_connect(monkeypatch, conn)
    LdapAdapter().validate(LDAP_CFG, "pw")  # must not raise


def test_ldap_fetch_requests_operational_attributes(monkeypatch):
    """memberOf is an operational attr: '*' alone never returns it, so
    real directories (OpenLDAP memberOf overlay, AD) would mirror zero
    entitlements. Pin the requested attribute list (found live in the
    phase-E proof)."""
    requested = []
    conn = _mock_ldap_entries()
    real_search = conn.search

    def spy(*args, **kwargs):
        requested.append(kwargs.get("attributes"))
        return real_search(*args, **kwargs)

    conn.search = spy
    _patch_connect(monkeypatch, conn)
    asyncio.run(LdapAdapter().fetch(LDAP_CFG, "pw"))
    assert requested, "fetch must issue searches"
    for attrs in requested:
        assert "*" in attrs and "memberOf" in attrs


# --------------------------------------------------------------- Entra

ENTRA_CFG = {"tenant_id": "t-1", "client_id": "c-1"}

ENTRA_USERS_PAGE1 = {
    "value": [
        {"id": "u-1", "userPrincipalName": "alice@x.io", "mail": "alice@x.io"},
        {"id": "u-2", "userPrincipalName": "bob@x.io", "mail": "bob@x.io"},
    ],
    "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=2",
}


def _entra_mock(member_by_id=None, next_link_users=None):
    member_by_id = member_by_id if member_by_id is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "login.microsoftonline.com" in request.url.host:
            return httpx.Response(200, json={
                "access_token": "tok-1", "expires_in": 3600,
            })
        if path.endswith("/users") and "$skiptoken" not in str(request.url):
            payload = dict(ENTRA_USERS_PAGE1)
            if next_link_users is False:
                payload.pop("@odata.nextLink", None)
            else:
                payload["@odata.nextLink"] = next_link_users or payload["@odata.nextLink"]
            return httpx.Response(200, json=payload)
        if "$skiptoken" in str(request.url):
            return httpx.Response(200, json={
                "value": [
                    {"id": "u-3", "userPrincipalName": "carol@x.io",
                     "mail": "carol@x.io"},
                ],
            })
        for uid, names in member_by_id.items():
            if uid in path:
                return httpx.Response(200, json={
                    "value": [{"displayName": n} for n in names],
                })
        return httpx.Response(404, json={"error": "no route"})

    return httpx.MockTransport(handler)


def test_entra_fetch_paginates_and_maps(monkeypatch):
    transport = _entra_mock(member_by_id={
        "u-1": ["Eng-Admins", "Payroll-Vault"],
        "u-2": ["Read-Only"],
        "u-3": [],
    })
    monkeypatch.setattr(
        "app.core.connectors._entra_async_client",
        lambda timeout: httpx.AsyncClient(transport=transport, timeout=timeout),
    )
    snap = asyncio.run(EntraAdapter().fetch(ENTRA_CFG, "sec"))
    by_value = {a.value: a for a in snap.accounts}
    assert set(by_value) == {"alice@x.io", "bob@x.io", "carol@x.io"}
    assert by_value["alice@x.io"].entitlements == ("Eng-Admins", "Payroll-Vault")
    assert by_value["bob@x.io"].entitlements == ("Read-Only",)
    assert by_value["carol@x.io"].entitlements == ()


def test_entra_validate_uses_token_cache(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "login.microsoftonline.com" in request.url.host:
            calls["n"] += 1
            return httpx.Response(200, json={
                "access_token": "tok-2", "expires_in": 3600,
            })
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.core.connectors._entra_sync_client",
        lambda timeout: httpx.Client(transport=transport, timeout=timeout),
    )
    from app.core import connectors as C

    C._ENTRA_TOKEN_CACHE.clear()
    EntraAdapter().validate(ENTRA_CFG, "sec")
    first = calls["n"]
    assert first == 1
    EntraAdapter().validate(ENTRA_CFG, "sec")  # cached -> no new token call
    assert calls["n"] == 1


def test_entra_validate_bad_secret(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if "login.microsoftonline.com" in request.url.host:
            return httpx.Response(401, json={"error": "invalid_client"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.core.connectors._entra_sync_client",
        lambda timeout: httpx.Client(transport=transport, timeout=timeout),
    )
    from app.core import connectors as C

    C._ENTRA_TOKEN_CACHE.clear()
    with pytest.raises(ValueError, match="token fetch failed"):
        EntraAdapter().validate(ENTRA_CFG, "bad")


def test_entra_missing_ids_rejected():
    with pytest.raises(ValueError, match="tenant_id"):
        EntraAdapter().validate({"client_id": "c"}, "s")
    with pytest.raises(ValueError, match="client_id"):
        EntraAdapter().validate({"tenant_id": "t"}, "s")


def test_entra_404_user_mid_sync(monkeypatch):
    """A user deleted between listing and memberOf fetch is skipped
    gracefully, not a hard failure."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "login.microsoftonline.com" in request.url.host:
            return httpx.Response(200, json={
                "access_token": "tok-3", "expires_in": 3600,
            })
        path = request.url.path
        if path.endswith("/users"):
            return httpx.Response(200, json={
                "value": [
                    {"id": "u-1", "userPrincipalName": "alice@x.io",
                     "mail": "alice@x.io"},
                    {"id": "u-9", "userPrincipalName": "ghost@x.io",
                     "mail": "ghost@x.io"},
                ],
            })
        if "u-1" in path:
            return httpx.Response(200, json={
                "value": [{"displayName": "Eng-Admins"}],
            })
        return httpx.Response(404)  # ghost user vanished mid-sync

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.core.connectors._entra_async_client",
        lambda timeout: httpx.AsyncClient(transport=transport, timeout=timeout),
    )
    snap = asyncio.run(EntraAdapter().fetch(ENTRA_CFG, "sec"))
    by_value = {a.value: a for a in snap.accounts}
    assert by_value["alice@x.io"].entitlements == ("Eng-Admins",)
    assert by_value["ghost@x.io"].entitlements == ()


# ----------------------------------------------------------------- SQL


def _seed_sqlite(tmp_path):
    db = tmp_path / "upstream.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE access (account TEXT, entitlement TEXT, privilege TEXT);
        INSERT INTO access VALUES ('alice', 'Eng-Admins', 'High');
        INSERT INTO access VALUES ('alice', 'Payroll-Vault', NULL);
        INSERT INTO access VALUES ('bob', 'Read-Only', 'low');
        INSERT INTO access VALUES ('', 'should-skip', NULL);
        """
    )
    con.commit()
    con.close()
    return db


SQL_CFG = {
    "url": "sqlite:///{db}",
    "query": "SELECT account, entitlement, privilege FROM access",
}


def test_sql_fetch_real_sqlite(tmp_path):
    db = _seed_sqlite(tmp_path)
    cfg = dict(SQL_CFG, url=f"sqlite:///{db}")
    snap = asyncio.run(SqlAdapter().fetch(cfg, ""))
    by_value = {}
    for rec in snap.accounts:
        if rec.value in by_value:
            by_value[rec.value].entitlements += rec.entitlements
        else:
            by_value[rec.value] = rec
    assert set(by_value) == {"alice", "bob"}  # blank account skipped
    assert set(by_value["alice"].entitlements) == {"Eng-Admins", "Payroll-Vault"}
    assert by_value["bob"].privilege == "low"
    assert by_value["alice"].privilege == "high"


def test_sql_validate_real_sqlite(tmp_path):
    db = _seed_sqlite(tmp_path)
    cfg = dict(SQL_CFG, url=f"sqlite:///{db}")
    SqlAdapter().validate(cfg, "")  # passes: account column present


def test_sql_validate_missing_account_column(tmp_path):
    db = tmp_path / "bad.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (user TEXT, entitlement TEXT)")
    con.commit()
    con.close()
    cfg = {
        "url": f"sqlite:///{db}",
        "query": "SELECT user, entitlement FROM t",
    }
    with pytest.raises(ValueError, match="account"):
        SqlAdapter().validate(cfg, "")


def test_sql_rejects_non_select(tmp_path):
    cfg = {
        "url": f"sqlite:///{tmp_path / 'x.db'}",
        "query": "DELETE FROM access",
    }
    with pytest.raises(ValueError, match="SELECT"):
        SqlAdapter().validate(cfg, "")


def test_sql_secret_placeholder_in_url(tmp_path):
    from app.core.connectors import _sql_dsn

    db = _seed_sqlite(tmp_path)
    dsn = _sql_dsn({"url": f"sqlite:///{db}?$SECRET"}, "pw")
    assert dsn.endswith("?pw")  # placeholder substituted, config not mutated


def test_sql_async_dsn_translated(tmp_path):
    from app.core.connectors import _sql_dsn

    assert _sql_dsn(
        {"url": "postgresql+asyncpg://u:p@h/db"}, ""
    ) == "postgresql+psycopg2://u:p@h/db"
    assert _sql_dsn(
        {"url": "sqlite+aiosqlite:///./x.db"}, ""
    ) == "sqlite:///./x.db"


# ------------------------------------------------------------- Registry


def test_registry_shape():
    for st in ("ldap", "entra", "sql"):
        adapter = get_adapter(st)
        assert callable(adapter.fetch)
        assert callable(adapter.validate)
    for st in ("csv", "xlsx", "nope"):
        with pytest.raises(ValueError, match="no connector adapter"):
            get_adapter(st)


def test_connector_block_echoes_config_not_secret(admin_client, worker_session):
    """GET /api/sources must echo the stored (non-secret) config so the UI
    can prefill the connector panel - regression for the silent-wipe bug
    where reopening the panel showed blanks and saving them wiped config."""
    from app.models.identity import utcnow
    from app.models.source import DataSource

    r = admin_client.post("/api/sources", json={"name": "ECHO", "source_type": "ldap"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    async def configure():
        async with worker_session() as maker:
            async with maker() as s:
                src = await s.get(DataSource, sid)
                src.connector_config = json.dumps({
                    "url": "ldap://ldap.example.com:389",
                    "base_dn": "dc=example,dc=com",
                    "bind_dn": "cn=svc,dc=example,dc=com",
                })
                src.connector_secret = "supersecret"
                await s.commit()

    asyncio.run(configure())

    r = admin_client.get("/api/sources")
    assert r.status_code == 200, r.text
    mine = next(s for s in r.json()["items"] if s["id"] == sid)
    conn = mine["connector"]
    assert conn["configured"] is True
    assert conn["has_secret"] is True
    assert conn["config"] == {
        "url": "ldap://ldap.example.com:389",
        "base_dn": "dc=example,dc=com",
        "bind_dn": "cn=svc,dc=example,dc=com",
    }
    assert "secret" not in json.dumps(conn).lower().replace("has_secret", "")


def test_connector_put_merges_absent_keys_keeps_stored(admin_client, worker_session, monkeypatch):
    """PUT /api/sources/{id}/connector with a PARTIAL config must keep
    stored values for absent keys (merge, not replace) — regression for
    the replace-semantics footgun where a partial PUT silently dropped
    fields. Blank-string values still clear explicitly."""
    from app.models.source import DataSource

    r = admin_client.post("/api/sources", json={"name": "MERGE", "source_type": "ldap"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    async def seed():
        async with worker_session() as maker:
            async with maker() as s:
                src = await s.get(DataSource, sid)
                src.connector_config = json.dumps({
                    "url": "ldap://ldap.example.com:389",
                    "base_dn": "dc=example,dc=com",
                    "bind_dn": "cn=svc,dc=example,dc=com",
                    "filter": "(objectClass=person)",
                })
                src.connector_secret = "stored-secret"
                await s.commit()

    asyncio.run(seed())

    calls = []

    class RecordingAdapter:
        def validate(self, config, secret):
            calls.append((dict(config), secret))

    monkeypatch.setattr(
        "app.routers.sources.get_adapter", lambda _t: RecordingAdapter()
    )

    # Partial PUT: url updated, everything else absent — must keep stored.
    r = admin_client.put(
        f"/api/sources/{sid}/connector",
        json={"config": {"url": "ldap://new.example.com:389"}},
    )
    assert r.status_code == 200, r.text
    assert calls[-1][0] == {
        "url": "ldap://new.example.com:389",
        "base_dn": "dc=example,dc=com",
        "bind_dn": "cn=svc,dc=example,dc=com",
        "filter": "(objectClass=person)",
    }
    assert calls[-1][1] == "stored-secret"

    r = admin_client.get(f"/api/sources/{sid}")
    assert r.status_code == 200, r.text
    conn = r.json()["connector"]
    assert conn["config"]["url"] == "ldap://new.example.com:389"
    assert conn["config"]["base_dn"] == "dc=example,dc=com"
    assert conn["has_secret"] is True


def test_connector_put_blank_string_clears_field(admin_client, worker_session, monkeypatch):
    """Explicit blank string clears that field while other stored keys
    survive — blank-vs-absent is the whole merge contract."""
    from app.models.source import DataSource

    r = admin_client.post("/api/sources", json={"name": "BLANKCLR", "source_type": "ldap"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    async def seed():
        async with worker_session() as maker:
            async with maker() as s:
                src = await s.get(DataSource, sid)
                src.connector_config = json.dumps({
                    "url": "ldap://ldap.example.com:389",
                    "base_dn": "dc=example,dc=com",
                    "bind_dn": "cn=svc,dc=example,dc=com",
                })
                src.connector_secret = "stored-secret"
                await s.commit()

    asyncio.run(seed())

    calls = []

    class RecordingAdapter:
        def validate(self, config, secret):
            calls.append((dict(config), secret))

    monkeypatch.setattr(
        "app.routers.sources.get_adapter", lambda _t: RecordingAdapter()
    )

    # Explicit blank: bind_dn cleared, url/base_dn survive.
    r = admin_client.put(
        f"/api/sources/{sid}/connector",
        json={"config": {"bind_dn": ""}},
    )
    assert r.status_code == 200, r.text
    assert calls[-1][0] == {
        "url": "ldap://ldap.example.com:389",
        "base_dn": "dc=example,dc=com",
    }
    assert "bind_dn" not in calls[-1][0]


def test_worker_pass_through_real_registry(admin_client, worker_session):
    """Full run_pass with the DEFAULT fetch path (registry dispatch):
    a sql source configured against a real SQLite file syncs end-to-end."""
    import io
    from datetime import timedelta

    from app.models.identity import utcnow
    from app.models.source import DataSource

    db = _seed_sqlite(Path(admin_client.app.state.test_db_path).parent)
    csv = (
        "employee_id,username,email,first_name,last_name,department,"
        "manager_employee_id\n"
        "E-1,alice,alice@x.io,Alice,Andrews,Engineering,\n"
        "E-2,bob,bob@x.io,Bob,Brown,Engineering,E-1\n"
    )
    admin_client.post(
        "/api/identities/import",
        files={"file": ("p.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    r = admin_client.post(
        "/api/sources", json={"name": "SQLSRC", "source_type": "sql"}
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    async def configure():
        async with worker_session() as maker:
            async with maker() as s:
                src = await s.get(DataSource, sid)
                src.connector_config = json.dumps({
                    "url": f"sqlite:///{db}",
                    "query": "SELECT account, entitlement, privilege FROM access",
                })
                src.connector_secret = ""
                src.sync_interval_minutes = 60
                src.next_sync_at = utcnow() - timedelta(minutes=5)
                await s.commit()

    asyncio.run(configure())

    async def go():
        async with worker_session() as maker:
            return await run_pass(maker)  # no fetch override: real registry

    stats = asyncio.run(go())
    assert stats["enqueued"] == 1 and stats["completed"] == 1, stats
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    try:
        rows = con.execute(
            "SELECT account_value, privilege_level FROM accounts "
            "WHERE data_source_id=? ORDER BY account_value",
            (sid,),
        ).fetchall()
        assert rows == [("alice", "high"), ("bob", "low")]
        n_ents = con.execute(
            "SELECT count(*) FROM entitlements WHERE data_source_id=?", (sid,)
        ).fetchone()[0]
        assert n_ents == 3  # Eng-Admins, Payroll-Vault, Read-Only
    finally:
        con.close()
    assert admin_client.get("/api/audit/verify").json()["valid"] is True
