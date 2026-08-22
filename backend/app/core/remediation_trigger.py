"""Remediation trigger: invoked inside the review-submit transaction.

Loads config + active rules, matches them against the revoked account
via the pure engine, creates RemediationAction rows, bumps rule
counters, and appends ONE audit entry per trigger event — all inside
the caller's transaction (invariant 10; decision + actions atomic).
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.core.audit_service import append_audit
from app.core.remediation_engine import AccountContext, matching_rules
from app.models.campaign import Review
from app.models.entitlement import Entitlement
from app.models.identity import Identity
from app.models.remediation import (
    DEFAULT_CONFIG,
    RemediationAction,
    RemediationRule,
    RemediationSettings,
    RemediationStatus,
)
from app.models.source import Account, DataSource

HIGH_PRIVILEGES = ("high", "very_high")


async def get_remediation_config(db) -> dict:
    """Config dict from the single settings row; DEFAULT_CONFIG fallback.

    Migration 0005 seeds the row, but create_all-built test DBs and any
    volume that somehow lost the row need self-healing: insert defaults
    so the settings API always has something to show and edit.
    """
    row = await db.get(RemediationSettings, 1)
    if row is None:
        row = RemediationSettings(id=1, config=json.dumps(DEFAULT_CONFIG))
        db.add(row)
        await db.flush()
        return dict(DEFAULT_CONFIG)
    try:
        stored = json.loads(row.config)
    except (TypeError, ValueError):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG})
    return merged


async def trigger_remediation(db, user, review: Review, account: Account) -> int:
    """Create actions for a REVOKED review. Returns count created.

    Called from _finalize AFTER the review status/decision are set and
    BEFORE the caller's commit. Approve decisions must not call this.
    Reads config + rules in the same TX; on any miss (disabled config,
    no rules matched, no default) creates nothing.
    """
    config = await get_remediation_config(db)
    if not config.get("enabled", True):
        return 0

    rules = (
        await db.execute(
            select(RemediationRule).where(RemediationRule.is_active.is_(True))
        )
    ).scalars().all()

    entitlement_name: str | None = None
    if account.entitlement_id is not None:
        ent = await db.get(Entitlement, account.entitlement_id)
        entitlement_name = ent.name if ent else None

    ctx = AccountContext(
        data_source_id=account.data_source_id,
        privilege_level=account.privilege_level,
        entitlement_name=entitlement_name,
    )
    matched = matching_rules(list(rules), ctx)

    requires_high_risk = bool(config.get("require_approval_for_high_risk", True)) and (
        account.privilege_level in HIGH_PRIVILEGES
    )

    actions: list[RemediationAction] = []
    if matched:
        for rule in matched:
            rule.times_triggered += 1
            actions.append(
                RemediationAction(
                    review_id=review.id,
                    rule_id=rule.id,
                    account_id=account.id,
                    snapshot=await _snapshot(db, review, account, entitlement_name, rule),
                    action_type=rule.action,
                    status=(
                        RemediationStatus.PENDING_APPROVAL
                        if rule.require_approval or requires_high_risk
                        else RemediationStatus.APPROVED
                    ),
                    requires_approval=rule.require_approval or requires_high_risk,
                )
            )
    else:
        default_action = config.get("default_action")
        if default_action:
            actions.append(
                RemediationAction(
                    review_id=review.id,
                    rule_id=None,
                    account_id=account.id,
                    snapshot=await _snapshot(db, review, account, entitlement_name),
                    action_type=default_action,
                    status=(
                        RemediationStatus.PENDING_APPROVAL
                        if requires_high_risk
                        else RemediationStatus.APPROVED
                    ),
                    requires_approval=requires_high_risk,
                )
            )

    if not actions:
        return 0

    for a in actions:
        db.add(a)
    await db.flush()

    await append_audit(
        db,
        actor_id=user.id,
        actor_username=user.identity.username or "",
        action="remediation_actions_created",
        entity_type="remediation_action",
        entity_id=actions[0].id,
        details={
            "review_id": review.id,
            "rule_ids": [a.rule_id for a in actions],
            "action_ids": [a.id for a in actions],
            "default_action_used": matched == [],
        },
    )
    return len(actions)


async def _snapshot(db, review: Review, account: Account, ent_name: str | None,
                    rule: RemediationRule | None = None) -> str:
    source = await db.get(DataSource, account.data_source_id)
    identity = await db.get(Identity, account.identity_id) if account.identity_id else None
    identity_name = None
    if identity is not None:
        identity_name = f"{identity.first_name or ''} {identity.last_name or ''}".strip()
        if not identity_name:
            identity_name = identity.username or identity.email
    snap = {
        "review_id": review.id,
        "campaign_id": review.campaign_id,
        "account_value": account.account_value,
        "account_type": account.account_type,
        "privilege_level": account.privilege_level,
        "entitlement_name": ent_name,
        "data_source_id": account.data_source_id,
        "data_source_name": source.name if source else None,
        "identity_name": identity_name,
        "ts": _utc_iso(),
    }
    if rule is not None and rule.action == "enforce":
        # feature-6: freeze the rule's target choice at trigger time (the
        # action must not silently change meaning if the rule is edited
        # before delivery). D's worker reads target from here.
        snap["target"] = rule.target or "remove_entitlement"
    return json.dumps(snap)


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
