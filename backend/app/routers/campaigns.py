"""Campaign router: lifecycle, scope, dry-run preview, start."""
from __future__ import annotations
import csv
import io
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from app.core.audit_service import append_audit
from app.core.email_templates import (
    TemplateRenderError,
    build_review_url,
    render_email,
)
from app.core.sod_engine import violations_for_identities
from app.models.campaign import Campaign, CampaignStatus, Review, ReviewStatus
from app.models.email import EmailOutbox, OutboxStatus
from app.models.entitlement import Entitlement
from app.models.identity import Identity, utcnow
from app.models.risk import RiskSnapshot
from app.models.source import Account, DataSource
from app.models.user import Role, User
from app.routers.deps import AnyUser, CertAdminUser, DbSession, ReportViewer, get_settings
router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
PRIVILEGED = ("high", "very_high")
class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    review_mode: str = Field(default="source_owner", pattern="^(source_owner|manager)$")
    scope: dict = {}
    deadline: datetime | None = None
def _scope_filters(scope: dict):
    filters = []
    if scope.get("data_source_ids"):
        filters.append(Account.data_source_id.in_(scope["data_source_ids"]))
    if scope.get("departments"):
        filters.append(Identity.department.in_(scope["departments"]))
    if scope.get("privileged_only"):
        filters.append(Account.privilege_level.in_(PRIVILEGED))
    if scope.get("unlinked_only"):
        filters.append(Account.identity_id.is_(None))
    return filters
async def _scoped_accounts(db, scope: dict):
    filters = _scope_filters(scope)
    stmt = (
        select(Account)
        .join(Identity, Account.identity_id == Identity.id, isouter=True)
        .where(*filters)
        .order_by(Account.id)
    )
    return (await db.execute(stmt)).scalars().all()
async def _source_owners(db, account_rows) -> dict:
    owner_ids = set()
    for a in account_rows:
        owner_ids.add(a.data_source_id)
    owners = {}
    if owner_ids:
        rows = (
            await db.execute(
                select(DataSource, User)
                .join(User, User.identity_id == DataSource.owner_identity_id, isouter=True)
                .where(DataSource.id.in_(owner_ids))
            )
        ).all()
        for src, u in rows:
            if u is not None:
                owners[src.id] = u
    return owners
@router.get("")
async def list_campaigns(db: DbSession, user: AnyUser):
    rows = (await db.execute(select(Campaign).order_by(Campaign.id.desc()))).scalars().all()
    counts = dict(
        (await db.execute(
            select(Review.campaign_id, func.count())
            .where(Review.status == ReviewStatus.PENDING)
            .group_by(Review.campaign_id)
        )).all()
    )
    return {
        "items": [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status.value,
                "review_mode": c.review_mode,
                "pending_reviews": counts.get(c.id, 0),
                "deadline": c.deadline.isoformat() if c.deadline else None,
            }
            for c in rows
        ]
    }
@router.post("")
async def create_campaign(body: CampaignIn, db: DbSession, user: CertAdminUser):
    c = Campaign(
        name=body.name,
        description=body.description,
        review_mode=body.review_mode,
        scope=json.dumps(body.scope),
        deadline=body.deadline,
        created_by_id=user.id,
    )
    db.add(c)
    await db.flush()
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="campaign_created", entity_type="campaign", entity_id=c.id,
                       details={"name": c.name, "review_mode": c.review_mode})
    await db.commit()
    return {"id": c.id, "name": c.name, "status": c.status.value}
@router.get("/{campaign_id}")
async def get_campaign(campaign_id: int, db: DbSession, user: AnyUser):
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    pending = (await db.execute(
        select(func.count()).select_from(Review)
        .where(Review.campaign_id == campaign_id,
               Review.status == ReviewStatus.PENDING)
    )).scalar_one()
    done = (await db.execute(
        select(func.count()).select_from(Review)
        .where(Review.campaign_id == campaign_id,
               Review.status.in_((ReviewStatus.APPROVED, ReviewStatus.REVOKED)))
    )).scalar_one()
    return {
        "id": c.id, "name": c.name, "description": c.description,
        "status": c.status.value, "review_mode": c.review_mode,
        "scope": json.loads(c.scope or "{}"),
        "deadline": c.deadline.isoformat() if c.deadline else None,
        "total_reviews": pending + done,
        "completed_reviews": done,
    }
