# Feature 3 — Remediation (revoke → rule → action → delivery)

Status: DRAFT — awaiting USER ratification. Nothing below is built yet.
Fills the REQUIREMENTS.md §4 deferred list ("remediation") and the
ARCHITECTURE.md design-slot intent for workflow automation inside the
app's own write path. (Note: ARCHITECTURE.md design slots name
connectors/email/SoD explicitly; remediation is the next reserved slot
by the §4 deferred list — this spec is that slot's contract.)

## Goal

When a reviewer revokes access during an active campaign, IAG turns that
decision into follow-up work instead of a dead record: rules match the
revocation, actions are created (optionally behind an approval gate),
and a background worker delivers them — email notification to the
source owner, or an outbound webhook to whatever system CAN enforce the
change. Every step is audit-chained in the same transaction as the
state change it describes.

## Clean-room divergence from v1 (behavioral, not code)

v1 (IAM-Simplified remediation_service.py + tier5_models) had four
actions: notify_owner, disable_account, remove_entitlement, webhook.
v2 keeps two of them (notify_owner, webhook) and deliberately drops
two:

- **disable_account — dropped.** v1 set Identity.is_active=False and
  disabled the login User. That mutates IAG's own auth data because a
  governance decision happened: a reviewer revoking one entitlement
  would lock a person out of the governance tool itself. Governance
  records access; it does not punish the login.
- **remove_entitlement — dropped.** v1 deleted the local
  AccountMapping row. Under feature-2 sync semantics (upsert-only,
  missing counted not deleted — decision D3) the next connector run
  would resurrect it, and worse, deleting mirror rows corrupts the
  record of what access EXISTS. The mirror reports reality; remediation
  reports what should be DONE about it.

Real enforcement (disabling an account in the source directory) is
write-back — that is feature 6 (SCIM-class) with its own spec, using
the connector infrastructure. Remediation in v2 is the workflow layer:
decide, record, notify, hand off. Enforce elsewhere.

## Non-goals (v1 of this feature)

