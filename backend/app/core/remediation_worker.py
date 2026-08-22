"""Remediation worker: delivers approved actions (fork-A discipline).

Claim TX (SKIP LOCKED) -> deliver OUTSIDE TX (SMTP direct or webhook)
-> finalize TX. Same shape as email worker with two divergences per the
ratified spec: notify_owner WITHOUT SMTP configured is a hard failure
(a notification action with no way to send is a config error, not a
log-only pass), and delivery is recorded on the action row itself
(D2 — the action row IS the delivery record).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_service import append_audit
from app.models.campaign import Campaign, Review
from app.models.identity import utcnow
from app.models.remediation import (
    RemediationAction,
    RemediationRule,
    RemediationStatus,
)
from app.models.source import Account, DataSource

logger = logging.getLogger("iag.remediation")


async def _send_smtp_direct(settings, recipient: str, subject: str, body: str) -> None:
    """SMTP send for remediation delivery. Reuses the email worker's
    adaptive-STARTTLS discipline by running through EmailOutbox-shaped
    call; synchronous smtplib, short handshake tolerable in-loop (same
    tradeoff as email worker)."""
    if not settings.smtp_host:
        raise RuntimeError(
            "notify_owner action cannot send: IAG_SMTP_HOST is not configured"
        )
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
        s.ehlo()
        if s.has_extn("starttls"):
            s.starttls()
            s.ehlo()
        else:
            logger.warning("SMTP %s:%s offers no STARTTLS; sending plaintext",
                           settings.smtp_host, settings.smtp_port)
        if settings.smtp_user and s.has_extn("auth"):
            s.login(settings.smtp_user, settings.smtp_password)
        elif settings.smtp_user:
            logger.warning("SMTP %s offers no AUTH; skipping login",
                           settings.smtp_host)
        s.send_message(msg)


async def _resolve_recipient(db, action: RemediationAction) -> str:
    """Source owner's email (D7). Walks review -> account -> source ->
    owner_identity_id (int FK) -> identity.email. Empty string when
    unresolvable — the caller treats it as a delivery failure."""
    review = await db.get(Review, action.review_id)
    if review is None:
        return ""
    account = await db.get(Account, review.account_id)
    if account is None:
        return ""
    source = await db.get(DataSource, account.data_source_id)
    if source is None or source.owner_identity_id is None:
        return ""
    from app.models.identity import Identity
    owner = await db.get(Identity, source.owner_identity_id)
    if owner is None or not owner.email:
        return ""
    return owner.email


async def _deliver_notify_owner(db, action: RemediationAction, settings) -> str:
    """Render the notify template with snapshot + live context and send
    direct via SMTP. Returns the result line for the action row."""
    from app.core.email_templates import render_email

    snapshot = action.snapshot_dict()
    review = await db.get(Review, action.review_id)
    if review is None:
        raise RuntimeError("review gone; cannot deliver notify_owner")
    campaign = await db.get(Campaign, review.campaign_id)
    recipient = await _resolve_recipient(db, action)
    if not recipient:
        raise RuntimeError("source owner email unresolvable (D7 recipient)")
    owner_first = recipient.split("@", 1)[0].capitalize()
    subject, body = render_email(
        "remediation_notify_owner",
        first_name=owner_first,
        campaign_name=campaign.name if campaign else f"campaign {review.campaign_id}",
        data_source_name=snapshot.get("data_source_name") or "unknown source",
        account_value=snapshot.get("account_value") or "?",
        account_type=snapshot.get("account_type") or "?",
        privilege_level=snapshot.get("privilege_level") or "?",
        entitlement_name=snapshot.get("entitlement_name") or "unknown entitlement",
        identity_name=snapshot.get("identity_name") or "unknown identity",
        reviewer_comment=review.comments or "(none)",
        action_id=action.id,
        review_id=action.review_id,
    )
    await _send_smtp_direct(settings, recipient, subject, body)
    return f"email sent to {recipient}"


async def _deliver_webhook(db, action: RemediationAction, settings) -> str:
    """POST snapshot payload to the rule's webhook_url. NO secrets."""
    import httpx

    rule = await db.get(RemediationRule, action.rule_id) if action.rule_id else None
    url = rule.webhook_url if rule and rule.webhook_url else None
    if not url:
        raise RuntimeError("webhook action has no webhook_url (rule deleted or none)")
    payload = dict(action.snapshot_dict())
    payload.update({
        "action_id": action.id,
        "rule_id": action.rule_id,
        "review_id": action.review_id,
        "action_type": action.action_type,
        "ts": utcnow().isoformat(),
    })
    async with httpx.AsyncClient(
        timeout=settings.remediation_webhook_timeout_seconds
    ) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    return f"webhook {resp.status_code} from {url[:120]}"


async def _deliver_enforce(db, action: RemediationAction, settings) -> str:
    """Feature-6 D: write the revocation back to the account's source
    directory. The frozen snapshot (data_source_id + target) is the seam;
    target was pinned at trigger time so editing the rule later can never
    silently change what an in-flight action does."""
    import json

    from app.core.enforcement import enforce_against_source

    snapshot = action.snapshot_dict()
    source_id = snapshot.get("data_source_id")
    if not source_id:
        raise RuntimeError("enforce action snapshot has no data_source_id")
    source = await db.get(DataSource, source_id)
    if source is None:
        raise RuntimeError(
            f"enforce action's source {source_id} no longer exists"
        )
    try:
        config = json.loads(source.connector_config) if source.connector_config else {}
    except (TypeError, ValueError):
        config = {}
    if not config:
        raise RuntimeError(
            f"source '{source.name}' has no connector config; enforcement "
            "needs a configured ldap/entra/sql source"
        )
    target = snapshot.get("target") or "remove_entitlement"
    result = await enforce_against_source(
        source.source_type, config, source.connector_secret or "",
        snapshot, target,
    )
    return f"target={target}; {result}"


