# Feature 2 — Live LDAP / Entra / SQL connectors

Status: RATIFIED 2026-08-20 (D2 deferred to polish phase; see Secrets).
Build phases A-E may proceed. Nothing below is built yet.
Fills the reserved ARCHITECTURE.md slot: "Live LDAP/Entra/SQL connectors:
background sync tasks inside app replicas."

## Goal

Replace the "connector types modeled, stubbed" placeholder with real sync:
each DataSource of type `ldap` / `entra` / `sql` can be configured with
credentials and periodically pulled into `accounts` / `entitlements` by a
background worker running INSIDE each app replica (fork-A shape, same
resilience contract as the email worker). The app remains the only writer;
every applied sync lands one hash-chained audit entry in the same
transaction.

## Non-goals (v1 of this feature)

- Writing back to the remote directory (read-only connectors).
- Deleting/stale-marking accounts absent from a snapshot — counted, not acted on.
- Identity auto-creation from remote users — link only, never invent identities.
- Incremental/delta sync (token checkpoints) — full snapshot per run.
- Entra live-wire proof (no tenant available); see Live proofs.

## Data model — migration 0004

`data_sources` new columns:

| column | type | notes |
|---|---|---|
| `connector_config` | Text (JSON) | adapter-specific, non-secret: host, port, base_dn, filter, query, tenant_id, client_id, ... |
| `connector_secret` | Text, nullable | Fernet-encrypted bind password / client secret / DB password |
| `sync_interval_minutes` | Integer, nullable | null = manual-only |
| `next_sync_at` | DateTime, nullable | set on config save + after each run |
| `last_sync_at` | DateTime, nullable | display only |

`has_secret` is derived at read time (`connector_secret IS NOT NULL`), not a column.

New table `sync_runs`:

- `id`, `data_source_id` FK CASCADE, `status` (`pending|syncing|done|failed|cancelled`),
  `triggered_by` (`manual|schedule`; renamed from `trigger` - SQL reserved word), `started_at`, `finished_at`, `stats` Text(JSON),
  `error` Text, `created_at`.
- Partial unique index `uq_sync_run_inflight ON sync_runs(data_source_id)
  WHERE status IN ('pending','syncing')` — makes duplicate enqueue impossible
  (IntegrityError -> skip) and caps one in-flight run per source. Works on
  Postgres and SQLite.

## Secrets

**USER DECISION 2026-08-20: encryption-at-rest (original D2) is DEFERRED
to the polish phase.** Connector secrets are stored as ordinary DB rows
for now, exactly like SMTP credentials already live in `.env` today:
same trust boundary (anyone with the DB or a dump of it can read them),
zero new security surface, one less encryption layer to get wrong while
the feature is still forming. When D2 lands (polish), it becomes:

- Encrypted at rest with `cryptography.fernet.MultiFernet` keyed off
  `IAG_SECRET_KEY` (HKDF-SHA256, fixed info string, cached).
- A small migration backfills: add `connector_secret_enc` Text nullable,
  decrypt-with-old / encrypt-with-new copy job, drop the plain column.
  The plain column keeps the same name so adapters are untouched.
- Key-rotation orphans secrets (decrypt fails -> run fails with a clear
  error, admin re-enters). Documented, accepted then as now.

Until then (v1 of this feature):

- Secret stored plaintext in `data_sources.connector_secret` - same
  exposure as `.env` SMTP creds, local stack only.
- Write path: one endpoint sets config+secret together; secret never read
  back - API returns `has_secret: true/false` (this boundary survives the
  future encryption migration unchanged).
- SQL connector passwords live in `connector_secret`, never in the URL.
- A WARNING comment ships in the model so nobody mistakes this for a
  finished state.
## Worker — fork-A mapping (email worker -> sync worker)

The unit of work differs: email claims one ROW of many; sync claims one JOB
that mutates many rows. Same transaction discipline, coarser grain.

1. **Enqueue pass** (one per tick): for active sources with
   `sync_interval_minutes` set and `next_sync_at <= now`, INSERT pending
   run (`trigger=schedule`). The partial unique index makes concurrent
   enqueues from 3 replicas safe: first INSERT wins, the rest get
   IntegrityError -> skip.
2. **Claim TX**: SELECT one `pending` run (plus `syncing` runs older than
   `connector_stuck_minutes` — stuck reclaim) `FOR UPDATE SKIP LOCKED`,
   set `status=syncing`, `started_at`, commit. No-op on SQLite (tests).
3. **Work — OUTSIDE any transaction**: adapter fetches a `SyncSnapshot`
   (list of account records: value, type, privilege, entitlement names)
   with per-request timeouts and paging. This is the only network step and
   never holds DB locks.
4. **Finalize TX** (fresh session): re-read the run; if status != `syncing`
   (cancelled meanwhile) skip — never resurrect, same as email. Otherwise:
   apply snapshot (below) + write ONE audit entry + set run done/failed +
   advance `last_sync_at`/`next_sync_at` — single commit, all-or-nothing.

Loop: `connector_worker_loop` started in FastAPI lifespan next to the email
worker (skipped under `IAG_ENV=test`), one enqueue+claim+run per
`connector_poll_seconds` tick; per-tick exceptions log and retry next tick.

## Apply semantics (identical contract to CSV upload)

- Entitlements: natural-key upsert per (source, column, normalized value).
- Accounts: upsert per (source, account_value); update `last_seen_at`;
  attempt identity link by exact email/username match (same semantics as
  bulk-link; existing links never rewritten).
- Accounts present in DB but absent from snapshot: counted in stats as
  `missing_from_snapshot`, NOT deleted/deactivated (decision D3).
- Whole run applies in ONE transaction — a failed apply leaves the previous
  snapshot fully intact.

