"""Review router: my queue, submit decisions, bulk submit, history."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from app.core.audit_service import append_audit
from app.models.campaign import Campaign, CampaignStatus, Review, ReviewStatus
from app.models.identity import Identity, utcnow
from app.models.source import Account
from app.routers.deps import AnyUser, DbSession
router = APIRouter(prefix="/api/reviews", tags=["reviews"])
DECISIONS = {"approve", "revoke"}
class SubmitIn(BaseModel):
    decision: str = Field(pattern="^(approve|revoke)$")
    comments: str | None = None
class BulkSubmitIn(BaseModel):
    review_ids: list[int]
    decision: str = Field(pattern="^(approve|revoke)$")
    comments: str | None = None
@router.get("/queue")
async def my_queue(db: DbSession, user: AnyUser, page: int = 1, page_size: int = 50):
    total = (
        await db.execute(
            select(func.count()).select_from(Review)
            .where(Review.reviewer_id == user.id,
                   Review.status.in_((ReviewStatus.PENDING, ReviewStatus.IN_PROGRESS)))
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(Review, Account, Campaign)
            .join(Account, Review.account_id == Account.id)
            .join(Campaign, Review.campaign_id == Campaign.id)
            .where(Review.reviewer_id == user.id,
                   Review.status.in_((ReviewStatus.PENDING, ReviewStatus.IN_PROGRESS)))
            .order_by(Review.id)
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    items = []
    for r, a, c in rows:
        items.append({
            "id": r.id,
            "campaign_id": c.id, "campaign_name": c.name,
            "account_value": a.account_value,
            "privilege_level": a.privilege_level,
            "status": r.status.value,
        })
    return {"total": total, "page": page, "items": items}
@router.get("/count")
async def my_count(db: DbSession, user: AnyUser):
    n = (
        await db.execute(
            select(func.count()).select_from(Review)
            .where(Review.reviewer_id == user.id,
                   Review.status.in_((ReviewStatus.PENDING, ReviewStatus.IN_PROGRESS)))
        )
    ).scalar_one()
    return {"count": n}
@router.get("/history")
async def my_history(db: DbSession, user: AnyUser, page: int = 1, page_size: int = 50):
    rows = (
        await db.execute(
            select(Review, Account, Campaign)
            .join(Account, Review.account_id == Account.id)
            .join(Campaign, Review.campaign_id == Campaign.id)
            .where(Review.reviewer_id == user.id,
                   Review.status.in_((ReviewStatus.APPROVED, ReviewStatus.REVOKED)))
            .order_by(Review.completed_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    items = []
    for r, a, c in rows:
        items.append({
            "id": r.id,
            "campaign_name": c.name,
            "account_value": a.account_value,
            "decision": r.decision,
            "comments": r.comments,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        })
    return {"items": items}
@router.get("/{review_id}")
async def get_review(review_id: int, db: DbSession, user: AnyUser):
    row = (
        await db.execute(
            select(Review, Account, Campaign)
            .join(Account, Review.account_id == Account.id)
            .join(Campaign, Review.campaign_id == Campaign.id)
            .where(Review.id == review_id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Review not found")
    r, a, c = row
    if r.reviewer_id != user.id and user.role.value not in ("system_admin", "certification_admin", "auditor"):
        raise HTTPException(403, "Not your review")
    ident = await db.get(Identity, a.identity_id) if a.identity_id else None
    return {
        "id": r.id,
        "campaign_id": c.id, "campaign_name": c.name,
        "account_value": a.account_value,
        "account_type": a.account_type,
        "privilege_level": a.privilege_level,
        "identity_employee_id": ident.employee_id if ident else None,
        "identity_name": f"{ident.first_name} {ident.last_name}" if ident else None,
        "status": r.status.value,
        "decision": r.decision,
        "comments": r.comments,
    }
async def _finalize(db, user, review: Review, decision: str, comments: str | None) -> None:
    if review.status in (ReviewStatus.APPROVED, ReviewStatus.REVOKED):
        raise HTTPException(409, "Review already decided")
    if decision == "revoke" and not (comments or "").strip():
        raise HTTPException(400, "Revocation requires a comment")
    review.status = ReviewStatus.APPROVED if decision == "approve" else ReviewStatus.REVOKED
    review.decision = decision
    review.comments = comments
    review.completed_at = utcnow()
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="review_decided", entity_type="review", entity_id=review.id,
                       details={"decision": decision, "campaign_id": review.campaign_id})
async def _maybe_complete(db, user, campaign: Campaign) -> None:
    """Domain rule 6: a campaign completes when every review has a decision."""
    await db.flush()  # counts must see pending decision UPDATEs (autoflush off)
    done = (await db.execute(
        select(func.count()).select_from(Review)
        .where(Review.campaign_id == campaign.id,
               Review.status.in_((ReviewStatus.APPROVED, ReviewStatus.REVOKED)))
    )).scalar_one()
    total = (await db.execute(
        select(func.count()).select_from(Review)
        .where(Review.campaign_id == campaign.id)
    )).scalar_one()
    if total > 0 and done == total:
        campaign.status = CampaignStatus.COMPLETED
        await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                           action="campaign_completed", entity_type="campaign",
                           entity_id=campaign.id)
@router.post("/{review_id}/submit")
async def submit_review(review_id: int, body: SubmitIn, db: DbSession, user: AnyUser):
    review = await db.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "Review not found")
    if review.reviewer_id != user.id:
        raise HTTPException(403, "Not your review")
    campaign = await db.get(Campaign, review.campaign_id)
    if campaign is None or campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(409, "Campaign is not active")
    await _finalize(db, user, review, body.decision, body.comments)
    await _maybe_complete(db, user, campaign)
    await db.commit()
    return {"ok": True}
@router.post("/bulk-submit")
async def bulk_submit(body: BulkSubmitIn, db: DbSession, user: AnyUser):
    submitted = 0
    campaigns = {}
    for rid in body.review_ids:
        review = await db.get(Review, rid)
        if review is None or review.reviewer_id != user.id:
            continue
        campaign = await db.get(Campaign, review.campaign_id)
        if campaign is None or campaign.status != CampaignStatus.ACTIVE:
            continue
        await _finalize(db, user, review, body.decision, body.comments)
        campaigns[campaign.id] = campaign
        submitted += 1
    for c in campaigns.values():
        await _maybe_complete(db, user, c)
    await db.commit()
    return {"submitted": submitted}
