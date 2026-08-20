"""Sync run router: single-run view + cancel (Feature 2 Phase D)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.audit_service import append_audit
from app.models.sync import SyncRun, SyncStatus
from app.routers.deps import AnyUser, CertAdminUser, DbSession
from app.routers.sources import _run_out

router = APIRouter(prefix="/api/syncs", tags=["syncs"])


@router.get("/{run_id}")
async def get_sync(run_id: int, db: DbSession, user: AnyUser):
    run = await db.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(404, "Sync run not found")
    return _run_out(run)


@router.post("/{run_id}/cancel")
async def cancel_sync(run_id: int, db: DbSession, user: CertAdminUser):
    """Cancel a pending/syncing run. The worker's fresh-status check at
    finalize means a cancelled run is never resurrected; an in-flight
    fetch still completes, its result is just discarded."""
    run = await db.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(404, "Sync run not found")
    if run.status not in (SyncStatus.PENDING, SyncStatus.SYNCING):
        raise HTTPException(409, f"Run already finished ({run.status})")
    run.status = SyncStatus.CANCELLED
    await append_audit(
        db, actor_id=user.id, actor_username=user.identity.username or "",
        action="sync_run_cancelled", entity_type="sync_run", entity_id=run.id,
        details={"data_source_id": run.data_source_id},
    )
    await db.commit()
    return {"ok": True, "status": run.status}
