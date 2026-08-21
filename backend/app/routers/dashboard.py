"""Dashboard router: portfolio stats + personal workload."""
from __future__ import annotations
from fastapi import APIRouter
from sqlalchemy import func, select
from app.models.campaign import Campaign, CampaignStatus, Review, ReviewStatus
from app.models.identity import Identity
from app.models.source import Account
from app.routers.deps import AnyUser, DbSession, Principal
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
@router.get("")
async def dashboard(db: DbSession, user: AnyUser):
    identities = (
        await db.execute(
            select(func.count()).select_from(Identity).where(Identity.is_active == True)  # noqa: E712
        )
    ).scalar_one()
    accounts = (
        await db.execute(select(func.count()).select_from(Account))
    ).scalar_one()
    unlinked = (
        await db.execute(
            select(func.count()).select_from(Account).where(Account.identity_id.is_(None))
        )
    ).scalar_one()
    privileged = (
        await db.execute(
            select(func.count()).select_from(Account)
            .where(Account.privilege_level.in_(("high", "very_high")))
        )
    ).scalar_one()
    active_campaigns = (
        await db.execute(
            select(func.count()).select_from(Campaign)
            .where(Campaign.status == CampaignStatus.ACTIVE)
        )
    ).scalar_one()
    # D4 mixed payload: an API key gets real portfolio numbers and a
    # zeroed personal block with an explicit principal flag, not a 403.
    if getattr(user, "is_api_key", False):
        return {
            "identities": identities,
            "accounts": accounts,
            "unlinked_accounts": unlinked,
            "privileged_accounts": privileged,
            "active_campaigns": active_campaigns,
            "my_pending_reviews": 0,
            "principal": "api_key",
        }
    my_pending = (
        await db.execute(
            select(func.count()).select_from(Review)
            .where(Review.reviewer_id == user.id,
                   Review.status.in_((ReviewStatus.PENDING, ReviewStatus.IN_PROGRESS)))
        )
    ).scalar_one()
    return {
        "identities": identities,
        "accounts": accounts,
        "unlinked_accounts": unlinked,
        "privileged_accounts": privileged,
        "active_campaigns": active_campaigns,
        "my_pending_reviews": my_pending,
    }