@router.put("/{campaign_id}")
async def update_campaign(campaign_id: int, body: CampaignIn, db: DbSession, user: CertAdminUser):
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    if c.status not in (CampaignStatus.DRAFT, CampaignStatus.STAGED):
        raise HTTPException(409, "Only draft or staged campaigns can be edited")
    c.name = body.name
    c.description = body.description
    c.review_mode = body.review_mode
    c.scope = json.dumps(body.scope)
    c.deadline = body.deadline
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="campaign_updated", entity_type="campaign", entity_id=campaign_id,
                       details={"name": c.name})
    await db.commit()
    return {"ok": True}
@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int, db: DbSession, user: CertAdminUser):
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    if c.status == CampaignStatus.ACTIVE:
        raise HTTPException(409, "Cancel the campaign before deleting it")
    name = c.name
    await db.delete(c)
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="campaign_deleted", entity_type="campaign", entity_id=campaign_id,
                       details={"name": name})
    await db.commit()
    return {"ok": True}
@router.post("/{campaign_id}/preview")
async def preview_campaign(campaign_id: int, db: DbSession, user: CertAdminUser):
    """Dry-run: scope resolution + reviewer resolution, nothing written."""
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    scope = json.loads(c.scope or "{}")
    accounts = await _scoped_accounts(db, scope)
    owners = await _source_owners(db, accounts)
    account_by_id = {a.id: a for a in accounts}
    included, skipped = [], []
    for a in accounts:
        if c.review_mode == "source_owner":
            reviewer = owners.get(a.data_source_id)
            if reviewer is None:
                skipped.append({"account_id": a.id, "account_value": a.account_value,
                                "reason": "source has no owner with a login"})
                continue
            included.append({"account_id": a.id, "reviewer": reviewer.identity.username})
        else:
            if a.identity_id is None:
                skipped.append({"account_id": a.id, "account_value": a.account_value,
                                "reason": "unlinked account has no manager"})
                continue
            ident = await db.get(Identity, a.identity_id)
            if ident is None or ident.manager_id is None:
                skipped.append({"account_id": a.id, "account_value": a.account_value,
                                "reason": "identity has no manager"})
                continue
            mgr = (await db.execute(
                select(User).where(User.identity_id == ident.manager_id)
            )).scalars().first()
            if mgr is None:
                skipped.append({"account_id": a.id, "account_value": a.account_value,
                                "reason": "manager has no login; falls back to creator"})
                included.append({"account_id": a.id, "reviewer": "fallback:creator"})
                continue
            included.append({"account_id": a.id, "reviewer": mgr.identity.username})
    sod = await violations_for_identities(
        db, {a.identity_id for a in accounts if a.identity_id}
    )
    violating_identities = set(sod)
    for item in included:
        a = account_by_id.get(item["account_id"])
        if a is not None and a.identity_id in violating_identities:
            item["sod_violations"] = sod[a.identity_id]
    return {"total_in_scope": len(accounts), "will_create": len(included),
            "skipped": skipped[:100], "sample": included[:50],
            "sod": {"identities_flagged": len(violating_identities),
                    "accounts_flagged": sum(1 for i in included
                                            if i.get("sod_violations"))}}
@router.post("/{campaign_id}/stage")
async def stage_campaign(campaign_id: int, db: DbSession, user: CertAdminUser):
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    if c.status != CampaignStatus.DRAFT:
        raise HTTPException(409, "Only draft campaigns can be staged")
    c.status = CampaignStatus.STAGED
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="campaign_staged", entity_type="campaign", entity_id=campaign_id)
    await db.commit()
    return {"ok": True, "status": c.status.value}
