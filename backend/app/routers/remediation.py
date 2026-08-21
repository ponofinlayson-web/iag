"""Remediation router: rules CRUD, action queue, approvals, settings.

Write paths follow audit discipline (change + audit, one commit); rule
saves compile the entitlement regex so a bad pattern is a 400 at SAVE,
never a trigger-time surprise (D6). Approve/cancel/retry change action
state with audit; retry never resets attempts (D5).
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.audit_service import append_audit
from app.core.remediation_trigger import get_remediation_config
from app.models.identity import utcnow
from app.models.remediation import (
    DEFAULT_CONFIG,
    RemediationAction,
    RemediationRule,
    RemediationSettings,
    RemediationStatus,
)
from app.routers.deps import AdminUser, AnyUser, CertAdminUser, DbSession

router = APIRouter(prefix="/api/remediation", tags=["remediation"])

ACTIONS = {"notify_owner", "webhook"}
PRIVILEGES = {"low", "moderate", "high", "very_high"}


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    data_source_id: int | None = None
    privilege_level: str | None = None
    entitlement_pattern: str | None = Field(default=None, max_length=255)
    action: str = "notify_owner"
    webhook_url: str | None = None
    is_active: bool = True
    require_approval: bool = False


class SettingsIn(BaseModel):
    enabled: bool = True
    default_action: str = "notify_owner"
    require_approval_for_high_risk: bool = True


class ActionUpdate(BaseModel):
    op: str = Field(pattern="^(approve|cancel)$")


async def _validate_rule(db, body: RuleIn) -> None:
    if body.action not in ACTIONS:
        raise HTTPException(400, "action must be notify_owner or webhook")
    if body.action == "webhook" and not (body.webhook_url or "").strip():
        raise HTTPException(400, "webhook action requires webhook_url")
    if body.privilege_level is not None and body.privilege_level not in PRIVILEGES:
        raise HTTPException(400, "privilege_level must be low, moderate, high, very_high")
    if body.entitlement_pattern is not None:
        try:
            re.compile(body.entitlement_pattern)
        except re.error as exc:
            raise HTTPException(400, f"invalid entitlement_pattern: {exc}") from exc
    if body.data_source_id is not None:
        from app.models.source import DataSource

        if (await db.get(DataSource, body.data_source_id)) is None:
            raise HTTPException(400, "Unknown data_source_id")


def _rule_out(r: RemediationRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "data_source_id": r.data_source_id,
        "privilege_level": r.privilege_level,
        "entitlement_pattern": r.entitlement_pattern,
        "action": r.action,
        "webhook_url": r.webhook_url,
        "is_active": r.is_active,
        "require_approval": r.require_approval,
        "times_triggered": r.times_triggered,
        "times_executed": r.times_executed,
        "times_failed": r.times_failed,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/rules")
async def list_rules(db: DbSession, user: AnyUser):
    rules = (await db.execute(select(RemediationRule).order_by(RemediationRule.id))).scalars().all()
    return {"items": [_rule_out(r) for r in rules]}


@router.post("/rules")
async def create_rule(body: RuleIn, db: DbSession, user: CertAdminUser):
    dup = (
        await db.execute(select(RemediationRule).where(RemediationRule.name == body.name))
    ).scalars().first()
    if dup:
        raise HTTPException(409, "Rule name already exists")
    await _validate_rule(db, body)
    r = RemediationRule(
        name=body.name,
        description=body.description,
        data_source_id=body.data_source_id,
        privilege_level=body.privilege_level,
        entitlement_pattern=body.entitlement_pattern,
        action=body.action,
        webhook_url=body.webhook_url,
        is_active=body.is_active,
        require_approval=body.require_approval,
    )
    db.add(r)
    await db.flush()
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="remediation_rule_created", entity_type="remediation_rule",
                       entity_id=r.id,
                       details={"name": r.name, "action": r.action})
    await db.commit()
    return {"id": r.id, "name": r.name}


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, body: RuleIn, db: DbSession, user: CertAdminUser):
    r = await db.get(RemediationRule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    dup = (
        await db.execute(
            select(RemediationRule).where(
                RemediationRule.name == body.name, RemediationRule.id != rule_id
            )
        )
    ).scalars().first()
    if dup:
        raise HTTPException(409, "Rule name already exists")
    await _validate_rule(db, body)
    old = {"name": r.name, "action": r.action, "active": r.is_active}
    r.name = body.name
    r.description = body.description
    r.data_source_id = body.data_source_id
    r.privilege_level = body.privilege_level
    r.entitlement_pattern = body.entitlement_pattern
    r.action = body.action
    r.webhook_url = body.webhook_url
    r.is_active = body.is_active
    r.require_approval = body.require_approval
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="remediation_rule_updated", entity_type="remediation_rule",
                       entity_id=rule_id,
                       details={"old": old,
                                "new": {"name": r.name, "action": r.action,
                                        "active": r.is_active}})
    await db.commit()
    return {"ok": True}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, db: DbSession, user: CertAdminUser):
    r = await db.get(RemediationRule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    name = r.name
    await db.delete(r)
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="remediation_rule_deleted", entity_type="remediation_rule",
                       entity_id=rule_id, details={"name": name})
    await db.commit()
    return {"ok": True}


def _action_out(a: RemediationAction, rule_name: str | None) -> dict:
    import json as _json

    try:
        snap = _json.loads(a.snapshot) if isinstance(a.snapshot, str) else a.snapshot
    except (TypeError, ValueError):
        snap = {}
    return {
        "id": a.id,
        "review_id": a.review_id,
        "rule_id": a.rule_id,
        "rule_name": rule_name,
        "account_id": a.account_id,
        "action_type": a.action_type,
        "status": a.status,
        "requires_approval": a.requires_approval,
        "approved_by_id": a.approved_by_id,
        "approved_at": a.approved_at.isoformat() if a.approved_at else None,
        "attempts": a.attempts,
        "result": a.result,
        "executed_at": a.executed_at.isoformat() if a.executed_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "snapshot": snap,
    }


@router.get("/actions")
async def list_actions(
    db: DbSession,
    user: AnyUser,
    status: str | None = None,
    campaign_id: int | None = None,
    rule_id: int | None = None,
    limit: int = 100,
):
    q = select(RemediationAction).order_by(RemediationAction.id.desc()).limit(min(limit, 500))
    if status:
        q = q.where(RemediationAction.status == status)
    if rule_id:
        q = q.where(RemediationAction.rule_id == rule_id)
    rows = list((await db.execute(q)).scalars().all())
    if campaign_id:
        # snapshot holds campaign_id; filter in Python (JSON in TEXT col)
        rows = [
            a for a in rows
            if str(campaign_id) == str(a.snapshot_dict().get("campaign_id"))
        ]
    rule_names: dict[int, str] = {}
    rule_ids = {a.rule_id for a in rows if a.rule_id is not None}
    if rule_ids:
        found = (
            await db.execute(select(RemediationRule).where(RemediationRule.id.in_(rule_ids)))
        ).scalars().all()
        rule_names = {f.id: f.name for f in found}
    return {
        "items": [_action_out(a, rule_names.get(a.rule_id)) for a in rows],
        "total": len(rows),
    }


@router.put("/actions/{action_id}")
async def update_action(action_id: int, body: ActionUpdate, db: DbSession, user: CertAdminUser):
    a = await db.get(RemediationAction, action_id)
    if a is None:
        raise HTTPException(404, "Action not found")
    if body.op == "approve":
        if a.status != RemediationStatus.PENDING_APPROVAL:
            raise HTTPException(409, f"Action is {a.status}, not pending_approval")
        a.status = RemediationStatus.APPROVED
        a.approved_by_id = user.id
        a.approved_at = utcnow()
        action_name = "remediation_action_approved"
    else:  # cancel
        if a.status in (RemediationStatus.COMPLETED, RemediationStatus.CANCELLED):
            raise HTTPException(409, f"Action already {a.status}")
        a.status = RemediationStatus.CANCELLED
        action_name = "remediation_action_cancelled"
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action=action_name, entity_type="remediation_action",
                       entity_id=action_id,
                       details={"op": body.op, "status": a.status,
                                "action_type": a.action_type})
    await db.commit()
    return {"ok": True, "status": a.status}


@router.post("/actions/{action_id}/retry")
async def retry_action(action_id: int, db: DbSession, user: CertAdminUser):
    """failed -> approved for ONE more worker attempt. attempts NOT reset
    (D5: history stays honest). Repeated clicks each buy one attempt."""
    a = await db.get(RemediationAction, action_id)
    if a is None:
        raise HTTPException(404, "Action not found")
    if a.status != RemediationStatus.FAILED:
        raise HTTPException(409, f"Action is {a.status}, not failed")
    a.status = RemediationStatus.APPROVED
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="remediation_action_retry", entity_type="remediation_action",
                       entity_id=action_id,
                       details={"attempts_before": a.attempts})
    await db.commit()
    return {"ok": True, "attempts": a.attempts}


@router.get("/settings")
async def get_settings_route(db: DbSession, user: AnyUser):
    return await get_remediation_config(db)


@router.put("/settings")
async def put_settings(body: SettingsIn, db: DbSession, user: AdminUser):
    if body.default_action not in ACTIONS:
        raise HTTPException(400, "default_action must be notify_owner or webhook")
    old = await get_remediation_config(db)
    row = await db.get(RemediationSettings, 1)
    if row is None:
        row = RemediationSettings(id=1, config="")
        db.add(row)
    row.config = json.dumps({
        "enabled": body.enabled,
        "default_action": body.default_action,
        "require_approval_for_high_risk": body.require_approval_for_high_risk,
    })
    await db.flush()
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="remediation_settings_updated",
                       entity_type="remediation_settings", entity_id=1,
                       details={"old": old, "new": json.loads(row.config)})
    await db.commit()
    return json.loads(row.config)
