"""Feature 6 phase B: SCIM protocol surface (auth gate, CRUD, filter, paging)."""
from __future__ import annotations

import asyncio

from app.core.apikeys import hash_key
from app.db import get_db
from app.models.identity import Identity
from app.models.scim import ScimSettings

ERROR_URN = "urn:ietf:params:scim:api:messages:2.0:Error"
USER_URN = "urn:ietf:params:scim:schemas:core:2.0:User"
TOKEN = "iag_scim_test_bearer_token_value_0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _direct_session(client):
    override = client.app.dependency_overrides[get_db]

    async def _go():
        gen = override()
        s = await gen.__anext__()
        try:
            yield s
        finally:
            await gen.aclose()

    return _go()


def _set_scim(client, *, enabled=True, token=TOKEN):
    """Seed/replace the single settings row; creates tables on first use."""
    import json

    async def _go():
        async for s in _direct_session(client):
            row = await s.get(ScimSettings, 1)
            if row is None:
                row = ScimSettings(id=1, config="{}")
                s.add(row)
            row.config = json.dumps({"enabled": enabled})
            row.token_hash = hash_key(token) if token else None
            await s.commit()

    asyncio.run(_go())


def _seed_identities(client, count):
    async def _go():
        async for s in _direct_session(client):
            s.add_all([
                Identity(employee_id=f"E-{i:04d}", username=f"u{i:04d}",
                         email=f"u{i:04d}@x.io")
                for i in range(1, count + 1)
            ])
            await s.commit()

    asyncio.run(_go())


def _audit_feed_stats(client):
    r = client.get("/api/audit/feed/stats")
    assert r.status_code == 200, r.text
    return r.json()