async def _deliver_unsupported(db, action: RemediationAction, settings) -> str:
    raise RuntimeError(
        f"action_type '{action.action_type}' has no delivery arm in this build"
    )


_DELIVERERS = {
    "notify_owner": _deliver_notify_owner,
    "webhook": _deliver_webhook,
    "enforce": _deliver_enforce,
}


async def _claim_due(session: AsyncSession, settings, now) -> list[RemediationAction]:
    """Claim TX: approved (or stuck executing) rows -> executing,
    attempts+1, one commit. SKIP LOCKED for multi-replica safety."""
    due = (
        select(RemediationAction)
        .where(RemediationAction.status == RemediationStatus.APPROVED)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(due)).scalars().all())
    cutoff = now - timedelta(minutes=settings.remediation_stuck_minutes)
    stuck = (
        select(RemediationAction)
        .where(
            RemediationAction.status == RemediationStatus.EXECUTING,
            RemediationAction.updated_at < cutoff,
        )
        .with_for_update(skip_locked=True)
    )
    stuck_rows = list((await session.execute(stuck)).scalars().all())
    for row in rows + stuck_rows:
        row.status = RemediationStatus.EXECUTING
        row.attempts += 1
        row.updated_at = now
    await session.commit()
    return rows + stuck_rows


async def _finalize(
    session: AsyncSession, action: RemediationAction,
    error: str | None, settings, stats: dict,
) -> None:
    """Finalize TX: completed / requeue-approved / failed-terminal, plus
    audit + rule counters, one commit."""
    now = utcnow()
    rule = await session.get(RemediationRule, action.rule_id) if action.rule_id else None
    if error is None:
        action.status = RemediationStatus.COMPLETED
        action.result = action.result or ""
        action.executed_at = now
        if rule is not None:
            rule.times_executed += 1
        stats["completed"] = stats.get("completed", 0) + 1
        action_name, details = "remediation_action_executed", {
            "action_id": action.id, "action_type": action.action_type,
            "result": (action.result or "")[:500],
        }
    else:
        exhausted = action.attempts >= settings.remediation_max_attempts
        if exhausted:
            action.status = RemediationStatus.FAILED
            stats["failed"] = stats.get("failed", 0) + 1
        else:
            action.status = RemediationStatus.APPROVED  # retryable
            stats["requeued"] = stats.get("requeued", 0) + 1
        if rule is not None:
            rule.times_failed += 1
        action.result = error[:500]
        action_name, details = "remediation_action_failed", {
            "action_id": action.id, "action_type": action.action_type,
            "error": error[:500], "attempt": action.attempts,
            "dead_letter": exhausted,
        }
    action.updated_at = now
    await append_audit(
        session, actor_id=None, actor_username="system",
        action=action_name, entity_type="remediation_action",
        entity_id=action.id, details=details,
    )
    await session.commit()


async def run_pass(session_factory, settings=None, deliver_overrides=None) -> dict:
    """One claim -> deliver -> finalize cycle, testable without the loop."""
    from app.core.settings import Settings

    settings = settings or Settings()
    overrides = deliver_overrides or {}
    stats = {"claimed": 0, "completed": 0, "requeued": 0, "failed": 0}
    async with session_factory() as session:
        rows = await _claim_due(session, settings, utcnow())
    stats["claimed"] = len(rows)
    for row in rows:
        error = None
        result = None
        deliver = overrides.get(row.action_type)
        if deliver is None:
            deliver = _DELIVERERS.get(row.action_type)
        if deliver is None:
            # Unknown action type must fail LOUD with its own name, not
            # fall into the webhook arm's misleading "no webhook_url"
            # (a raw mis-seeded or future type says so honestly).
            deliver = _deliver_unsupported
        try:
            async with session_factory() as session:
                result = await deliver(session, row, settings)
        except Exception as exc:  # noqa: BLE001 - one bad row never kills the pass
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("remediation deliver failed id=%s attempt=%s: %s",
                           row.id, row.attempts, error)
        async with session_factory() as session:
            fresh = await session.get(RemediationAction, row.id)
            if fresh is None or fresh.status != RemediationStatus.EXECUTING:
                continue  # cancelled mid-flight; never resurrect
            if result is not None:
                fresh.result = result
            await _finalize(session, fresh, error, settings, stats)
    return stats


async def remediation_worker_loop(app_settings=None) -> None:
    """Per-replica poll loop, started by FastAPI lifespan; one run_pass per
    remediation_poll_seconds tick; per-tick exceptions log and continue."""
    from app.core.settings import Settings
    from app.db import SessionLocal

    settings = app_settings or Settings()
    logger.info("remediation worker start (poll=%ss)", settings.remediation_poll_seconds)
    while True:
        try:
            stats = await run_pass(SessionLocal, settings=settings)
            if stats["claimed"]:
                logger.info("remediation pass: %s", stats)
            await asyncio.sleep(settings.remediation_poll_seconds)
        except asyncio.CancelledError:
            logger.info("remediation worker stop")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("remediation pass crashed; retrying next tick")
            await asyncio.sleep(settings.remediation_poll_seconds)
