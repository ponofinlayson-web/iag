"""Audit service: appends hash-chained entries in the caller's transaction."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import GENESIS, AuditEntry, canonical_json, compute_record_hash
from app.models.identity import utcnow
def _iso_ts(dt: datetime) -> str:
    """DB columns are timezone-naive; timestamps written as UTC must hash
    identically before and after a round-trip, so coerce naive -> UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
def _payload(e: AuditEntry) -> dict:
    """The canonical payload an entry's record_hash commits to."""
    return {
        "action": e.action,
        "actor_id": e.actor_id,
        "actor_username": e.actor_username,
        "details": e.details,
        "entity_id": e.entity_id,
        "entity_type": e.entity_type,
    }
async def append_audit(
    db: AsyncSession,
    *,
    actor_id: int | None,
    actor_username: str,
    action: str,
    entity_type: str,
    entity_id: int | None,
    details: dict | None = None,
) -> AuditEntry:
    """Append one entry. Caller commits, so the entry lands in the same
    transaction as the change it describes."""
    # Pending state must be visible to the head lookup: with autoflush off,
    # an unflushed prior append in this transaction would be skipped and the
    # chain would fork. flush() is not commit(); atomicity is preserved.
    await db.flush()
    last = (
        await db.execute(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1))
    ).scalars().first()
    prev_hash = last.record_hash if last else GENESIS
    entry = AuditEntry(
        ts=utcnow(),
        actor_id=actor_id,
        actor_username=actor_username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=canonical_json(details or {}),
        prev_hash=prev_hash,
        record_hash="pending",
    )
    payload = _payload(entry)
    payload["ts"] = _iso_ts(entry.ts)
    entry.record_hash = compute_record_hash(prev_hash, payload)
    db.add(entry)
    return entry
async def verify_chain(db: AsyncSession) -> dict:
    """Walk the chain in id order; recompute each hash; report tampering."""
    entries = (
        (await db.execute(select(AuditEntry).order_by(AuditEntry.id))).scalars().all()
    )
    prev = GENESIS
    for e in entries:
        payload = _payload(e)
        payload["ts"] = _iso_ts(e.ts)
        expected = compute_record_hash(prev, payload)
        if expected != e.record_hash:
            return {
                "valid": False,
                "broken_at": e.id,
                "reason": "record_hash mismatch",
            }
        if e.prev_hash != prev:
            return {
                "valid": False,
                "broken_at": e.id,
                "reason": "prev_hash does not chain",
            }
        prev = e.record_hash
    return {"valid": True, "entries": len(entries), "head": prev}
