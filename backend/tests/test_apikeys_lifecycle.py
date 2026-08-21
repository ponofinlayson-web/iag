"""Phase C: API-key lifecycle through the router (create/list/revoke)."""
from __future__ import annotations


def _create(admin_client, **overrides):
    body = {"name": "probe", "role": "auditor"}
    body.update(overrides)
    return admin_client.post("/api/api-keys", json=body)


def test_create_returns_full_key_once(admin_client):
    r = _create(admin_client, name="once-key")
    assert r.status_code == 201, r.text
    body = r.json()
    key = body["key"]
    assert key.startswith("iag_") and len(key.split("_", 2)[2]) == 43
    assert body["key_prefix"] == key[:8]
    assert body["role"] == "auditor"
    assert body["is_active"] is True
    # list must show prefix only - never key or hash
    lst = admin_client.get("/api/api-keys")
    assert lst.status_code == 200
    items = lst.json()["items"]
    assert len(items) >= 1
    row = next(i for i in items if i["name"] == "once-key")
    assert row["key_prefix"] == key[:8]
    assert "key" not in row and "key_hash" not in row
    assert all("key" not in i or i.get("key") is None for i in items)


def test_created_key_authenticates(admin_client):
    key = _create(admin_client, name="usable").json()["key"]
    r = admin_client.get("/api/dashboard", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200 and r.json()["principal"] == "api_key"


def test_duplicate_name_409(admin_client):
    assert _create(admin_client, name="dup").status_code == 201
    assert _create(admin_client, name="dup").status_code == 409


def test_bad_role_400(admin_client):
    for role in ("system_admin", "reviewer", "nonexistent"):
        r = _create(admin_client, name=f"bad-{role}", role=role)
        assert r.status_code == 400, (role, r.status_code, r.text)


def test_past_expires_400(admin_client):
    r = _create(admin_client, name="past", expires_at="2020-01-01T00:00:00Z")
    assert r.status_code == 400
    assert "future" in r.json()["detail"]


def test_revoke_then_401_and_idempotent(admin_client):
    key = _create(admin_client, name="revokeme").json()["key"]
    kid = _create(admin_client, name="revokeme2").json()["id"]
    hdr = {"Authorization": f"Bearer {key}"}
    assert admin_client.get("/api/dashboard", headers=hdr).status_code == 200
    r = admin_client.post(f"/api/api-keys/{kid}/revoke")
    assert r.status_code == 200 and r.json() == {"ok": True, "already_revoked": False}
    assert admin_client.get("/api/dashboard", headers=hdr).status_code == 200  # different key
    # revoke the first one too, then it must 401
    first_id = int(key.split("_")[1])
    r2 = admin_client.post(f"/api/api-keys/{first_id}/revoke")
    assert r2.status_code == 200 and r2.json()["already_revoked"] is False
    assert admin_client.get("/api/dashboard", headers=hdr).status_code == 401
    r3 = admin_client.post(f"/api/api-keys/{first_id}/revoke")
    assert r3.status_code == 200 and r3.json() == {"ok": True, "already_revoked": True}


def test_audit_entries_and_chain(admin_client):
    _create(admin_client, name="audited")
    r = admin_client.get("/api/audit?action=api_key_created")
    assert r.status_code == 200
    names = [i["details"] for i in r.json()["items"]]
    assert any('"audited"' in (d or "") for d in names)
    v = admin_client.get("/api/audit/verify")
    assert v.status_code == 200 and v.json()["valid"] is True


def test_non_admin_403(client):
    from app.core.security import hash_password
    from app.db import Base, build_engine
    from app.models.identity import Identity
    from app.models.user import Role, User
    from sqlalchemy.ext.asyncio import async_sessionmaker
    import asyncio

    async def seed():
        eng = build_engine(f"sqlite+aiosqlite:///{client.app.state.test_db_path}")
        maker = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
        async with maker() as s:
            ident = Identity(employee_id="E-RV2", username="rev2", email="rev2@x.io",
                             first_name="R", last_name="V")
            s.add(ident)
            await s.flush()
            s.add(User(identity_id=ident.id, password_hash=hash_password("revpass123"),
                       role=Role.REVIEWER))
            await s.commit()
        await eng.dispose()

    client.get("/api/dashboard")  # 401, but runs get_db -> creates tables first
    asyncio.run(seed())
    client.post("/api/auth/login", json={"username": "rev2", "password": "revpass123"})
    assert client.get("/api/api-keys").status_code == 403
    assert client.post("/api/api-keys", json={"name": "x", "role": "auditor"}).status_code == 403


def test_401_and_404_shapes(client):
    assert client.get("/api/api-keys").status_code == 401
    assert client.post("/api/api-keys/999/revoke").status_code == 401
