"""Risk router: explicit run trigger + snapshot reads (spec Part 1).

POST /runs is the only write; one transaction persists the run's
snapshot rows and the risk_run_completed audit entry together. Reads
serve the latest run by default (D4); run_id reaches history.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.core.audit_service import append_audit
from app.core.risk_engine import score_identities
from app.models.identity import Identity, utcnow
from app.models.risk import RiskSnapshot
from app.routers.deps import CertAdminUser, DbSession, ReportViewer

router = APIRouter(prefix="/api/risk", tags=["risk"])


async def _identity_names(db, rows) -> dict[int, dict]:
    ids = {r.identity_id for r in rows if r.identity_id is not None}
    if not ids:
        return {}
    found = (
        await db.execute(
            select(
                Identity.id,
                Identity.first_name,
                Identity.last_name,
                Identity.department,
            ).where(Identity.id.in_(ids))
        )
    ).all()
    return {
        f.id: {
            "name": " ".join(x for x in (f.first_name, f.last_name) if x) or None,
            "department": f.department,
        }
        for f in found
    }


async def _latest_run_id(db) -> str | None:
    return (
        await db.execute(select(RiskSnapshot.run_id).order_by(RiskSnapshot.id.desc()).limit(1))
    ).scalar_one_or_none()


@router.post("/runs", status_code=202)
async def run_risk(db: DbSession, user: CertAdminUser):
    run_id = uuid.uuid4().hex
    active_ids = (
        await db.execute(select(Identity.id).where(Identity.is_active.is_(True)))
    ).scalars().all()
    scored = await score_identities(db, active_ids)
    distribution: dict[str, int] = {}
    for s in scored.values():
        db.add(
            RiskSnapshot(
                run_id=run_id,
                identity_id=s.identity_id,
                identity_employee_id=s.employee_id,
                score=s.score,
                band=s.band,
                signals=json.dumps(s.signals, sort_keys=True),
                factors=json.dumps(s.factors),
                computed_at=utcnow(),
            )
        )
        distribution[s.band] = distribution.get(s.band, 0) + 1
    average = (
        round(sum(s.score for s in scored.values()) / len(scored), 1) if scored else 0.0
    )
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=user.identity.username or "",
        action="risk_run_completed",
        entity_type="risk_run",
        entity_id=None,
        details={
            "run_id": run_id,
            "scored": len(scored),
            "average_score": average,
            "band_distribution": distribution,
        },
    )
    await db.commit()
    return {
        "run_id": run_id,
        "scored_identities": len(scored),
        "average_score": average,
        "band_distribution": distribution,
    }


@router.get("/snapshots")
async def list_snapshots(
    db: DbSession,
    user: ReportViewer,
    run_id: str = "",
    band: str = "",
    department: str = "",
    page: int = 1,
    page_size: int = 50,
):
    effective_run = run_id or await _latest_run_id(db)
    if effective_run is None:
        return {"run_id": None, "total": 0, "page": page, "items": []}
    crit = [RiskSnapshot.run_id == effective_run]
    if band:
        crit.append(RiskSnapshot.band == band)
    if department:
        crit.append(
            RiskSnapshot.identity_id.in_(
                select(Identity.id).where(Identity.department == department)
            )
        )
    q = select(RiskSnapshot).where(*crit)
    total = (
        await db.execute(select(func.count()).select_from(q.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            q.order_by(RiskSnapshot.score.desc(), RiskSnapshot.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    names = await _identity_names(db, rows)
    return {
        "run_id": effective_run,
        "total": total,
        "page": page,
        "items": [
            {
                "id": r.id,
                "run_id": r.run_id,
                "identity_id": r.identity_id,
                "employee_id": r.identity_employee_id,
                "score": r.score,
                "band": r.band,
                "signals": json.loads(r.signals),
                "name": names.get(r.identity_id, {}).get("name"),
                "department": names.get(r.identity_id, {}).get("department"),
            }
            for r in rows
        ],
    }


@router.get("/trend/{identity_id}")
async def identity_trend(identity_id: int, db: DbSession, user: ReportViewer):
    if await db.get(Identity, identity_id) is None:
        raise HTTPException(404, "Identity not found")
    rows = (
        await db.execute(
            select(RiskSnapshot)
            .where(RiskSnapshot.identity_id == identity_id)
            .order_by(RiskSnapshot.computed_at.asc(), RiskSnapshot.id.asc())
        )
    ).scalars().all()
    return {
        "identity_id": identity_id,
        "items": [
            {
                "run_id": r.run_id,
                "score": r.score,
                "band": r.band,
                "signals": json.loads(r.signals),
                "computed_at": r.computed_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/summary")
async def risk_summary(db: DbSession, user: ReportViewer):
    latest = await _latest_run_id(db)
    if latest is None:
        return {
            "run_id": None,
            "run_at": None,
            "scored_identities": 0,
            "average_score": 0.0,
            "band_distribution": {},
            "top_risky": [],
        }
    rows = (
        await db.execute(
            select(RiskSnapshot)
            .where(RiskSnapshot.run_id == latest)
            .order_by(RiskSnapshot.score.desc(), RiskSnapshot.id.asc())
        )
    ).scalars().all()
    distribution: dict[str, int] = {}
    for r in rows:
        distribution[r.band] = distribution.get(r.band, 0) + 1
    names = await _identity_names(db, rows)
    top = []
    for r in rows[:10]:
        factors = sorted(
            json.loads(r.factors), key=lambda f: f["contribution"], reverse=True
        )
        top.append(
            {
                "employee_id": r.identity_employee_id,
                "name": names.get(r.identity_id, {}).get("name"),
                "score": r.score,
                "band": r.band,
                "top_factors": [
                    {"signal": f["signal"], "contribution": f["contribution"], "detail": f["detail"]}
                    for f in factors[:3]
                ],
            }
        )
    return {
        "run_id": latest,
        "run_at": rows[0].computed_at.isoformat() if rows else None,
        "scored_identities": len(rows),
        "average_score": round(sum(r.score for r in rows) / len(rows), 1) if rows else 0.0,
        "band_distribution": distribution,
        "top_risky": top,
    }
