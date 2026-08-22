"""Risk engine: transparent 7-signal scoring over governed data.

Pure read-side computation (sod_engine shape): score_identities(db, ids)
never writes; the router persists snapshot rows in one transaction per
run. Weights are fixed constants (spec D3) - transparency is the point:
every factor row carries raw counts so an auditor can recompute any
score by hand.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from app.core.sod_engine import violations_for_identities
from app.models.campaign import Review, ReviewStatus
from app.models.identity import Identity, utcnow
from app.models.source import Account, DataSource

SIGNAL_WEIGHTS = {
    "unreviewed_access": 20,
    "privileged_access": 20,
    "sod_violations": 20,
    "privilege_creep": 10,
    "orphaned_access": 10,
    "stale_identity": 10,
    "source_concentration": 10,
}
CREEP_DAYS = 30
PRIVILEGE_DIVISOR = 10  # 10 weighted privileged accounts = full signal
SOD_DIVISOR = 3  # 3 open violations = full signal
CONCENTRATION_DIVISOR = 20  # 20 accounts on one source = full signal
PRIVILEGED_LEVELS = {"high", "very_high"}


def band_of(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


@dataclass
class ScoredIdentity:
    identity_id: int
    employee_id: str
    score: float
    band: str
    signals: dict[str, float]
    factors: list[dict]


def _factor(signal: str, raw, raw_total, points: float, detail: str) -> dict:
    return {
        "signal": signal,
        "weight": SIGNAL_WEIGHTS[signal],
        "raw": raw,
        "raw_total": raw_total,
        "contribution": round(points, 1),
        "detail": detail,
    }


def _cap(points: float, weight: int) -> float:
    return min(points, float(weight))


async def score_identities(
    db, identity_ids, *, unreviewed_days: int | None = None
) -> dict[int, ScoredIdentity]:
    """Score each requested identity; returns {} for empty input.
    Reads only: basis tables + sod_engine. No writes, no commits."""
    ids = set(identity_ids)
    if not ids:
        return {}
    if unreviewed_days is None:
        from app.core.settings import Settings

        unreviewed_days = Settings().risk_unreviewed_days
    now = utcnow()
    reviewed_cutoff = now - timedelta(days=unreviewed_days)
    creep_cutoff = now - timedelta(days=CREEP_DAYS)

    identities = (
        (
            await db.execute(
                select(
                    Identity.id,
                    Identity.employee_id,
                    Identity.is_active,
                    Identity.manager_id,
                ).where(Identity.id.in_(ids))
            )
        )
        .all()
    )
    if not identities:
        return {}

    account_rows = (
        await db.execute(
            select(
                Account.id,
                Account.identity_id,
                Account.data_source_id,
                Account.privilege_level,
                Account.created_at,
            ).where(Account.identity_id.in_(ids))
        )
    ).all()
    accounts_by_ident: dict[int, list] = {}
    account_ids = set()
    for row in account_rows:
        accounts_by_ident.setdefault(row.identity_id, []).append(row)
        account_ids.add(row.id)

    reviewed_account_ids: set[int] = set()
    if account_ids:
        reviewed = (
            await db.execute(
                select(Review.account_id)
                .where(
                    Review.account_id.in_(account_ids),
                    Review.completed_at.is_not(None),
                    Review.completed_at >= reviewed_cutoff,
                    Review.status.in_((ReviewStatus.APPROVED, ReviewStatus.REVOKED)),
                )
                .distinct()
            )
        ).all()
        reviewed_account_ids = {r[0] for r in reviewed}

    source_names: dict[int, str] = {}
    needed_sources = {r.data_source_id for r in account_rows}
    if needed_sources:
        for sid, name in (
            await db.execute(
                select(DataSource.id, DataSource.name).where(
                    DataSource.id.in_(needed_sources)
                )
            )
        ).all():
            source_names[sid] = name

    sod = await violations_for_identities(db, ids)

    out: dict[int, ScoredIdentity] = {}
    for ident in identities:
        out[ident.id] = _score_one(
            ident, accounts_by_ident.get(ident.id, []), reviewed_account_ids,
            sod.get(ident.id, []), source_names, creep_cutoff, unreviewed_days,
        )
    return out


def _score_one(
    ident, accounts, reviewed_account_ids, sod_violations, source_names,
    creep_cutoff, unreviewed_days,
) -> ScoredIdentity:
    total = len(accounts)
    signals: dict[str, float] = {}
    factors: list[dict] = []

    unreviewed = sum(1 for a in accounts if a.id not in reviewed_account_ids)
    pts = (unreviewed / total) * SIGNAL_WEIGHTS["unreviewed_access"] if total else 0.0
    signals["unreviewed_access"] = round(pts, 1)
    factors.append(_factor(
        "unreviewed_access", unreviewed, total, pts,
        f"{unreviewed} of {total} accounts without a review decision "
        f"in the last {unreviewed_days} days" if total else "no linked accounts",
    ))

    n_high = sum(1 for a in accounts if a.privilege_level == "high")
    n_vhigh = sum(1 for a in accounts if a.privilege_level == "very_high")
    weighted = n_high + 2 * n_vhigh
    pts = min(weighted / PRIVILEGE_DIVISOR, 1.0) * SIGNAL_WEIGHTS["privileged_access"]
    signals["privileged_access"] = round(pts, 1)
    factors.append(_factor(
        "privileged_access", weighted, total, pts,
        f"{n_high} high + {n_vhigh} very_high accounts "
        f"(very_high double-weighted, {weighted} weighted)",
    ))

    n_sod = len(sod_violations)
    pts = min(n_sod / SOD_DIVISOR, 1.0) * SIGNAL_WEIGHTS["sod_violations"]
    signals["sod_violations"] = round(pts, 1)
    rule_names = ", ".join(v["rule_name"] for v in sod_violations[:3])
    factors.append(_factor(
        "sod_violations", n_sod, None, pts,
        f"{n_sod} open SoD violations" + (f" ({rule_names})" if rule_names else ""),
    ))

    fresh = sum(1 for a in accounts if a.created_at and a.created_at >= creep_cutoff)
    pts = (fresh / total) * SIGNAL_WEIGHTS["privilege_creep"] if total else 0.0
    signals["privilege_creep"] = round(pts, 1)
    factors.append(_factor(
        "privilege_creep", fresh, total, pts,
        f"{fresh} of {total} accounts created in the last {CREEP_DAYS} days"
        if total else "no linked accounts",
    ))

    orphaned = total > 0 and ident.manager_id is None
    pts = SIGNAL_WEIGHTS["orphaned_access"] if orphaned else 0.0
    signals["orphaned_access"] = pts
    factors.append(_factor(
        "orphaned_access", 1 if orphaned else 0, 1, pts,
        "holds accounts but has no manager" if orphaned
        else "manager set" if total else "no linked accounts",
    ))

    stale = not ident.is_active and total > 0
    pts = SIGNAL_WEIGHTS["stale_identity"] if stale else 0.0
    signals["stale_identity"] = pts
    factors.append(_factor(
        "stale_identity", 1 if stale else 0, 1, pts,
        "identity inactive while still holding accounts" if stale
        else "identity active or holds no accounts",
    ))

    per_source: dict[int, int] = {}
    for a in accounts:
        per_source[a.data_source_id] = per_source.get(a.data_source_id, 0) + 1
    if per_source:
        top_source, top_count = max(per_source.items(), key=lambda kv: kv[1])
        pts = min(top_count / CONCENTRATION_DIVISOR, 1.0) * SIGNAL_WEIGHTS["source_concentration"]
        top_name = source_names.get(top_source, f"source#{top_source}")
    else:
        top_source, top_count, pts, top_name = None, 0, 0.0, None
    signals["source_concentration"] = round(pts, 1)
    factors.append(_factor(
        "source_concentration", top_count, total, pts,
        f"{top_count} of {total} accounts on one source ({top_name})"
        if per_source else "no linked accounts",
    ))

    score = round(min(sum(signals.values()), 100.0), 1)
    return ScoredIdentity(
        identity_id=ident.id,
        employee_id=ident.employee_id,
        score=score,
        band=band_of(score),
        signals=signals,
        factors=factors,
    )
