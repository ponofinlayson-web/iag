"""Connector sync worker: runs INSIDE each app replica (fork-A shape).

Same transaction discipline as the email worker at coarser grain: enqueue
(schedule due sources) -> claim ONE run (FOR UPDATE SKIP LOCKED + stuck
reclaim) -> fetch the remote snapshot OUTSIDE any transaction -> finalize
in a single fresh-session commit (apply + one audit entry + schedule
advance, all-or-nothing). A replica dying between claim and finalize
leaves the run 'syncing'; the stuck reclaim re-claims it. Apply is an
idempotent upsert, so re-running a crashed run is always safe.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_service import append_audit
from app.models.entitlement import Entitlement
from app.models.identity import Identity, utcnow
from app.models.source import Account, DataSource
from app.models.sync import SyncRun, SyncStatus, Triggered

logger = logging.getLogger("iag.connectors")

# Mirrors routers/sources.py PRIVILEGE_LEVELS; kept local so the worker
# never imports from the API layer.
PRIVILEGE_LEVELS = {"low", "moderate", "high", "very_high"}


@dataclass(slots=True)
class AccountRecord:
    value: str
    account_type: str = "username"
    privilege: str | None = None
    entitlements: tuple[str, ...] = ()


@dataclass(slots=True)
class SyncSnapshot:
    accounts: list[AccountRecord] = field(default_factory=list)
    entitlement_column: str = "entitlement"


FetchFn = Callable[[dict, str], Awaitable[SyncSnapshot]]


def _default_fetch(source: DataSource) -> FetchFn:
    """Resolve the adapter for the source type (Phase C registry)."""
    from app.core.connectors import get_adapter

    adapter = get_adapter(source.source_type.value)
    return adapter.fetch


async def enqueue_manual(session: AsyncSession, source_id: int) -> SyncRun | None:
    """INSERT a pending manual run. None when one is already in-flight
    (the partial unique index rejects the insert). Caller maps to 409."""
    run = SyncRun(data_source_id=source_id, triggered_by=Triggered.MANUAL)
    session.add(run)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None
    return run


async def _enqueue_due(session_factory, settings) -> int:
    """One enqueue pass: due configured sources get a pending run. First
    replica's INSERT wins the partial unique index; the others roll back."""
    now = utcnow()
    n = 0
    async with session_factory() as session:
        due = (
            await session.execute(
                select(DataSource).where(
                    DataSource.is_active.is_(True),
                    DataSource.sync_interval_minutes.is_not(None),
                    DataSource.connector_config.is_not(None),
                    DataSource.next_sync_at.is_not(None),
                    DataSource.next_sync_at <= now,
                ).order_by(DataSource.id)
            )
        ).scalars().all()
        for src in due:
            session.add(
                SyncRun(data_source_id=src.id, triggered_by=Triggered.SCHEDULE)
            )
            try:
                await session.commit()
                n += 1
            except IntegrityError:
                await session.rollback()
    return n


