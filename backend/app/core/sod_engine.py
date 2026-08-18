"""SoD engine: read-side evaluation of active rules against identity access.

Pure function of (entitlements held, active rules) -> violations. Never
writes, never persists violations: results are computed per-request and
surfaced as context in campaign preview and review detail. Reviewers
decide; the engine only informs (ARCHITECTURE.md design slot).
"""
from __future__ import annotations
from sqlalchemy import select
from app.models.entitlement import Entitlement
from app.models.sod import SodRule
from app.models.source import Account

async def violations_for_identities(db, identity_ids) -> dict[int, list[dict]]:
    """Map each identity id -> list of SoD violations across ALL their
    linked accounts (any source). Empty dict input returns {}."""
    ids = set(identity_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Account.identity_id, Account.entitlement_id)
            .where(Account.identity_id.in_(ids), Account.entitlement_id.is_not(None))
        )
    ).all()
    held: dict[int, set[int]] = {}
    for identity_id, ent_id in rows:
        held.setdefault(identity_id, set()).add(ent_id)
    if not held:
        return {}
    rules = (
        await db.execute(select(SodRule).where(SodRule.is_active.is_(True)))
    ).scalars().all()
    rules = [r for r in rules if r.entitlement_a_id != r.entitlement_b_id]
    if not rules:
        return {}
    ent_names: dict[int, str] = {}
    needed = {e for r in rules for e in (r.entitlement_a_id, r.entitlement_b_id)}
    for e in (await db.execute(select(Entitlement).where(Entitlement.id.in_(needed)))).scalars():
        ent_names[e.id] = e.name
    out: dict[int, list[dict]] = {}
    for identity_id, ents in held.items():
        for r in rules:
            if r.entitlement_a_id in ents and r.entitlement_b_id in ents:
                out.setdefault(identity_id, []).append({
                    "rule_id": r.id,
                    "rule_name": r.name,
                    "severity": r.severity,
                    "entitlement_a": ent_names.get(r.entitlement_a_id, f"ENT#{r.entitlement_a_id}"),
                    "entitlement_b": ent_names.get(r.entitlement_b_id, f"ENT#{r.entitlement_b_id}"),
                })
    return out