def _create(client, **overrides) -> dict:
    body = {
        "schemas": [USER_URN],
        "userName": "jdoe",
        "externalId": "E-SCIM-1",
        "name": {"givenName": "Jane", "familyName": "Doe"},
        "emails": [{"value": "jdoe@x.io", "type": "work", "primary": True}],
        "title": "Dev",
        "department": "Eng",
        "active": True,
    }
    body.update(overrides)
    r = client.post("/api/scim/v2/Users", headers=AUTH, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- auth gate ---


def test_503_envelope_when_surface_off(client):
    # No settings row at all: enabled=false by absence.
    r = client.get("/api/scim/v2/Users")
    assert r.status_code == 503
    assert r.json()["schemas"] == [ERROR_URN]
    assert r.json()["status"] == "503"


def test_503_when_enabled_but_no_token(client):
    _set_scim(client, enabled=True, token=None)
    r = client.get("/api/scim/v2/Users", headers=AUTH)
    assert r.status_code == 503
    assert r.json()["schemas"] == [ERROR_URN]


def test_401_missing_and_bad_token(client):
    _set_scim(client)
    r = client.get("/api/scim/v2/Users")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["schemas"] == [ERROR_URN]
    r = client.get("/api/scim/v2/Users", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert r.json()["schemas"] == [ERROR_URN]


def test_401_for_api_key_style_token(client):
    # A valid /api api-key must NOT open the SCIM surface: different
    # credential class (spec: SCIM token authority is exactly SCIM).
    _set_scim(client)
    r = client.get("/api/scim/v2/Users", headers={"Authorization": "Bearer iag_1_whatever"})
    assert r.status_code == 401


def test_disabled_flag_gates_even_with_valid_token(client):
    _set_scim(client, enabled=False)
    r = client.get("/api/scim/v2/Users", headers=AUTH)
    assert r.status_code == 503


# --- ServiceProviderConfig ---


def test_spc_served_behind_auth(client):
    _set_scim(client)
    r = client.get("/api/scim/v2/ServiceProviderConfig", headers=AUTH)
    assert r.status_code == 200
    spc = r.json()
    assert spc["patch"]["supported"] is True
    assert spc["bulk"]["supported"] is False


# --- create ---


def test_create_201_echo_and_audit(admin_client):
    _set_scim(admin_client)
    body = _create(admin_client)
    assert body["id"] == "E-SCIM-1"
    assert body["externalId"] == "E-SCIM-1"
    assert body["userName"] == "jdoe"
    assert body["active"] is True
    assert body["meta"]["resourceType"] == "User"
    stats = _audit_feed_stats(admin_client)
    assert stats["chain_valid"] is True
    entries = admin_client.get("/api/audit/feed?limit=50").text.splitlines()
    created = [e for e in entries if '"scim_user_created"' in e]
    assert len(created) == 1
    assert '"actor_username":"scim"' in created[0].replace(", ", ",").replace('", "', '"')
    assert '"actor_id":null' in created[0] or '"actor_id": null' in created[0]


def test_create_409s_on_each_duplicate(admin_client):
    _set_scim(admin_client)
    _create(admin_client)
    # same userName
    r = admin_client.post("/api/scim/v2/Users", headers=AUTH, json={
        "userName": "jdoe", "externalId": "E-OTHER"})
    assert r.status_code == 409
    assert "userName" in r.json()["detail"]
    # same email
    r = admin_client.post("/api/scim/v2/Users", headers=AUTH, json={
        "userName": "unique1", "externalId": "E-OTHER",
        "emails": [{"value": "jdoe@x.io"}]})
    assert r.status_code == 409
    # same externalId
    r = admin_client.post("/api/scim/v2/Users", headers=AUTH, json={
        "userName": "unique2", "externalId": "E-SCIM-1"})
    assert r.status_code == 409


def test_create_400_missing_username_or_externalid(admin_client):
    _set_scim(admin_client)
    r = admin_client.post("/api/scim/v2/Users", headers=AUTH, json={"externalId": "E-X"})
    assert r.status_code == 400
    assert r.json()["schemas"] == [ERROR_URN]
    r = admin_client.post("/api/scim/v2/Users", headers=AUTH, json={"userName": "x"})
    assert r.status_code == 400
    assert "externalId" in r.json()["detail"]


# --- list + filter + paging ---


def test_list_paging_and_totals(admin_client):
    _set_scim(admin_client)
    _seed_identities(admin_client, 5)
    r = admin_client.get("/api/scim/v2/Users?startIndex=2&count=2", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["totalResults"] == 6  # 5 seeded + E-ADMIN from conftest
    assert body["startIndex"] == 2
    assert body["itemsPerPage"] == 2
    assert [u["id"] for u in body["Resources"]] == ["E-0001", "E-0002"]  # id order, E-ADMIN first


def test_list_count_clamped_to_max(admin_client):
    _set_scim(admin_client)
    _seed_identities(admin_client, 205)
    r = admin_client.get("/api/scim/v2/Users?count=100000", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["totalResults"] == 206
    assert body["itemsPerPage"] == 200  # PAGE_MAX_COUNT clamp


def test_list_filters_each_field(admin_client):
    _set_scim(admin_client)
    _seed_identities(admin_client, 5)
    r = admin_client.get(
        '/api/scim/v2/Users?filter=userName eq "u0002"', headers=AUTH)
    assert [u["userName"] for u in r.json()["Resources"]] == ["u0002"]
    r = admin_client.get(
        '/api/scim/v2/Users?filter=emails.value eq "u0003@x.io"', headers=AUTH)
    assert [u["userName"] for u in r.json()["Resources"]] == ["u0003"]
    r = admin_client.get(
        '/api/scim/v2/Users?filter=externalId eq "E-ADMIN"', headers=AUTH)
    assert [u["userName"] for u in r.json()["Resources"]] == ["admin"]


def test_list_filter_unsupported_400_envelope(admin_client):
    _set_scim(admin_client)
    r = admin_client.get('/api/scim/v2/Users?filter=userName co "u"', headers=AUTH)
    assert r.status_code == 400
    assert r.json()["schemas"] == [ERROR_URN]


def test_get_user_404_envelope(admin_client):
    _set_scim(admin_client)
    r = admin_client.get("/api/scim/v2/Users/E-NOPE", headers=AUTH)
    assert r.status_code == 404
    assert r.json()["schemas"] == [ERROR_URN]


# --- PUT / PATCH ---


def test_put_replaces_mutable_attrs(admin_client):
    _set_scim(admin_client)
    _create(admin_client)
    r = admin_client.put("/api/scim/v2/Users/E-SCIM-1", headers=AUTH, json={
        "userName": "jdoe2", "externalId": "E-SCIM-1",
        "name": {"givenName": "Janet", "familyName": "Doe"},
        "emails": [{"value": "janet@x.io"}], "title": "Sr Dev", "active": False})
    assert r.status_code == 200
    body = r.json()
    assert body["userName"] == "jdoe2"
    assert body["title"] == "Sr Dev"
    assert body["active"] is False


def test_put_externalid_mismatch_400(admin_client):
    _set_scim(admin_client)
    _create(admin_client)
    r = admin_client.put("/api/scim/v2/Users/E-SCIM-1", headers=AUTH, json={
        "userName": "jdoe", "externalId": "E-DIFFERENT"})
    assert r.status_code == 400
    assert "externalId" in r.json()["detail"]


def test_patch_active_flip_okta_shape(admin_client):
    _set_scim(admin_client)
    _create(admin_client)
    r = admin_client.patch("/api/scim/v2/Users/E-SCIM-1", headers=AUTH, json={
        "Operations": [{"op": "replace", "value": {"active": False}}]})
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_patch_name_parts_compose(admin_client):
    # Regression for the phase-A gap: flat dotted name paths must reach
    # the identity, not silently no-op.
    _set_scim(admin_client)
    _create(admin_client)
    r = admin_client.patch("/api/scim/v2/Users/E-SCIM-1", headers=AUTH, json={
        "Operations": [{"op": "replace", "path": "name.familyName", "value": "Smith"}]})
    assert r.status_code == 200
    assert r.json()["name"]["familyName"] == "Smith"


def test_patch_add_remove_400(admin_client):
    _set_scim(admin_client)
    _create(admin_client)
    r = admin_client.patch("/api/scim/v2/Users/E-SCIM-1", headers=AUTH, json={
        "Operations": [{"op": "add", "path": "active", "value": True}]})
    assert r.status_code == 400
    r = admin_client.patch("/api/scim/v2/Users/E-SCIM-1", headers=AUTH, json={
        "Operations": [{"op": "remove", "path": "title"}]})
    assert r.status_code == 400


def test_patch_nothing_writable_no_audit(admin_client):
    # Path-less replace whose value object is empty folds to zero
    # writable fields: 200 echo (normalize_patch contract: empty fold =
    # nothing writable), and no audit entry - nothing changed.
    _set_scim(admin_client)
    _create(admin_client)
    before = _audit_feed_stats(admin_client)["total_entries"]
    r = admin_client.patch("/api/scim/v2/Users/E-SCIM-1", headers=AUTH, json={
        "Operations": [{"op": "replace", "value": {}}]})
    assert r.status_code == 200
    after = _audit_feed_stats(admin_client)["total_entries"]
    assert after == before


def test_put_uniqueness_409(admin_client):
    _set_scim(admin_client)
    _create(admin_client)
    _create(admin_client, userName="smith", externalId="E-SCIM-2",
            emails=[{"value": "smith@x.io"}])
    r = admin_client.put("/api/scim/v2/Users/E-SCIM-2", headers=AUTH, json={
        "userName": "jdoe", "emails": [{"value": "smith@x.io"}]})
    assert r.status_code == 409


# --- DELETE ---


def test_delete_soft_and_idempotent_with_audit(admin_client):
    _set_scim(admin_client)
    _create(admin_client)
    r = admin_client.delete("/api/scim/v2/Users/E-SCIM-1", headers=AUTH)
    assert r.status_code == 204
    # still readable, now inactive
    r = admin_client.get("/api/scim/v2/Users/E-SCIM-1", headers=AUTH)
    assert r.json()["active"] is False
    # second delete: 204 again, second audit entry (IdP retry recorded)
    before = _audit_feed_stats(admin_client)["total_entries"]
    r = admin_client.delete("/api/scim/v2/Users/E-SCIM-1", headers=AUTH)
    assert r.status_code == 204
    after = _audit_feed_stats(admin_client)["total_entries"]
    assert after == before + 1
    depro = admin_client.get("/api/audit/feed?limit=10").text
    assert depro.count('"scim_user_deprovisioned"') >= 2


def test_delete_404_envelope(admin_client):
    _set_scim(admin_client)
    r = admin_client.delete("/api/scim/v2/Users/E-NOPE", headers=AUTH)
    assert r.status_code == 404
    assert r.json()["schemas"] == [ERROR_URN]


# --- chain ---


def test_chain_valid_after_write_flows(admin_client):
    _set_scim(admin_client)
    _create(admin_client)
    admin_client.patch("/api/scim/v2/Users/E-SCIM-1", headers=AUTH, json={
        "Operations": [{"op": "replace", "path": "active", "value": False}]})
    admin_client.delete("/api/scim/v2/Users/E-SCIM-1", headers=AUTH)
    assert _audit_feed_stats(admin_client)["chain_valid"] is True
