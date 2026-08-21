"""Phase B: API-key principal wiring (auth path, chokes, SessionUser sweep)."""
from __future__ import annotations
from datetime import timedelta

from app.core import apikeys as keyfns
from app.models.apikey import ApiKey
from app.models.identity import utcnow
from app.models.user import Role


def _seed_key(client, *, role=Role.AUDITOR, active=True, expires=None):
    """Insert a key row behind the API (router lands in Phase C); returns
    the full key string exactly as a client would present it. Seeds via
    the app's overridden get_db (its override engine owns the tables)."""
    import asyncio
    from app.db import get_db

    override = client.app.dependency_overrides[get_db]

    async def _go():
        gen = override()  # first call also creates tables + seeds admin
        s = await gen.__anext__()
        try:
            row = ApiKey(
                name=f"probe-key-{keyfns.generate_token()[:8]}",
                key_prefix="iag_xxxx",
                key_hash="placeholder",
                role=role,
                is_active=active,
                expires_at=expires,
            )
            s.add(row)
            await s.flush()
            full, prefix, digest = keyfns.generate_key(row.id)
            row.key_prefix = prefix
            row.key_hash = digest
            await s.commit()
            return full
        finally:
            await gen.aclose()

    return asyncio.run(_go())


def _hdr(full_key):
    return {"Authorization": f"Bearer {full_key}"}


def test_key_reads_dashboard_mixed_payload(client):
    key = _seed_key(client)
    r = client.get("/api/dashboard", headers=_hdr(key))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["principal"] == "api_key"
    assert body["my_pending_reviews"] == 0
    assert "identities" in body  # portfolio section is real


def test_key_wrong_token_401(client):
    key = _seed_key(client)
    r = client.get("/api/dashboard", headers=_hdr(key + "x"))
    assert r.status_code == 401
    assert "Invalid API key" in r.json()["detail"]


def test_key_revoked_401(client):
    key = _seed_key(client, active=False)
    r = client.get("/api/dashboard", headers=_hdr(key))
    assert r.status_code == 401
    assert "revoked" in r.json()["detail"]


def test_key_expired_401(client):
    key = _seed_key(client, expires=utcnow() - timedelta(seconds=1))
    r = client.get("/api/dashboard", headers=_hdr(key))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"]


def test_key_malformed_401(client):
    for bad in ("iag_1", "garbage", "iag_", "XAG_9_tok"):
        r = client.get("/api/dashboard", headers=_hdr(bad))
        assert r.status_code == 401, bad


def test_key_role_allows_audit_read(client):
    key = _seed_key(client, role=Role.AUDITOR)
    r = client.get("/api/audit", headers=_hdr(key))
    assert r.status_code == 200, r.text


def test_key_role_below_guard_403(client):
    key = _seed_key(client, role=Role.REPORT_VIEWER)
    r = client.get("/api/audit", headers=_hdr(key))
    assert r.status_code == 403


def test_key_write_blocked_403(client):
    key = _seed_key(client)
    r = client.post("/api/identities", headers=_hdr(key), json={})
    assert r.status_code == 403
    assert "read-only" in r.json()["detail"]
    r2 = client.put("/api/remediation/settings", headers=_hdr(key), json={})
    assert r2.status_code == 403
    assert "read-only" in r2.json()["detail"]


def test_key_cannot_manage_keys_403(client):
    key = _seed_key(client)
    r = client.get("/api/api-keys", headers=_hdr(key))
    assert r.status_code == 403
    assert "manage" in r.json()["detail"]


def test_key_personal_endpoints_403(client):
    key = _seed_key(client)
    for method, path in (
        ("get", "/api/auth/me"),
        ("post", "/api/auth/logout"),
        ("post", "/api/auth/change-password"),
        ("get", "/api/reviews/queue"),
        ("get", "/api/reviews/count"),
        ("get", "/api/reviews/history"),
        ("post", "/api/reviews/999/submit"),
    ):
        r = getattr(client, method)(path, headers=_hdr(key))
        assert r.status_code == 403, (method, path, r.status_code)


def test_last_used_at_set_on_first_use(client):
    key = _seed_key(client)
    r = client.get("/api/dashboard", headers=_hdr(key))
    assert r.status_code == 200
    import asyncio
    from app.db import build_engine

    async def _go():
        eng = build_engine(f"sqlite+aiosqlite:///{client.app.state.test_db_path}")
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
            maker = async_sessionmaker(eng, class_=AsyncSession,
                                       expire_on_commit=False, autoflush=False)
            async with maker() as s:
                row = await s.get(ApiKey, keyfns.parse_key(key)[0])
                return row.last_used_at
        finally:
            await eng.dispose()

    first = asyncio.run(_go())
    assert first is not None
    r2 = client.get("/api/dashboard", headers=_hdr(key))
    assert r2.status_code == 200
    second = asyncio.run(_go())
    assert second == first  # throttled: no rewrite inside 60s


def test_cookie_flow_still_works(admin_client):
    r = admin_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["role"] == "system_admin"
    r2 = admin_client.get("/api/dashboard")
    assert r2.status_code == 200
    assert r2.json().get("principal") is None  # cookie principal, no flag


def test_logout_requires_session_now(client):
    r = client.post("/api/auth/logout")
    assert r.status_code == 401