@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: int, db: DbSession, user: CertAdminUser):
    """Generate reviews. Re-start clears existing reviews and regenerates."""
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    if c.status not in (CampaignStatus.STAGED, CampaignStatus.ACTIVE):
        raise HTTPException(409, "Campaign must be staged before start")
    # Re-start = regenerate: clear prior reviews (outbox rows cascade via FK).
    await db.execute(delete(Review).where(Review.campaign_id == campaign_id))
    scope = json.loads(c.scope or "{}")
    accounts = await _scoped_accounts(db, scope)
    owners = await _source_owners(db, accounts)
    manager_user = {}
    reviewer_fallback = user
    created, skipped = 0, 0
    new_reviews: list[tuple[Review, User]] = []
    for a in accounts:
        reviewer = None
        if c.review_mode == "source_owner":
            reviewer = owners.get(a.data_source_id)
            if reviewer is None:
                skipped += 1
                continue
        else:
            if a.identity_id is None:
                skipped += 1
                continue
            ident = await db.get(Identity, a.identity_id)
            if ident is None or ident.manager_id is None:
                reviewer = reviewer_fallback
            else:
                mid = ident.manager_id
                if mid not in manager_user:
                    manager_user[mid] = (
                        await db.execute(select(User).where(User.identity_id == mid))
                    ).scalars().first()
                reviewer = manager_user[mid] or reviewer_fallback
        review = Review(campaign_id=campaign_id, account_id=a.id, reviewer_id=reviewer.id)
        db.add(review)
        new_reviews.append((review, reviewer))
        created += 1
    await db.flush()  # reviews need PKs before the outbox rows reference them
    c.status = CampaignStatus.ACTIVE
    settings = get_settings()
    due = utcnow() + timedelta(minutes=settings.reminder_delay_minutes)
    # Render at enqueue: a template failure is a 400 here, not a dead email later
    try:
        rendered = [
            render_email("review_reminder",
                         first_name=(rev.identity.first_name if rev.identity else "") or "reviewer",
                         campaign_name=c.name,
                         review_url=build_review_url(campaign_id))
            for r, rev in new_reviews
        ]
    except TemplateRenderError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.add_all([
        EmailOutbox(
            campaign_id=campaign_id,
            review_id=r.id,
            reviewer_id=r.reviewer_id,
            recipient=rev.identity.email if rev.identity else None,
            subject=subject,
            body=body,
            due_at=due,
            status=OutboxStatus.PENDING,
        )
        for (r, rev), (subject, body) in zip(new_reviews, rendered)
    ])
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="campaign_started", entity_type="campaign", entity_id=campaign_id,
                       details={"reviews_created": created, "skipped": skipped,
                                "reminders_enqueued": len(new_reviews)})
    await db.commit()
    return {"reviews_created": created, "skipped": skipped}
@router.post("/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: int, db: DbSession, user: CertAdminUser):
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    if c.status not in (CampaignStatus.STAGED, CampaignStatus.ACTIVE):
        raise HTTPException(409, "Only staged or active campaigns can be cancelled")
    c.status = CampaignStatus.CANCELLED
    cancelled = (await db.execute(
        update(EmailOutbox)
        .where(EmailOutbox.campaign_id == campaign_id,
               EmailOutbox.status == OutboxStatus.PENDING)
        .values(status=OutboxStatus.CANCELLED)
    )).rowcount
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="campaign_cancelled", entity_type="campaign", entity_id=campaign_id,
                       details={"reminders_cancelled": cancelled})
    await db.commit()
    return {"ok": True, "status": c.status.value}
