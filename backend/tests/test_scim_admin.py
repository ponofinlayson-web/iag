"""Feature 6 phase C: SCIM management surface + enforce rule CRUD + trigger
snapshot keys + worker dispatch guard. Session-auth AdminUser on config/token;
enforce rules validate target and default require_approval ON (D6)."""
from __future__ import annotations

import asyncio
import json

from app.core.apikeys import hash_key
from app.db import get_db
from app.models.remediation import RemediationRule


def _session(client):
    override = client.app.dependency_overrides[get_db]

    async def _go():
        gen = override()
        s = await gen.__anext__()
        try:
            yield s
        finally:
            await gen.aclose()

    return _go()


def _audit_actions(admin_client, action: str) -> list[dict]:
    r = admin_client.get(f"/api/audit?action={action}&page_size=50")
    assert r.status_code == 200, r.text
    return r.json()["items"]


# --- SCIM management surface: admin gating ---


def test_config_and_token_require_session(client):
    assert client.get("/api/scim/config").status_code == 401
    assert client.put("/api/scim/config", json={"enabled": True}).status_code == 401
    assert client.post("/api/scim/token").status_code == 401
    assert client.delete("/api/scim/token").status_code == 401


def test_config_and_token_cert_admin_403(client):
    from app.core.security import hash_password
    from app.db import build_engine
    from app.models.identity import Identity
    from app.models.user import Role, User
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def seed():
        eng = build_engine(f"sqlite+aiosqlite:///{client.app.state.test_db_path}")
        maker = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
        async with maker() as s:
            ident = Identity(employee_id="E-CA1", username="ca1", email="ca1@x.io")
            s.add(ident)
            await s.flush()
            s.add(User(identity_id=ident.id, password_hash=hash_password("capass123"),
                       role=Role.CERTIFICATION_ADMIN))
            await s.commit()
        await eng.dispose()

    client.get("/api/scim/config")  # 401, but creates tables first
    asyncio.run(seed())
    r = client.post("/api/auth/login", json={"username": "ca1", "password": "capass123"})
    assert r.status_code == 200, r.text
    assert client.get("/api/scim/config").status_code == 403
    assert client.post("/api/scim/token").status_code == 403
    assert client.delete("/api/scim/token").status_code == 403
    assert client.put("/api/scim/config", json={"enabled": True}).status_code == 403


# --- config GET/PUT ---


