"""SoD rule router: CRUD with audit discipline. The only write path."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.core.audit_service import append_audit
from app.models.entitlement import Entitlement
from app.models.sod import SodRule
from app.routers.deps import AnyUser, CertAdminUser, DbSession
router = APIRouter(prefix="/api/sod", tags=["sod"])
SEVERITIES = {"low", "moderate", "high", "very_high"}
class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    entitlement_a_id: int
    entitlement_b_id: int
    severity: str = Field(default="high")
    is_active: bool = True
def _rule_out(r: SodRule, names: dict[int, str]) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "entitlement_a_id": r.entitlement_a_id,
        "entitlement_b_id": r.entitlement_b_id,
        "entitlement_a_name": names.get(r.entitlement_a_id),
        "entitlement_b_name": names.get(r.entitlement_b_id),
        "severity": r.severity,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
async def _ent_names(db, rules) -> dict[int, str]:
    ids = {e for r in rules for e in (r.entitlement_a_id, r.entitlement_b_id)}
    if not ids:
        return {}
    rows = (await db.execute(select(Entitlement).where(Entitlement.id.in_(ids)))).scalars().all()
    return {e.id: e.name for e in rows}
async def _validate_refs(db, a: int, b: int) -> None:
    if a == b:
        raise HTTPException(400, "Rule cannot pair an entitlement with itself")
    found = set(
        (await db.execute(select(Entitlement.id).where(Entitlement.id.in_((a, b))))).scalars().all()
    )
    if found != {a, b}:
        raise HTTPException(400, "Unknown entitlement reference")
@router.get("/rules")
async def list_rules(db: DbSession, user: AnyUser):
    rules = (await db.execute(select(SodRule).order_by(SodRule.id))).scalars().all()
    names = await _ent_names(db, rules)
    return {"items": [_rule_out(r, names) for r in rules]}
@router.get("/rules/{rule_id}")
async def get_rule(rule_id: int, db: DbSession, user: AnyUser):
    r = await db.get(SodRule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    return _rule_out(r, await _ent_names(db, [r]))
@router.post("/rules")
async def create_rule(body: RuleIn, db: DbSession, user: CertAdminUser):
    if body.severity not in SEVERITIES:
        raise HTTPException(400, "severity must be low, moderate, high, or very_high")
    dup = (await db.execute(select(SodRule).where(SodRule.name == body.name))).scalars().first()
    if dup:
        raise HTTPException(409, "Rule name already exists")
    await _validate_refs(db, body.entitlement_a_id, body.entitlement_b_id)
    r = SodRule(
        name=body.name,
        description=body.description,
        entitlement_a_id=body.entitlement_a_id,
        entitlement_b_id=body.entitlement_b_id,
        severity=body.severity,
        is_active=body.is_active,
    )
    db.add(r)
    await db.flush()
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="sod_rule_created", entity_type="sod_rule", entity_id=r.id,
                       details={"name": r.name, "severity": r.severity})
    await db.commit()
    return {"id": r.id, "name": r.name}
@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, body: RuleIn, db: DbSession, user: CertAdminUser):
    if body.severity not in SEVERITIES:
        raise HTTPException(400, "severity must be low, moderate, high, or very_high")
    r = await db.get(SodRule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    dup = (
        await db.execute(
            select(SodRule).where(SodRule.name == body.name, SodRule.id != rule_id)
        )
    ).scalars().first()
    if dup:
        raise HTTPException(409, "Rule name already exists")
    await _validate_refs(db, body.entitlement_a_id, body.entitlement_b_id)
    old = {"name": r.name, "severity": r.severity, "active": r.is_active}
    r.name = body.name
    r.description = body.description
    r.entitlement_a_id = body.entitlement_a_id
    r.entitlement_b_id = body.entitlement_b_id
    r.severity = body.severity
    r.is_active = body.is_active
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="sod_rule_updated", entity_type="sod_rule", entity_id=rule_id,
                       details={"old": old, "new": {"name": r.name, "severity": r.severity,
                                                    "active": r.is_active}})
    await db.commit()
    return {"ok": True}
@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, db: DbSession, user: CertAdminUser):
    r = await db.get(SodRule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    name = r.name
    await db.delete(r)
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="sod_rule_deleted", entity_type="sod_rule", entity_id=rule_id,
                       details={"name": name})
    await db.commit()
    return {"ok": True}