@router.get("/{campaign_id}/metrics")
async def campaign_metrics(campaign_id: int, db: DbSession, user: AnyUser):
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    by_status = dict(
        (await db.execute(
            select(Review.status, func.count())
            .where(Review.campaign_id == campaign_id)
            .group_by(Review.status)
        )).all()
    )
    by_status = {k.value: v for k, v in by_status.items()}
    total = sum(by_status.values())
    done = by_status.get("approved", 0) + by_status.get("revoked", 0)
    return {
        "campaign_id": campaign_id,
        "status": c.status.value,
        "by_status": by_status,
        "total": total,
        "completed": done,
        "progress_pct": round(100 * done / total, 1) if total else 0.0,
    }


@router.get("/{campaign_id}/report")
async def campaign_report(campaign_id: int, db: DbSession, user: ReportViewer):
    """Executive report JSON: header, completion, decisions, reviewer
    workload, revocation detail, risk block (spec Part 2)."""
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    rows = (
        await db.execute(
            select(Review)
            .where(Review.campaign_id == campaign_id)
            .order_by(Review.id)
        )
    ).scalars().all()
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
    total = len(rows)
    done = by_status.get("approved", 0) + by_status.get("revoked", 0)
    # --- reviewer workload: one row per reviewer, sorted pending desc ---
    reviewer_ids = {r.reviewer_id for r in rows}
    reviewer_names: dict[int, str] = {}
    if reviewer_ids:
        found = (
            await db.execute(
                select(User.id, Identity.first_name, Identity.last_name)
                .join(Identity, User.identity_id == Identity.id)
                .where(User.id.in_(reviewer_ids))
            )
        ).all()
        reviewer_names = {uid: " ".join(x for x in (fn, ln) if x) for uid, fn, ln in found}
    workload = {}
    for r in rows:
        w = workload.setdefault(
            r.reviewer_id,
            {"reviewer": reviewer_names.get(r.reviewer_id) or f"user:{r.reviewer_id}",
             "assigned": 0, "approved": 0, "revoked": 0, "pending": 0},
        )
        w["assigned"] += 1
        if r.status == ReviewStatus.APPROVED:
            w["approved"] += 1
        elif r.status == ReviewStatus.REVOKED:
            w["revoked"] += 1
        else:
            w["pending"] += 1
    workload_rows = sorted(workload.values(), key=lambda w: -w["pending"])
    # --- revocations detail: comment is mandatory so always meaningful ---
    account_ids = {r.account_id for r in rows}
    acct_rows = (
        await db.execute(
            select(Account, Entitlement.name, DataSource.name)
            .join(Entitlement, Account.entitlement_id == Entitlement.id, isouter=True)
            .join(DataSource, Account.data_source_id == DataSource.id, isouter=True)
            .where(Account.id.in_(account_ids))
        )
    ).all() if account_ids else []
    acct_by_id = {a.id: (a, ename, sname) for a, ename, sname in acct_rows}
    ident_ids = {a.identity_id for a, _, _ in acct_rows if a.identity_id is not None}
    ident_names: dict[int, dict] = {}
    if ident_ids:
        found_i = (
            await db.execute(
                select(Identity.id, Identity.first_name, Identity.last_name,
                       Identity.employee_id)
                .where(Identity.id.in_(ident_ids))
            )
        ).all()
        ident_names = {
            i: {"name": " ".join(x for x in (fn, ln) if x) or None, "employee_id": eid}
            for i, fn, ln, eid in found_i
        }
    revocations = []
    for r in rows:
        if r.status != ReviewStatus.REVOKED:
            continue
        a, ename, sname = acct_by_id.get(r.account_id, (None, None, None))
        ident = ident_names.get(a.identity_id, {}) if a else {}
        revocations.append({
            "identity": ident.get("name"),
            "employee_id": ident.get("employee_id"),
            "account": a.account_value if a else None,
            "entitlement": ename,
            "source": sname,
            "decided_at": r.completed_at.isoformat() if r.completed_at else None,
            "reviewer": reviewer_names.get(r.reviewer_id),
            "comment": r.comments,
        })
    # --- risk block: band distribution of reviewed identities (latest run) ---
    latest_run = (
        await db.execute(
            select(RiskSnapshot.run_id).order_by(RiskSnapshot.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    risk_block = None
    if latest_run is not None:
        risk_ids = {a.identity_id for a, _, _ in acct_rows if a.identity_id is not None}
        snap_rows = (
            await db.execute(
                select(RiskSnapshot.identity_id, RiskSnapshot.band)
                .where(RiskSnapshot.run_id == latest_run,
                       RiskSnapshot.identity_id.in_(risk_ids))
            )
        ).all() if risk_ids else []
        dist: dict[str, int] = {}
        for _, band in snap_rows:
            dist[band] = dist.get(band, 0) + 1
        risk_block = {
            "run_id": latest_run,
            "scored_in_campaign": len(snap_rows),
            "band_distribution": dist,
        }
    return {
        "campaign": {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "status": c.status.value,
            "review_mode": c.review_mode,
            "deadline": c.deadline.isoformat() if c.deadline else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        },
        "generated_at": utcnow().isoformat(),
        "completion": {
            "total": total,
            "completed": done,
            "pending": by_status.get("pending", 0) + by_status.get("in_progress", 0),
            "progress_pct": round(100 * done / total, 1) if total else 0.0,
        },
        "decisions": by_status,
        "reviewer_workload": workload_rows,
        "revocations": revocations,
        "risk": risk_block,
    }


@router.get("/{campaign_id}/report.csv")
async def campaign_report_csv(campaign_id: int, db: DbSession, user: ReportViewer):
    """Streamed decision rows (house pattern; no files on replicas)."""
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    rows = (
        await db.execute(
            select(Review)
            .where(Review.campaign_id == campaign_id)
            .order_by(Review.id)
        )
    ).scalars().all()
    account_ids = {r.account_id for r in rows}
    acct_rows = (
        await db.execute(
            select(Account, Entitlement.name, DataSource.name)
            .join(Entitlement, Account.entitlement_id == Entitlement.id, isouter=True)
            .join(DataSource, Account.data_source_id == DataSource.id, isouter=True)
            .where(Account.id.in_(account_ids))
        )
    ).all() if account_ids else []
    acct_by_id = {a.id: (a, ename, sname) for a, ename, sname in acct_rows}
    ident_ids = {a.identity_id for a, _, _ in acct_rows if a.identity_id is not None}
    ident_names: dict[int, tuple[str, str]] = {}
    if ident_ids:
        found_i = (
            await db.execute(
                select(
                    Identity.id, Identity.first_name, Identity.last_name,
                    Identity.employee_id,
                ).where(Identity.id.in_(ident_ids))
            )
        ).all()
        ident_names = {
            i: (" ".join(x for x in (fn, ln) if x) or "", eid)
            for i, fn, ln, eid in found_i
        }
    reviewer_ids = {r.reviewer_id for r in rows}
    reviewer_names: dict[int, str] = {}
    if reviewer_ids:
        found = (
            await db.execute(
                select(User.id, Identity.first_name, Identity.last_name)
                .join(Identity, User.identity_id == Identity.id)
                .where(User.id.in_(reviewer_ids))
            )
        ).all()
        reviewer_names = {uid: " ".join(x for x in (fn, ln) if x) for uid, fn, ln in found}
    header = ["identity", "employee_id", "source", "entitlement", "account",
              "privilege", "reviewer", "decision", "decided_at", "comment"]
    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        yield buf.getvalue()
        for r in rows:
            a, ename, sname = acct_by_id.get(r.account_id, (None, None, None))
            ident = ident_names.get(a.identity_id, ("", "")) if a else ("", "")
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([
                ident[0], ident[1], sname or "", ename or "",
                a.account_value if a else "", a.privilege_level if a else "",
                reviewer_names.get(r.reviewer_id, ""),
                r.status.value, r.completed_at.isoformat() if r.completed_at else "",
                r.comments or "",
            ])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv")