async def _claim_one(session: AsyncSession, settings, now) -> SyncRun | None:
    """Claim TX: one pending run -> syncing, committed. Also re-claims a
    'syncing' run older than the stuck window (crashed replica). SKIP
    LOCKED keeps replicas apart; no-op on SQLite (tests)."""
    stuck_cutoff = now - timedelta(minutes=settings.connector_stuck_minutes)
    run = (
        await session.execute(
            select(SyncRun)
            .where(SyncRun.status == SyncStatus.PENDING)
            .order_by(SyncRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalars().first()
    if run is None:
        run = (
            await session.execute(
                select(SyncRun)
                .where(
                    SyncRun.status == SyncStatus.SYNCING,
                    SyncRun.started_at.is_not(None),
                    SyncRun.started_at < stuck_cutoff,
                )
                .order_by(SyncRun.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalars().first()
    if run is None:
        return None
    run.status = SyncStatus.SYNCING
    run.started_at = now
    await session.commit()
    return run


async def _apply_snapshot(
    session: AsyncSession, source: DataSource, snapshot: SyncSnapshot, now
) -> dict:
    """Upsert a snapshot with CSV-upload semantics (spec: identical
    contract): natural-key entitlement upsert, per-(source,value) account
    upsert, last_seen bumps. Accounts missing from the snapshot are
    counted, never deleted. Identity links are attempted for unlinked
    accounts by exact username/email match; existing links are never
    rewritten. Account.entitlement_id is NOT touched: it is single-valued
    (CSV shape) while connector accounts carry many entitlements, so the
    catalog is the source of truth for those."""
    counts = {
        "accounts_created": 0,
        "accounts_updated": 0,
        "entitlements_created": 0,
        "identities_linked": 0,
        "missing_from_snapshot": 0,
    }
    merged: dict[str, AccountRecord] = {}
    for rec in snapshot.accounts:
        value = (rec.value or "").strip()
        if not value:
            continue
        ents = tuple(dict.fromkeys(e for e in rec.entitlements if e and e.strip()))
        if value in merged:
            merged[value].entitlements = tuple(dict.fromkeys(merged[value].entitlements + ents))
        else:
            merged[value] = AccountRecord(
                value=value,
                account_type=(rec.account_type or "username").strip() or "username",
                privilege=rec.privilege,
                entitlements=ents,
            )
    snap_values = set(merged)

    existing = (
        await session.execute(
            select(Account).where(Account.data_source_id == source.id)
        )
    ).scalars().all()
    by_value = {a.account_value: a for a in existing}
    counts["missing_from_snapshot"] = len(
        {a.account_value for a in existing} - snap_values
    )

    ent_cache: dict[str, Entitlement] = {}
    column = (snapshot.entitlement_column or "entitlement").strip() or "entitlement"

    async def _ent_for(name: str) -> None:
        natural = name.strip().lower()
        if natural in ent_cache:
            return
        ent = (
            await session.execute(
                select(Entitlement).where(
                    Entitlement.data_source_id == source.id,
                    Entitlement.source_column == column,
                    Entitlement.source_value == natural,
                )
            )
        ).scalars().first()
        if ent is None:
            seq = (
                await session.execute(select(func.count()).select_from(Entitlement))
            ).scalar_one() + 1
            ent = Entitlement(
                data_source_id=source.id,
                catalog_id=f"ENT-{seq:05d}",
                name=name.strip(),
                source_column=column,
                source_value=natural,
                last_seen_at=now,
            )
            session.add(ent)
            await session.flush()
            counts["entitlements_created"] += 1
        else:
            ent.last_seen_at = now
        ent_cache[natural] = ent

    unlinked: list[Account] = []
    for rec in merged.values():
        for e_name in rec.entitlements:
            await _ent_for(e_name)
        priv = (rec.privilege or "").strip().lower() or None
        if priv and priv not in PRIVILEGE_LEVELS:
            priv = None
        acc = by_value.get(rec.value)
        if acc is None:
            acc = Account(
                data_source_id=source.id,
                account_value=rec.value,
                account_type=rec.account_type,
                privilege_level=priv,
                last_seen_at=now,
            )
            session.add(acc)
            await session.flush()
            by_value[rec.value] = acc
            counts["accounts_created"] += 1
        else:
            acc.account_type = rec.account_type
            acc.privilege_level = priv or acc.privilege_level
            acc.last_seen_at = now
            counts["accounts_updated"] += 1
        if acc.identity_id is None:
            unlinked.append(acc)

    if unlinked:
        values = [a.account_value for a in unlinked]
        idents = (
            await session.execute(
                select(Identity).where(
                    or_(Identity.username.in_(values), Identity.email.in_(values))
                )
            )
        ).scalars().all()
        by_username = {i.username: i.id for i in idents if i.username}
        by_email = {i.email: i.id for i in idents if i.email}
        for acc in unlinked:
            iid = by_username.get(acc.account_value) or by_email.get(acc.account_value)
            if iid is not None:
                acc.identity_id = iid
                counts["identities_linked"] += 1
    return counts


async def _finalize(
    session: AsyncSession,
    run: SyncRun,
    source: DataSource | None,
    snapshot: SyncSnapshot | None,
    error: str | None,
    settings,
    started_at,
) -> bool:
    """Finalize TX: apply + ONE audit entry + status + schedule advance in
    a single commit. Failed scheduled runs reschedule too (decision D5)."""
    now = utcnow()
    counts: dict = {}
    if error is None:
        try:
            counts = await _apply_snapshot(session, source, snapshot, now)
            run.status = SyncStatus.DONE
            action = "connector_sync_completed"
        except Exception as exc:  # noqa: BLE001 - run fails honestly, chain intact
            await session.rollback()
            error = f"apply failed: {type(exc).__name__}: {exc}"
    if error is not None:
        run.status = SyncStatus.FAILED
        run.error = error[:500]
        action = "connector_sync_failed"
    run.finished_at = now
    details = {
        "triggered_by": run.triggered_by,
        **counts,
        "duration_ms": int((now - started_at).total_seconds() * 1000),
    }
    if error is not None:
        details["error"] = error[:500]
    run.stats = json.dumps(details)
    if source is not None:
        source.last_sync_at = now
        if source.sync_interval_minutes:
            source.next_sync_at = now + timedelta(
                minutes=source.sync_interval_minutes
            )
    await append_audit(
        session, actor_id=None, actor_username="system", action=action,
        entity_type="sync_run", entity_id=run.id, details=details,
    )
    await session.commit()
    return error is None


async def run_pass(session_factory, fetch: FetchFn | None = None, settings=None) -> dict:
    """One enqueue -> claim -> fetch -> finalize cycle. Testable without
    the loop. Fetch (network) runs OUTSIDE any transaction; finalize opens
    its own session so a crash costs at most the run, never the chain."""
    from app.core.settings import Settings

    settings = settings or Settings()
    stats = {"enqueued": 0, "claimed": 0, "completed": 0, "failed": 0,
             "skipped_cancelled": 0}
    stats["enqueued"] = await _enqueue_due(session_factory, settings)

    async with session_factory() as session:
        run = await _claim_one(session, settings, utcnow())
    if run is None:
        return stats
    stats["claimed"] = 1
    started_at = utcnow()

    error: str | None = None
    snapshot: SyncSnapshot | None = None
    async with session_factory() as session:
        source = await session.get(DataSource, run.data_source_id)
        if source is None:
            error = "data source deleted mid-run"
        elif not source.connector_config:
            error = "source has no connector config"
    if error is None:
        try:
            config = json.loads(source.connector_config or "{}")
            fetch_fn = fetch or _default_fetch(source)
            snapshot = await fetch_fn(config, source.connector_secret or "")
            if len(snapshot.accounts) > settings.connector_max_rows:
                raise ValueError(
                    f"snapshot rows {len(snapshot.accounts)} exceed "
                    f"IAG_CONNECTOR_MAX_ROWS={settings.connector_max_rows}"
                )
        except Exception as exc:  # noqa: BLE001 - fetch failure fails the run
            error = f"{type(exc).__name__}: {exc}"
            snapshot = None
            logger.warning("connector fetch failed run=%s source=%s: %s",
                           run.id, run.data_source_id, error)

    async with session_factory() as session:
        fresh = await session.get(SyncRun, run.id)
        if fresh is None or fresh.status != SyncStatus.SYNCING:
            stats["skipped_cancelled"] = 1  # cancelled mid-flight; never resurrect
            return stats
        src = await session.get(DataSource, run.data_source_id)
        ok = await _finalize(session, fresh, src, snapshot, error, settings, started_at)
        stats["completed" if ok else "failed"] += 1
    return stats


async def connector_worker_loop(app_settings=None) -> None:
    """Long-running loop for one replica; started by FastAPI lifespan."""
    from app.core.settings import Settings
    from app.db import SessionLocal

    settings = app_settings or Settings()
    logger.info("connector worker start (poll=%ss)", settings.connector_poll_seconds)
    while True:
        try:
            stats = await run_pass(SessionLocal, settings=settings)
            if stats["claimed"]:
                logger.info("connector pass: %s", stats)
            await asyncio.sleep(settings.connector_poll_seconds)
        except asyncio.CancelledError:
            logger.info("connector worker stop")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("connector pass crashed; retrying next tick")
            await asyncio.sleep(settings.connector_poll_seconds)
