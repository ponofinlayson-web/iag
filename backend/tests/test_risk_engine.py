"""Risk engine: pure 7-signal scoring against hand-built fixtures."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.risk_engine import SIGNAL_WEIGHTS, band_of, score_identities
from app.db import Base, build_engine
from app.models.campaign import Campaign, CampaignStatus, Review, ReviewStatus
from app.models.entitlement import Entitlement
from app.models.identity import Identity, utcnow
from app.models.sod import SodRule
from app.models.source import Account, DataSource, SourceType
from app.models.user import Role, User


@pytest.fixture()
async def db():
    engine = build_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _ident(db, n=1, manager=None, active=True):
    ident = Identity(employee_id=f"E-{n}", is_active=active, manager_id=manager)
    db.add(ident)
    await db.flush()
    return ident


async def _source(db, n=1):
    src = DataSource(name=f"src{n}", source_type=SourceType.CSV)
    db.add(src)
    await db.flush()
    return src


async def _ent(db, source, n):
    e = Entitlement(data_source_id=source.id, catalog_id=f"ENT-{n:05d}", name=f"ent{n}")
    db.add(e)
    await db.flush()
    return e


async def _account(db, source, ident, privilege=None, ent=None, created=None, n=1):
    acc = Account(
        data_source_id=source.id,
        identity_id=ident.id,
        account_value=f"acc{n}",
        privilege_level=privilege,
        entitlement_id=ent.id if ent else None,
        created_at=created or utcnow(),
    )
    db.add(acc)
    await db.flush()
    return acc


async def _reviewer(db):
    ident = Identity(employee_id="E-REVIEWER")
    db.add(ident)
    await db.flush()
    u = User(identity_id=ident.id, role=Role.REVIEWER)
    db.add(u)
    await db.flush()
    return u


async def _decide(db, acc, reviewer_id, days_ago, status=ReviewStatus.APPROVED, n=1):
    camp = Campaign(name=f"camp{n}", status=CampaignStatus.COMPLETED)
    db.add(camp)
    await db.flush()
    r = Review(
        campaign_id=camp.id,
        account_id=acc.id,
        reviewer_id=reviewer_id,
        status=status,
        decision="approve" if status == ReviewStatus.APPROVED else "revoke",
        completed_at=utcnow() - timedelta(days=days_ago),
    )
    db.add(r)
    await db.flush()
    return r


async def _score(db, ident):
    out = await score_identities(db, [ident.id], unreviewed_days=90)
    return out[ident.id]


def test_weights_sum_to_100():
    assert sum(SIGNAL_WEIGHTS.values()) == 100
    assert len(SIGNAL_WEIGHTS) == 7


def test_bands():
    assert band_of(0) == "low"
    assert band_of(24.9) == "low"
    assert band_of(25) == "medium"
    assert band_of(49.9) == "medium"
    assert band_of(50) == "high"
    assert band_of(74.9) == "high"
    assert band_of(75) == "critical"
    assert band_of(100) == "critical"


async def test_empty_input_returns_empty(db):
    assert await score_identities(db, []) == {}


async def test_identity_with_no_accounts_scores_zero(db):
    ident = await _ident(db)
    s = await _score(db, ident)
    assert s.score == 0.0
    assert s.band == "low"
    assert all(v == 0.0 for v in s.signals.values())
    assert len(s.factors) == 7
    assert s.employee_id == "E-1"


async def test_unreviewed_access_fraction(db):
    ident = await _ident(db)
    src = await _source(db)
    reviewer = await _reviewer(db)
    a1 = await _account(db, src, ident, n=1)
    a2 = await _account(db, src, ident, n=2)
    a3 = await _account(db, src, ident, n=3)
    a4 = await _account(db, src, ident, n=4)
    # two of four decided 10 days ago (fresh), one decided 200 days ago
    # (stale decision = still "reviewed" recency-wise? NO: outside window)
    await _decide(db, a1, reviewer.id, days_ago=10, n=1)
    await _decide(db, a2, reviewer.id, days_ago=10, n=2)
    await _decide(db, a3, reviewer.id, days_ago=200, n=3)
    s = await _score(db, ident)
    # only a1/a2 are reviewed within 90d -> 2 unreviewed of 4 = half
    assert s.signals["unreviewed_access"] == 10.0  # half of 20
    f = [f for f in s.factors if f["signal"] == "unreviewed_access"][0]
    assert f["raw"] == 2 and f["raw_total"] == 4


async def test_unreviewed_access_revoked_counts_as_reviewed(db):
    ident = await _ident(db)
    src = await _source(db)
    reviewer = await _reviewer(db)
    a1 = await _account(db, src, ident, n=1)
    await _decide(db, a1, reviewer.id, days_ago=5, status=ReviewStatus.REVOKED, n=1)
    s = await _score(db, ident)
    assert s.signals["unreviewed_access"] == 0.0


async def test_privileged_access_counts_and_doubles(db):
    ident = await _ident(db)
    src = await _source(db)
    for i in range(1, 11):
        await _account(db, src, ident, privilege="high", n=i)
    s = await _score(db, ident)
    assert s.signals["privileged_access"] == 20.0  # 10/10 = cap
    ident2 = await _ident(db, n=2)
    for i in range(1, 6):
        await _account(db, src, ident2, privilege="very_high", n=10 + i)
    s2 = await _score(db, ident2)
    assert s2.signals["privileged_access"] == 20.0  # 5*2=10 weighted = cap


async def test_sod_violations_scale(db):
    ident = await _ident(db)
    src = await _source(db)
    e1 = await _ent(db, src, 1)
    e2 = await _ent(db, src, 2)
    for i in (1, 2):
        await _account(db, src, ident, ent=e1 if i == 1 else e2, n=i)
    db.add(SodRule(name="R1", entitlement_a_id=e1.id, entitlement_b_id=e2.id))
    await db.flush()
    s = await _score(db, ident)
    assert s.signals["sod_violations"] == round(1 / 3 * 20, 1)


async def test_privilege_creep_fraction(db):
    ident = await _ident(db)
    src = await _source(db)
    await _account(db, src, ident, created=utcnow() - timedelta(days=200), n=1)
    await _account(db, src, ident, created=utcnow() - timedelta(days=5), n=2)
    s = await _score(db, ident)
    assert s.signals["privilege_creep"] == 5.0  # half of 10


async def test_orphaned_and_stale_binary_signals(db):
    # orphan: accounts but no manager; also inactive = stale too
    ident = await _ident(db, manager=None, active=False)
    src = await _source(db)
    await _account(db, src, ident, n=1)
    s = await _score(db, ident)
    assert s.signals["orphaned_access"] == 10.0
    assert s.signals["stale_identity"] == 10.0
    # managed + active: both zero
    boss = await _ident(db, n=2)
    ok = await _ident(db, n=3, manager=boss.id, active=True)
    await _account(db, src, ok, n=9)
    s2 = await _score(db, ok)
    assert s2.signals["orphaned_access"] == 0.0
    assert s2.signals["stale_identity"] == 0.0
    # inactive with NO accounts: stale stays 0 (spec: "while holding")
    ghost = await _ident(db, n=4, active=False)
    s3 = await _score(db, ghost)
    assert s3.signals["stale_identity"] == 0.0


async def test_source_concentration(db):
    ident = await _ident(db)
    src = await _source(db)
    other = await _source(db, n=2)
    for i in range(1, 21):
        await _account(db, src, ident, n=i)
    await _account(db, other, ident, n=100)
    s = await _score(db, ident)
    # max concentration = 20 on src -> capped at full 10
    assert s.signals["source_concentration"] == 10.0


async def test_all_signals_maxed_hits_100(db):
    # Every signal caps at its weight, so the raw sum maxes at exactly
    # 100; the engine clamp is belt-and-braces. Max out all seven.
    ident = await _ident(db, manager=None, active=False)
    src = await _source(db)
    ents = [await _ent(db, src, i) for i in range(1, 9)]
    rules = [(1, 2), (3, 4), (5, 6), (7, 8)]
    for a, b in rules:
        db.add(SodRule(name=f"R-{a}", entitlement_a_id=ents[a - 1].id, entitlement_b_id=ents[b - 1].id))
    for i in range(1, 25):  # 24 accounts, one source, all very_high, all fresh
        await _account(
            db, src, ident, privilege="very_high",
            ent=ents[(i - 1) % 8], n=i,
        )
    await db.flush()
    s = await _score(db, ident)
    assert s.signals["unreviewed_access"] == 20.0  # no reviews at all
    assert s.signals["privileged_access"] == 20.0  # 48 weighted, capped
    assert s.signals["sod_violations"] == 20.0  # 4 violations, capped
    assert s.signals["privilege_creep"] == 10.0
    assert s.signals["orphaned_access"] == 10.0
    assert s.signals["stale_identity"] == 10.0
    assert s.signals["source_concentration"] == 10.0  # 24/20, capped
    assert s.score == 100.0
    assert s.band == "critical"