def test_config_defaults_and_enabled_toggle(admin_client):
    r = admin_client.get("/api/scim/config")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"enabled": False, "token_prefix": None, "token_created_at": None}

    r = admin_client.put("/api/scim/config", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    assert "token_hash" not in r.json()

    audit = _audit_actions(admin_client, "scim_config_updated")
    assert audit and '"enabled":true' in (audit[0]["details"] or "")

    # surface stays off without a token (503 envelope, phase-B contract)
    r = admin_client.get("/api/scim/v2/ServiceProviderConfig")
    assert r.status_code == 503

    r = admin_client.put("/api/scim/config", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False


def test_config_put_validates_body(admin_client):
    r = admin_client.put("/api/scim/config", json={"enabled": "yes"})
    assert r.status_code == 400
    r = admin_client.put("/api/scim/config", json={})
    assert r.status_code == 400


# --- token lifecycle ---


def test_token_generate_reveal_once_and_hash_never_returned(admin_client):
    admin_client.put("/api/scim/config", json={"enabled": True})
    r = admin_client.post("/api/scim/token")
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert token.startswith("iag_scim_") and len(token) > len("iag_scim_") + 30

    cfg = admin_client.get("/api/scim/config").json()
    assert cfg["token_prefix"] == token[:16]
    assert cfg["token_created_at"] is not None
    assert "token_hash" not in cfg
    # the response of a second GET never carries the raw token
    assert token not in admin_client.get("/api/scim/config").text

    # protocol surface now serves behind the bearer
    r = admin_client.get("/api/scim/v2/ServiceProviderConfig",
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200

    audit = _audit_actions(admin_client, "scim_token_rotated")
    assert audit, "first generation must audit (as scim_token_rotated, spec pins the name)"


def test_token_rotate_kills_old_at_same_commit(admin_client):
    admin_client.put("/api/scim/config", json={"enabled": True})
    old = admin_client.post("/api/scim/token").json()["token"]
    new = admin_client.post("/api/scim/token").json()["token"]
    assert old != new

    hdr_old = {"Authorization": f"Bearer {old}"}
    hdr_new = {"Authorization": f"Bearer {new}"}
    assert admin_client.get("/api/scim/v2/Users", headers=hdr_old).status_code == 401
    assert admin_client.get("/api/scim/v2/Users", headers=hdr_new).status_code == 200


def test_token_delete_kills_surface_and_is_idempotent(admin_client):
    admin_client.put("/api/scim/config", json={"enabled": True})
    token = admin_client.post("/api/scim/token").json()["token"]
    hdr = {"Authorization": f"Bearer {token}"}
    assert admin_client.get("/api/scim/v2/Users", headers=hdr).status_code == 200

    r = admin_client.delete("/api/scim/token")
    assert r.status_code == 200 and r.json() == {"ok": True, "already_revoked": False}
    # enabled stays true, but no token -> 503 surface
    assert admin_client.get("/api/scim/config").json()["enabled"] is True
    assert admin_client.get("/api/scim/v2/Users", headers=hdr).status_code == 503

    r = admin_client.delete("/api/scim/token")
    assert r.status_code == 200 and r.json()["already_revoked"] is True

    audits = _audit_actions(admin_client, "scim_token_revoked")
    assert len(audits) >= 1


def test_management_flow_chain_verifies(admin_client):
    admin_client.put("/api/scim/config", json={"enabled": True})
    admin_client.post("/api/scim/token")
    admin_client.delete("/api/scim/token")
    admin_client.put("/api/scim/config", json={"enabled": False})
    r = admin_client.get("/api/audit/verify")
    assert r.status_code == 200 and r.json()["valid"] is True


# --- enforce rule CRUD ---


def _rule(client, **overrides) -> dict:
    body = {
        "name": "enforce-rule",
        "action": "enforce",
        "target": "remove_entitlement",
        "entitlement_pattern": "^Engineering",
        "require_approval": None,
    }
    body.update(overrides)
    return body


def test_enforce_rule_crud_with_target(admin_client):
    r = admin_client.post("/api/remediation/rules", json=_rule(admin_client))
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    rules = admin_client.get("/api/remediation/rules").json()["items"]
    row = next(x for x in rules if x["id"] == rid)
    assert row["action"] == "enforce"
    assert row["target"] == "remove_entitlement"
    assert row["require_approval"] is True  # D6: defaults ON for enforce

    r = admin_client.put(f"/api/remediation/rules/{rid}",
                         json=_rule(admin_client, target="disable_account",
                                    require_approval=False))
    assert r.status_code == 200, r.text
    row = next(x for x in admin_client.get("/api/remediation/rules").json()["items"]
               if x["id"] == rid)
    assert row["target"] == "disable_account"
    assert row["require_approval"] is False  # explicit opt-out honored

    # non-enforce actions never persist a target even if one is sent
    r = admin_client.post("/api/remediation/rules",
                          json=_rule(admin_client, name="plain-notify",
                                     action="notify_owner"))
    assert r.status_code == 200, r.text
    nid = r.json()["id"]
    row = next(x for x in admin_client.get("/api/remediation/rules").json()["items"]
               if x["id"] == nid)
    assert row["target"] is None
    assert row["require_approval"] is False  # non-enforce default unchanged


def test_enforce_rule_validation_400s(admin_client):
    base = _rule(admin_client)
    r = admin_client.post("/api/remediation/rules",
                          json={**base, "target": "delete_everything"})
    assert r.status_code == 400
    r = admin_client.post("/api/remediation/rules",
                          json={**base, "webhook_url": "https://x.example/hook"})
    assert r.status_code == 400


def test_default_action_still_rejects_enforce(admin_client):
    r = admin_client.put("/api/remediation/settings",
                         json={"enabled": True, "default_action": "enforce",
                               "require_approval_for_high_risk": True})
    assert r.status_code == 400


def test_notify_rule_defaults_unchanged(admin_client):
    r = admin_client.post("/api/remediation/rules", json={
        "name": "notify-default", "action": "notify_owner"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    row = next(x for x in admin_client.get("/api/remediation/rules").json()["items"]
               if x["id"] == rid)
    assert row["require_approval"] is False


# --- trigger snapshot carries target + data_source_id (phase-D seam) ---


def test_trigger_snapshot_freezes_target_and_source_id(client):
    """End-to-end lite: build the trigger inputs by hand and call
    _snapshot directly - the review-submit path is feature-3-tested; here
    we pin the two new keys an enforce action must freeze."""
    from app.core.remediation_trigger import _snapshot
    from app.models.campaign import Campaign, Review
    from app.models.source import Account, DataSource

    async def go():
        async for s in _session(client):
            src = DataSource(name="ldap-prod", source_type="ldap")
            s.add(src)
            await s.flush()
            rule = RemediationRule(name="freeze-rule", action="enforce",
                                   target="disable_account")
            s.add(rule)
            await s.flush()
            camp = Campaign(name="c1", review_mode="manager")
            s.add(camp)
            await s.flush()
            acct = Account(data_source_id=src.id, account_value="jdoe",
                           account_type="user")
            s.add(acct)
            await s.flush()
            review = Review(campaign_id=camp.id, account_id=acct.id, reviewer_id=1)
            s.add(review)
            await s.commit()

            snap = json.loads(await _snapshot(s, review, acct, "Engineering Admin", rule))
            assert snap["target"] == "disable_account"
            assert snap["data_source_id"] == src.id
            assert snap["data_source_name"] == "ldap-prod"

            snap2 = json.loads(await _snapshot(s, review, acct, "Engineering Admin"))
            assert "target" not in snap2  # non-rule snapshot has no target
            assert snap2["data_source_id"] == src.id

    asyncio.run(go())


# --- worker dispatch guard ---


def test_worker_unknown_action_type_fails_with_own_name(client, worker_session):
    from app.core.remediation_worker import run_pass
    from app.models.campaign import Campaign, Review
    from app.models.remediation import RemediationAction, RemediationStatus
    from app.models.source import Account
    from app.core.settings import Settings

    async def seed():
        from app.models.source import DataSource

        async for s in _session(client):
            src = DataSource(name="dispatch-guard-src", source_type="csv")
            s.add(src)
            await s.flush()
            camp = Campaign(name="dispatch-guard-c1", review_mode="manager")
            s.add(camp)
            await s.flush()
            acct = Account(data_source_id=src.id, account_value="jdoe",
                           account_type="user")
            s.add(acct)
            await s.flush()
            review = Review(campaign_id=camp.id, account_id=acct.id, reviewer_id=1)
            s.add(review)
            await s.flush()
            s.add(RemediationAction(
                review_id=review.id, rule_id=None, account_id=acct.id,
                action_type="carrier_pigeon",
                snapshot=json.dumps({"account_value": "jdoe"}),
                status=RemediationStatus.APPROVED,
            ))
            await s.commit()

    asyncio.run(seed())
    async def go():
        async with worker_session() as maker:
            return await run_pass(maker, settings=Settings())

    stats = asyncio.run(go())
    assert stats["claimed"] == 1
    assert stats["requeued"] == 1  # attempts=1 < max: retryable, not dead-letter

    async def check():
        async for s in _session(client):
            row = (await s.execute(
                __import__("sqlalchemy").select(RemediationAction)
            )).scalars().first()
            # honest failure with its own action name, not the webhook arm's
            assert "carrier_pigeon" in row.result and "no delivery arm" in row.result
            assert "webhook_url" not in row.result

    asyncio.run(check())


def test_worker_enforce_arm_registered(client, worker_session):
    """Phase D: enforce HAS a delivery arm now. A mis-wired registry would
    silently fall back to _deliver_unsupported; pin the registry shape."""
    from app.core.remediation_worker import _DELIVERERS, _deliver_enforce

    assert _DELIVERERS.get("enforce") is _deliver_enforce
