"""Reminder-email worker: runs INSIDE each app replica (resilience contract 4).

Fork-A shape per HANDOFF spec: claim transaction (FOR UPDATE SKIP LOCKED,
multi-replica safe on Postgres) -> send OUTSIDE the claim transaction (network
I/O never holds DB locks) -> finalize transaction. A replica dying between
claim and finalize leaves rows 'sending'; the stuck-row reclaim re-queues them.
Dev mode (no IAG_SMTP_HOST) delivers log-only: the email is logged and marked
sent, so the stack runs honestly without an SMTP server.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_service import append_audit
from app.models.email import EmailOutbox, OutboxStatus
from app.models.identity import utcnow

logger = logging.getLogger("iag.email")

SendFn = Callable[[EmailOutbox], Awaitable[None]]


def build_send_fn(settings) -> SendFn:
    """SMTP when configured, log-only otherwise. Kept trivial: one plain-text
    email per send call, no connection pooling across the loop."""
    if not settings.smtp_host:
        async def log_only(row: EmailOutbox) -> None:
            logger.info(
                "EMAIL(log-only) to=%s subject=%r body=%d chars",
                row.recipient, row.subject, len(row.body),
            )
        return log_only
    import smtplib
    from email.message import EmailMessage

    async def smtp_send(row: EmailOutbox) -> None:
        # smtplib is sync; the short TLS handshake is tolerable in-loop. If it
        # ever matters, aiosmtplib is the drop-in change.
        msg = EmailMessage()
        msg["From"] = settings.smtp_from
        msg["To"] = row.recipient or ""
        msg["Subject"] = row.subject
        msg.set_content(row.body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)

    return smtp_send


async def _claim_due(session: AsyncSession, settings, now) -> list[EmailOutbox]:
    """Claim TX: due rows marked sending + attempts+1, committed atomically.

    SKIP LOCKED keeps concurrent replicas from claiming the same row; SQLite
    (tests) drops the clause and calls serialize, which is acceptable per spec.
    Stuck 'sending' rows older than the reclaim window are re-claimed here too.
    """
    due = (
        select(EmailOutbox)
        .where(EmailOutbox.status == OutboxStatus.PENDING,
               EmailOutbox.due_at <= now)
        .limit(settings.reminder_batch_size)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(due)).scalars().all())
    cutoff = now - timedelta(minutes=settings.reminder_stuck_minutes)
    stuck = (
        select(EmailOutbox)
        .where(EmailOutbox.status == OutboxStatus.SENDING,
               EmailOutbox.updated_at < cutoff)
        .limit(settings.reminder_batch_size)
        .with_for_update(skip_locked=True)
    )
    stuck_rows = list((await session.execute(stuck)).scalars().all())
    for row in rows + stuck_rows:
        row.status = OutboxStatus.SENDING
        row.attempts += 1
        row.updated_at = now
    await session.commit()
    return rows + stuck_rows


async def _finalize(session: AsyncSession, row: EmailOutbox, error: str | None, settings, stats: dict) -> None:
    """Finalize TX (separate from claim): mark sent/failed + audit, one commit.

    attempt-scope finalize: the claim already bumped attempts, so max-attempts
    checks here read the post-bump value. Failed rows go back to pending for
    the next poll unless attempts exhausted -> dead-letter (stays failed).
    """
    now = utcnow()
    if error is None:
        row.status = OutboxStatus.SENT
        row.sent_at = now
        row.last_error = None
        stats["sent"] = stats.get("sent", 0) + 1
        action, details = "email_sent", {"to": row.recipient, "subject": row.subject,
                                         "campaign_id": row.campaign_id}
    else:
        exhausted = row.attempts >= settings.reminder_max_attempts
        if exhausted:
            row.status = OutboxStatus.FAILED
            stats["dead_letter"] = stats.get("dead_letter", 0) + 1
        else:
            row.status = OutboxStatus.PENDING
            stats["requeued"] = stats.get("requeued", 0) + 1
        row.last_error = error[:500]
        action, details = "email_failed", {"to": row.recipient, "error": error[:500],
                                           "attempt": row.attempts,
                                           "dead_letter": exhausted}
    row.updated_at = now
    await append_audit(session, actor_id=None, actor_username="system",
                       action=action, entity_type="email_outbox", entity_id=row.id,
                       details=details)
    await session.commit()


async def run_pass(session_factory, send: SendFn | None = None, settings=None) -> dict:
    """One claim -> send -> finalize cycle. Testable without the loop.

    session_factory must yield a NEW AsyncSession per call (the house
    sessionmaker does). Sends run outside any open transaction; each finalize
    opens its own session so a crash between rows loses only that row.
    """
    from app.core.settings import Settings
    settings = settings or Settings()
    send = send or build_send_fn(settings)
    stats = {"claimed": 0, "sent": 0, "failed": 0, "requeued": 0, "dead_letter": 0}
    async with session_factory() as session:
        rows = await _claim_due(session, settings, utcnow())
    stats["claimed"] = len(rows)
    for row in rows:
        error = None
        try:
            await send(row)
        except Exception as exc:  # noqa: BLE001 - one bad row must not kill the pass
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("reminder send failed id=%s attempt=%s: %s",
                           row.id, row.attempts, error)
        async with session_factory() as session:
            fresh = await session.get(EmailOutbox, row.id)
            if fresh is None or fresh.status != OutboxStatus.SENDING:
                continue  # cancelled/deleted mid-flight; never resurrect
            await _finalize(session, fresh, error, settings, stats)
    return stats


async def worker_loop(app_settings=None) -> None:
    """Long-running poll loop for one replica. Started by FastAPI lifespan;
    cancelled on shutdown. One run_pass per tick; failures log and retry next
    tick so a transient DB outage never kills the worker."""
    from app.core.settings import Settings
    from app.db import SessionLocal
    settings = app_settings or Settings()
    send = build_send_fn(settings)
    logger.info("reminder worker start (poll=%ss host=%s)",
                settings.reminder_poll_seconds, settings.smtp_host or "log-only")
    while True:
        try:
            stats = await run_pass(SessionLocal, send=send, settings=settings)
            if stats["claimed"]:
                logger.info("reminder pass: %s", stats)
            await asyncio.sleep(settings.reminder_poll_seconds)
        except asyncio.CancelledError:
            logger.info("reminder worker stop")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("reminder pass crashed; retrying next tick")
            await asyncio.sleep(settings.reminder_poll_seconds)