- Any write-back to a source directory (LDAP/Entra/SQL connectors stay
  read-only; that's feature 6).
- Ticketing integration (v1's "create_ticket" was a comment stub).
- SoD-violation-triggered remediation (future extension; trigger is
  review revoke only).
- SLA/escalation timers on pending approvals (manual queue, no nagging).
- Per-action email retries beyond the worker's max_attempts.

## Data model — migration 0005

New table `remediation_rules`:

| column | type | notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(255), unique | |
| `description` | Text nullable | |
| `data_source_id` | FK data_sources, SET NULL, nullable | null = match any source |
| `privilege_level` | String(20) nullable | null = any; values from the 5-level vocabulary |
| `entitlement_pattern` | String(255) nullable | Python regex, matched case-insensitive against entitlement NAME; validated (compiled) at rule save |
| `action` | String(50) | `notify_owner` or `webhook` |
| `webhook_url` | Text nullable | required iff action=webhook |
| `is_active` | Boolean default true | inactive rules never match |
| `require_approval` | Boolean default false | if true, matched actions land `pending_approval` |
| `times_triggered` / `times_executed` / `times_failed` | Integer default 0 | display stats only |
| `created_at` / `updated_at` | DateTime | |

New table `remediation_actions`:

| column | type | notes |
|---|---|---|
| `id` | Integer PK | |
| `review_id` | FK reviews CASCADE, indexed | the revocation that triggered this |
| `rule_id` | FK remediation_rules SET NULL | null = default action (no rule matched) |
| `account_id` | FK accounts SET NULL | the reviewed account, at trigger time |
| `snapshot` | Text (JSON) | frozen display payload: identity name, account value, entitlement name, source name, privilege — survives FK deaths, rendered in UI |
| `action_type` | String(50) | `notify_owner` or `webhook` |
| `status` | String(20), plain TEXT per house convention | `pending_approval` → `approved` → `executing` → `completed` \| `failed`; also `cancelled` |
| `requires_approval` | Boolean | copied from rule/config at creation |
| `approved_by_id` | FK users SET NULL | |
| `approved_at` | DateTime nullable | |
| `attempts` | Integer default 0 | |
| `result` | Text nullable | success/failure message, error[:500] |
| `executed_at` | DateTime nullable | |
| `created_at` / `updated_at` | DateTime | |

Index: `ix_remediation_actions_status` on status (worker claim + queue
filters). No unique constraint on review_id — multiple rules may match
one revocation, so multiple actions per review are valid.

New table `remediation_settings` (single row, id=1 enforced):

| column | type | notes |
|---|---|---|
| `id` | Integer PK (always 1) | single-row config; whole-value JSON replaced on write (house convention) |
| `config` | Text (JSON) | `{enabled, default_action, require_approval_for_high_risk}` |

Defaults on first boot: enabled=true, default_action=notify_owner,
require_approval_for_high_risk=true. No SystemSetting table (v1's
pattern) — the single-row table is explicit and typed.

## Trigger flow (inside the review-submit transaction)

Hook: `routers/reviews.py::_finalize` — after the review status/decision
is set, before the commit that already exists there. Both single submit
and bulk submit flow through `_finalize`, so both trigger identically.
All of it inside the caller's existing commit — decision + action
creation + audit entries are atomic (invariant 10).

1. Only `decision == "revoke"` proceeds; approve is a no-op.
2. Only if `remediation_settings.enabled` is true (read in the same TX).
3. Load active rules; match each against the review's account:
   - data_source_id null or equal to account's source;
   - privilege_level null or equal to account's privilege;
   - entitlement_pattern null or regex matches the account's
     entitlement name (case-insensitive search).
   All specified conditions must hold (AND); a rule with all three null
   matches everything (explicit catch-all).
4. Matched rules → create one `remediation_actions` row each:
   - status `pending_approval` if rule.require_approval OR (config
     `require_approval_for_high_risk` and
     account privilege in high/very_high); else `approved`.
   - snapshot frozen at creation (identity/account/entitlement/source
     names + privilege + review_id) — display data only.
5. No matched rules + `default_action` set → one action with
   rule_id=null, same approval logic (config flag only; no rule
   involved).
6. `times_triggered` incremented on each matched rule.
7. Audit: one entry `remediation_actions_created` per trigger event,
   details = {review_id, rule_ids, action_ids, default_action_used}.

Matching is pure in-memory reads (rules + the already-loaded account) —
no network, no locks beyond the TX itself, safe inside the request.

Rule-matching must be a pure function over (rules, account, source,
entitlement_name) — extracted into `app/core/remediation_engine.py`,
unit-tested in isolation (same shape as sod_engine).

## Worker — fork-A mapping (email/sync worker → remediation worker)

The unit of work: one action row, claimed → delivered → finalized. Same
transaction discipline as email worker, new delivery channel.

1. **Claim TX**: SELECT one action `status=approved` (plus
   `executing` older than `remediation_stuck_minutes` — stuck reclaim)
   `FOR UPDATE SKIP LOCKED`, set `status=executing`, `attempts+=1`,
   commit. SQLite no-op guard for tests as usual.
2. **Work — OUTSIDE TX**: deliver.
   - `notify_owner`: resolve source owner identity → email; render
     `remediation_notify_owner` template (new, feature-1 registry) with
     snapshot context; send via SMTP (shared adaptive-STARTTLS sender,
     extracted from email worker — see D2). If SMTP is unconfigured
     (empty IAG_SMTP_HOST), the action fails with a clear error — a
     notify_owner action with no way to send is a config error, not a
     log-only pass (divergence from email-worker dev mode).
   - `webhook`: `httpx.AsyncClient.post(webhook_url, json=payload,
     timeout=remediation_webhook_timeout)`. Payload = snapshot fields +
     action_id + rule_id + review_id + timestamp; NO secrets.
3. **Finalize TX** (fresh session): re-read action; if status changed
   (cancelled meanwhile) skip — never resurrect. On success:
   `completed`, result, executed_at; on failure: retry logic —
   attempts < max → back to `approved` (retryable), attempts == max →
   `failed` (terminal, manual re-run via API); rule times_executed /
   times_failed incremented.
4. Loop: `remediation_worker_loop` in FastAPI lifespan next to email +
   sync workers (skipped `IAG_ENV=test`), one claim+run per
   `remediation_poll_seconds` tick; per-tick exceptions log and retry
   next tick.

Only ONE worker instance across replicas claims a given action
(SKIP LOCKED); the rest see it executing and move on. Three replicas,
three loops, no double delivery.

## notify_owner delivery — decision D2 (needs ratification)

`EmailOutbox` has `uq_email_outbox_review` (one row per review) and is
reminder-shaped: one row per reviewer per campaign start, cancel marks
pending rows cancelled. Remediation email is a different animal — it
may fire multiple times per review (multiple rules), for a different
recipient (source owner, not reviewer), with different content.

**Proposal (D2)**: remediation does NOT touch EmailOutbox. The
remediation worker delivers directly via SMTP (same adaptive
STARTTLS/Auth logic, extracted shared with email worker) and records
delivery on the action row itself. The action IS the delivery record.
Advantages: no constraint surgery, no semantic overload of the outbox,
worker retry semantics stay on one row. Cost: remediation email is not
visible in /outbox UI — it's visible in the remediation actions view.

## Audit

One entry per action creation batch (per trigger event) — see trigger
flow. One entry per state transition worth recording:
`remediation_action_executed` (details: action_id, action_type, result
truncated, duration) — written inside the finalize TX. Approvals and
cancels get their own entries at their endpoints. All same-TX as the
change (invariant 10, no exceptions).

## API (new router `routers/remediation.py`, prefix `/api/remediation`)

- `GET /api/remediation/rules` — list (AnyUser read, admin write as
  per SoD pattern: CertAdminUser writes).
- `POST /api/remediation/rules` — create; validates action type,
  compiles entitlement_pattern (400 on bad regex at SAVE, not at
  trigger), webhook action requires webhook_url.
- `PUT /api/remediation/actions/{id}` — approve (cert-admin, only from
  `pending_approval`; sets approved_by/at, status=approved) or cancel
  (any non-terminal state → cancelled).
- `GET /api/remediation/actions` — queue view: filters status /
  campaign / source; includes snapshot fields, rule name, attempts,
  result. AnyUser read.
- `GET /api/remediation/settings` — AnyUser read.
- `PUT /api/remediation/settings` — AdminUser write; whole-value JSON
  replace; audit entry.
- `POST /api/remediation/actions/{id}/retry` — cert-admin; failed →
  approved for one more worker attempt; attempts is NOT reset (history
  stays honest — see D5). If that attempt fails again, the action stays
  failed; retry can be clicked again, one attempt per click.

Reuses SoD-rule CRUD shape (dup-name 409, audit on every write).

## Frontend (minimal surface)

New `views/Remediation.tsx` (nav "Remediation"): two panels.
- Rules: table (name, filters, action, webhook url, require_approval,
  is_active, stats) + create/edit form (type-aware: webhook shows URL
  field; pattern field with inline regex validation note).
- Actions: queue table (status chip, action type, snapshot summary
  line, campaign/source, attempts, result) with approve/cancel/retry
  buttons per row where state allows.
Settings inline at top of the view (enable toggle, default action
select, high-risk approval toggle) — admin-gated.
Mirrors SodRules.tsx patterns; no new libs. client.ts gains
RemediationRule / RemediationAction types + API calls.

## Settings / env

`IAG_REMEDIATION_POLL_SECONDS=30`, `IAG_REMEDIATION_STUCK_MINUTES=15`,
`IAG_REMEDIATION_MAX_ATTEMPTS=3`,
`IAG_REMEDIATION_WEBHOOK_TIMEOUT_SECONDS=10`. Sane defaults mean no
compose.yaml change required (feature-2 lesson: only map env that
actually overrides).

## Tests (pytest, SQLite, real code paths)

- Engine (pure): rule matching — source filter, privilege filter,
  regex match/miss/invalid-regex-skips-rule, catch-all rule, AND
  semantics, inactive rule never matches.
- Trigger: revoke creates actions per matched rules; approve decision
  creates none; disabled config creates none; bulk revoke triggers
  per-review; audit entry written; rule counters bumped; same TX
  (failure before commit → no orphan actions — assert via rollback
  then re-read).
- Worker: claim approved → executing; second claim no-op; stuck
  reclaim; cancelled-while-executing never resurrects; notify_owner
  path builds email content (SMTP sink or capture at finalize
  boundary); webhook path via `httpx.MockTransport` real client code
  path; retry back to approved; terminal fail at max_attempts; rule
  stat bumps.
- API: rules CRUD + regex 400 + webhook-requires-url 400 + dup 409;
  approve happy + 409 on non-pending; cancel; settings PUT audit; retry
  semantics.
- Audit chain still verifies after full flows (verify_chain).
- Config defaults present on boot (single row seeded by migration or
  first read — migration, deterministic).

## Live proofs (real Postgres, per house style)

1. **Full flow, email leg**: stack + smtp sink (existing recipe) →
   create source w/ owner identity + email → campaign → review →
   revoke with a matching rule → action pending_approval → approve →
   worker delivers owner email to sink → action completed, audit chain
   valid. Script: `scripts/live_remediation_check.py` (cookie per
   house rules, unique names per run).
2. **Webhook leg**: same flow but rule action=webhook against a local
   HTTP sink script (`scripts/webhook_sink.py`, thread + stdlib
   `http.server`, logs request JSON to file) → assert payload fields +
   action completed.
3. Both legs assert rule stats bumped and audit chain verifies.

## Build phases (each ends green: pytest + stack healthy + commit)

A. Migration 0005 + models + settings knobs + remediation_settings
   seed + engine (pure matching) + tests
B. Trigger wiring in reviews.py + tests (single + bulk + config-off +
   audit + counters)
C. Worker (claim/deliver/finalize/loop) + notify_owner template +
   SMTP share + tests
D. API router + frontend view + client types
E. Live proofs (email leg via sink, webhook leg via webhook_sink) +
   HANDOFF update

## Open decisions for ratification

- **D1 scope**: drop v1's disable_account and remove_entitlement (see
  Clean-room divergence). Remediation = workflow + notify + webhook
  only; enforcement write-back is feature 6. THIS IS THE BIG ONE.
- **D2 delivery**: remediation email bypasses EmailOutbox, delivered
  directly by the remediation worker (action row = delivery record).
  Alternative rejected: enqueuing EmailOutbox rows (constraint surgery
  + semantic overload).
- **D3 trigger scope**: revoke-only. SoD-triggered or scheduled
  re-checks are future extensions.
- **D4 config store**: single-row `remediation_settings` table vs env
  knobs only. Proposed: table (runtime-changeable, audited); env for
  worker tuning only.
- **D5 retry semantics**: worker retries to max_attempts, then failed
  is terminal until an admin clicks retry (failed → approved, one more
  attempt per click, attempts NOT reset — history stays honest).
- **D6 regex safety**: admin-only pattern surface, 255-char cap,
  compile-at-save; catastrophic backtracking risk acknowledged (Python
  re has no timeout). Accepted for single-admin local tool.
- **D7 notify recipient**: source owner identity email only (v1
  parity). Alternative: configurable extra recipients — future.