## Audit

One entry per run, written inside the finalize transaction:
`connector_sync_completed` / `connector_sync_failed`, entity_type
`sync_run`, entity_id = run id, details = trigger, counts (accounts
created/updated/linked/missing, entitlements created), duration,
error[:500] on failure. Per-account entries would flood the chain on a
10k-row first sync — the run is the auditable unit. (Decision D4.)

## Adapters

Shared protocol: `async fetch(config: dict, secret: str) -> SyncSnapshot`.
Each adapter also exposes `validate(config, secret)` for synchronous
fail-fast at config-save time (the validate_smtp philosophy: misconfig
dies at write, not at 03:00 in the worker).

- **ldap** — `ldap3`, sync calls via `asyncio.to_thread`. Paged search over
  a configurable filter; entries -> accounts, `memberOf`/group DNs ->
  entitlement names. Validate = bind + base search LIMIT 1.
- **entra** — `httpx.AsyncClient`. Client-credentials token (cached
  in-process), paginated `/users` + `transitiveMemberOf` via `$batch` or
  sequential gets with `ConsistencyLevel: eventual`. appRole / group names
  -> entitlements. Validate = token fetch only.
- **sql** — admin-supplied SELECT (must return columns account/entitlement
  [/privilege]); run on a throwaway sync SQLAlchemy engine via
  `asyncio.to_thread`, `SET TRANSACTION READ ONLY` enforced on Postgres.
  Driver availability is the deployer's business (psycopg2 ships for
  Postgres URLs; others = add the driver). Validate = connect + query LIMIT 1.

## API (cert-admin gated unless noted)

- `PUT /api/sources/{id}/connector` — set config + secret + interval;
  runs adapter `validate` synchronously (timeout-bounded) before saving;
  rejects non-connector source types; empty secret field = keep existing.
- `POST /api/sources/{id}/sync` — enqueue manual run; 409 if in-flight;
  400 if type has no adapter. Returns run id.
- `GET /api/sources/{id}/syncs` — run history (AnyUser), newest first.
- `GET /api/syncs/{run_id}` — single run incl. stats (AnyUser).
- `POST /api/syncs/{run_id}/cancel` — cert admin; finalize then skips
  (never resurrect). Stuck runs self-heal via reclaim anyway.
- Source GET/list responses gain `connector: {configured, interval_minutes,
  next_sync_at, last_sync_at, has_secret, last_run_status}`.

## Frontend (minimal surface)

Sources page: per-row "Sync now" button + last-run status chip; source
detail: connector config form (type-aware fields, secret write-only) +
interval field; run history drawer (status, trigger, counts, error).
Mirror existing patterns; no new libs.

## Settings / env

`IAG_CONNECTOR_POLL_SECONDS=60`, `IAG_CONNECTOR_STUCK_MINUTES=15`,
`IAG_CONNECTOR_TIMEOUT_SECONDS=30`, `IAG_CONNECTOR_MAX_ROWS=50000`.
Sane defaults mean no compose.yaml change required (lesson from app-3:
only map env that actually overrides). Snapshot larger than MAX_ROWS ->
run fails fast with a clear error.

## Tests (pytest, SQLite, real code paths)

- Enqueue: due source enqueued; not before `next_sync_at`; manual trigger;
  duplicate enqueue is a no-op (unique index).
- Claim: pending -> syncing; second claim gets nothing; stale `syncing`
  reclaimed after stuck window; cancelled run skipped at finalize.
- Apply: creates accounts+entitlements; re-run upserts (no dupes);
  `last_seen_at` advanced; identity linked by email; missing counted not
  deleted.
- Finalize: success path (stats, audit entry, schedule advanced) and
  failure path (status/error/audit).
- Adapter units: ldap3 MOCK strategy (built into ldap3 — no server, no
  external mock), entra via `httpx.MockTransport` (built in), sql against
  a real SQLite file through the real engine path.
- Audit chain still verifies after a run (verify_chain).

## Live proofs (real Postgres, per house style)

1. **SQL — self-referencing**: configure a `sql` connector whose query reads
   a planted table in the stack's own Postgres -> full worker pass live ->
   accounts appear, audit chain valid. Real wire, zero new infra.
2. **LDAP — glauth**: optional compose profile (`--profile connectors`)
   adding glauth (single-binary fake LDAP server, yaml users/groups) ->
   live sync of its users/groups. Real wire, opt-in only.
3. **Entra — not live-provable** without a tenant: MockTransport coverage +
   a documented manual checklist for first production use. Stated plainly,
   not papered over.

## Build phases (each ends green: pytest + stack healthy)

A. Migration 0004 + models + settings + secrets module
B. Worker (enqueue/claim/apply/finalize/loop) + tests
C. Adapters + validation + tests
D. API endpoints + frontend surface
E. Live proofs (SQL self-ref, LDAP glauth) + HANDOFF update

## Open decisions for ratification

- **D1 deps**: add `ldap3`, `httpx` (`cryptography` dropped - it was
  only needed for the now-deferred D2; all mainstream,
  permissive licenses; `cryptography` may pull Rust wheels — it ships
  prebuilt for win/linux).
- **D2 secrets-in-DB**: ~~Fernet under `IAG_SECRET_KEY`~~ DEFERRED to
  polish by user decision 2026-08-20 (see Secrets above);
  key-rotation orphans secrets (accepted, documented).
- **D3 no deletes**: upsert-only, missing counted (delete/stale-flag is a
  future decision with its own spec).
- **D4 one audit entry per run** (not per account).
- **D5 failure reschedule**: failed scheduled run reschedules at
  `now + interval` (no backoff) — simple and predictable.
- **D6 glauth profile**: opt-in compose profile for the LDAP live proof.
