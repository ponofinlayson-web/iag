# IAG v2 Rebuild ‚Äî Handoff

Continuation point for a fresh agent session. Read this fully before acting.
Project root: `D:\Projects\iag` (the v1 codebase it replaces is `D:\IAM-Simplified` ‚Äî
read-only reference; copy NO code from it).

## Mission

Clean-room rebuild of the user's first project (an IAM governance tool) as an
exceptional, sound web app. Specs already derived and frozen:
- `REQUIREMENTS.md` ‚Äî domain rules, roles, invariants, resilience contract
- `ARCHITECTURE.md` ‚Äî stack, container topology, design slots

Read both first. They are the contract. Do not re-derive.

## User context

- Novice vibe-coder, long unpaid hours, values honest "this is fragile" over
  reassurance. Flag real wins explicitly, explain the why in 1-2 sentences.
- Verification culture: label inference [H] vs verified [V]. Never fabricate
  file states or test results.
- This project is why the whole environment was built. Quality matters most.

## Critical: tool corruption guard

During the prior session, long file writes (via file_editor AND terminal
heredocs) intermittently corrupted content: duplicated lines, garbled tokens,
placeholder junk. EVERY file in backend/ was AST-checked (python -c "import
ast; ast.parse(...)") at write time and fixed when caught.

RULE: after ANY file write, verify before trusting. For Python: AST check.
For config/TS: lint or targeted grep for junk markers (duplicate lines,
words like "placeholder", "corrupt", "marker"). Write in chunks under ~120
lines; corruption correlated with long single writes and long context.

## Verified state [V]

All backend files exist and passed AST checks at write time:

backend/app/core/settings.py ‚Äî pydantic-settings, IAG_* env aliases,
  db_url_sync() conversion, validate_secrets() fail-fast
backend/app/core/security.py ‚Äî bcrypt (passlib) + scrypt fallback,
  HMAC-signed session tokens (new_session_token / verify_session_token)
backend/app/core/audit_service.py ‚Äî append_audit() same-transaction append,
  verify_chain() full-chain walk; canonical_json in models/audit.py
backend/app/db.py ‚Äî async engine, Base, get_db, SQLite FK pragma
backend/app/models/*.py ‚Äî identity, user (Role enum), source (DataSource,
  Account, SourceType), entitlement (natural key uq constraint),
  campaign (Campaign/Review + status enums), audit (AuditEntry hash chain)
backend/app/routers/deps.py ‚Äî get_current_user, require_roles, Annotated
  aliases: AdminUser, CertAdminUser, AnyUser, DbSession; exports _settings
backend/app/routers/auth.py ‚Äî login (lockout), me, logout, change-password
backend/app/routers/identities.py ‚Äî list/get/create/update/delete,
  /import CSV upsert, /export CSV, manager-cycle guard (_check_cycle)
backend/app/routers/sources.py ‚Äî CRUD, /upload CSV (natural-key entitlement
  upsert), accounts list, link, bulk-link by username|email
backend/app/routers/entitlements.py ‚Äî list, /stats, PUT privilege
backend/app/routers/campaigns.py ‚Äî CRUD, /preview (DRY-RUN reviewer
  resolution ‚Äî v1's best idea), stage, start (clears+regenerates reviews),
  cancel, /metrics
backend/app/routers/reviews.py ‚Äî queue, count, history, detail, submit
  (revoke REQUIRES comment), bulk-submit, campaign auto-complete on last
backend/app/routers/audit.py ‚Äî list (audit/system_admin/cert_admin only),
  /verify, /export CSV
backend/app/routers/dashboard.py ‚Äî portfolio + personal workload counts
backend/app/core/email_worker.py ‚Äî reminder worker: _claim_due (FOR UPDATE
  SKIP LOCKED + stuck reclaim), send outside TX, _finalize sent/failed/
  dead-letter + audit, run_pass, worker_loop (lifespan, skipped in test env)
backend/app/routers/reminders.py ‚Äî read-only: GET /api/reminders/outbox
  (paged, campaign/status filter), GET /api/reminders/campaigns/{id}
  (by_status counts); CertAdminUser only
backend/app/models/email.py ‚Äî EmailOutbox + OutboxStatus
backend/alembic/versions/0003_email_outbox.py ‚Äî explicit DDL, portable types
backend/tests/test_reminders.py ‚Äî enqueue, claim/send+chain, no-double-send,
  retry‚Üídead-letter, cancel-blocks-claim, 401/403, boot (suite 19/19)
backend/app/main.py ‚Äî FastAPI assembly, JSON logging, /api/health, SPA mount
backend/app/bootstrap.py ‚Äî one-shot first-admin creator (env creds)
backend/alembic.ini, alembic/env.py, alembic/script.py.mako
backend/alembic/versions/0001_initial.py ‚Äî metadata-driven create_all
backend/tests/conftest.py ‚Äî per-test SQLite file DB, in-loop seeding,
  admin_client fixture, exposes app.state.test_db_path
backend/tests/test_auth.py ‚Äî health, 401s, lockout, cookie, change-password
backend/tests/test_workflow.py ‚Äî full E2E: import‚Üísource‚Üíupload‚Üíbulk-link‚Üí
  campaign‚Üípreview‚Üístage‚Üístart‚Üíreviews‚Üíauto-complete‚Üíchain verify
backend/tests/test_audit_tamper.py ‚Äî raw-SQL mutation must break chain
backend/pyproject.toml ‚Äî deps + pytest config (pythonpath=["."])
uv.lock + .venv exist ‚Äî `uv sync` completed successfully [V]

## Unverified / in-flight

Nothing broken. Arc: 1/6 shipped, feature 2 spec DRAFTED awaiting
ratification. Fresh-volume reset proof DONE (2026-08-18, this session).
Design specs required before features 3-6 (no reserved slots).

## Session log (newest first)


### 2026-08-18 (session 2 — reset proof + feature 2 spec)

- Verified session-start state matched handoff exactly [V]: master @
  3ce5afd clean, 0 SMTP lines in .env, 5/5 containers healthy.
- **Fresh-volume reset proof PASSED first try** (pre-ratified): `down -v`
  removed both volumes (iag_pgdata, iag_static) -> `up -d --build` -> all
  healthy. psql proof via `docker compose exec -T iag-db psql -U iag_migrate
  -d iag`: alembic_version=0003, email_outbox present (14 cols), bootstrap
  admin `admin@iag.local` SYSTEM_ADMIN active. Front door :8090 serving
  SPA 200. Service name is `iag-db` not `db`; DB role `iag_migrate`, DB
  `iag` [V].
- **Feature 2 spec DRAFTED**: `SPECS/feature-2-connectors.md` (202 lines,
  16 sections). Live LDAP/Entra/SQL connectors per reserved architecture
  slot: migration 0004 (connector config/secret/interval columns +
  sync_runs table with partial unique in-flight index), fork-A worker
  (enqueue/claim/work-outside-TX/finalize), Fernet secrets under
  IAG_SECRET_KEY, three adapters, API, frontend surface, tests, live
  proofs (SQL self-ref + glauth LDAP profile; Entra = MockTransport only,
  stated plainly). SIX open decisions D1-D6 awaiting user ratification.
- Corruption guard honored: first file_editor write of the spec came out
  garbled (duplicate sections, junk tokens) — caught by spot-check,
  deleted, rewritten clean, verified (0 corruption tokens, headers sane).
  Same guard applies to every write this session.

### 2026-08-18 (deferred-arc session 1 - FEATURE 1 SHIPPED)

Context: user ratified the full deferred-features arc (menu items 1-6, in
order). Feature 1 = email templates (delivery already existed in fork A).

Shipped (3 commits on master):
- d90dd63 templates: app/core/email_templates.py (code-stored Jinja2 registry,
  StrictUndefined, empty-subject guard, render-at-enqueue -> template failure
  is a 400 at campaign start, never a worker dead-letter). campaigns.py routes
  composition through render_email; new IAG_APP_BASE_URL setting (default
  http://localhost:8090) builds review_url; uv add jinja2. Tests 19->27.
- b50cf71 SMTP hardening + proof tooling: adaptive STARTTLS/AUTH (ehlo ->
  starttls-if-offered with re-ehlo after [STARTTLS resets esmtp_features;
  has_extn("auth") would silently skip login], loud warning when relay offers
  neither), scripts/smtp_sink.py (aiosmtpd dev sink, bind 127.0.0.1 ‚Äî
  aiosmtpd probes `hostname`, 0.0.0.0 invalid on Windows; Docker Desktop
  proxies host.docker.internal to host loopback), scripts/live_smtp_proof.py.
- 4decb98 proof-harness fixes: unique source/campaign names (live DB carries
  history ‚Äî hardcoded names collide on rerun), expected count derived from
  start response, greeting assert CRLF-tolerant + name-agnostic (live admin
  is "System", fixture is "Ada"; SMTP wire is \r\n). compose.yaml now maps
  IAG_SMTP_PORT/USER/PASSWORD/FROM into app env (only HOST was mapped;
  validate_smtp correctly refused boot on the gap ‚Äî fail-fast worked).

Proofs: pytest 27/27; live E2E PASS ‚Äî 9 emails through REAL SMTP branch to
aiosmtpd sink on live Postgres, rendered subject/URL/greeting asserted in
sink log, outbox all sent, audit chain valid. First-ever exercise of the
SMTP branch.

Post-proof state: .env SMTP block REMOVED (log-only restored ‚Äî next campaign
won't dead-letter against a dead sink). Re-enable for proofs: append 5 lines
(IAG_SMTP_HOST=host.docker.internal, PORT=1025, USER/PASSWORD=any, FROM=
iag@localhost), start sink (uv run --with aiosmtpd python scripts/smtp_sink.py
D:\Projects\iag\smtp_sink_log.jsonl 1025), docker compose up -d, then
scripts/live_smtp_proof.py.

Arc status: 1/6 done. Next: feature 2 (live connectors) ‚Äî needs migration
0004, so do the fresh-volume reset proof (0003 on empty volume) FIRST.
Remaining arc order: 3 remediation, 4 API keys, 5 risk/PDF/SIEM, 6 SCIM etc
(design conversation required before 3-6; no reserved slots for them).

### 2026-08-17 (reminder-email session - FORK A SHIPPED)

- **Fork A built, live-proven, committed 9e3f03b.** Enqueue on campaign
  start (resolved reviewer emails), in-replica worker
  (claim SKIP LOCKED ‚Üí send outside TX ‚Üí finalize TX; stuck reclaim,
  retry‚Üídead-letter, log-only dev delivery), read-only API + /outbox
  frontend view, migration 0003 on existing volume.
- Proof: pytest 19/19; smoke.sh PASS incl kill-a-replica with worker
  deployed; scripts/live_reminder_check.py PASS (enqueue ‚Üí sent within
  poll window ‚Üí cancel path ‚Üí chain valid); 0003 via psql.
- Compose now passes reminder/SMTP knobs through with defaults; .env has
  IAG_REMINDER_DELAY_MINUTES=0, IAG_REMINDER_POLL_SECONDS=5 for fast
  proofs (60/60 code defaults remain for any deployment).
- Test gotchas fixed: audit API returns details as JSON string (parse
  before .get); worker skip in test env (SessionLocal points at prod URL).
- Live-script gotchas: unique username per run (import 500s on
  ix_identities_username collision); all call() sites need the session
  cookie (module-level _COOKIE fallback added).
- .gitignore: frontend/tsconfig.tsbuildinfo untracked.

### 2026-08-17 (SoD session ‚Äî feature complete)
- SoD engine shipped per ARCHITECTURE design slot: PURE READ-SIDE. Given
  identity entitlements + active rules -> violations, computed per request.
  No persistence of violations, no auto-revoke, no background anything.
  Reviewers decide; the engine informs.
- New: models/sod.py (SodRule: two entitlement FKs CASCADE, severity,
  is_active, unique name), alembic 0002 (EXPLICIT DDL ‚Äî not create_all ‚Äî
  because migrate container is the only schema authority), core/sod_engine.py
  (violations_for_identities: 3 queries then set intersection),
  routers/sod.py (/api/sod/rules CRUD, CertAdminUser, append_audit
  same-transaction: sod_rule_created/updated/deleted).
- Wired: campaign preview returns sod {identities_flagged, accounts_flagged}
  + per-sample-item sod_violations; review detail returns sod_violations.
- Frontend: SodRules.tsx (/sod, admin nav) create/toggle/delete rules;
  CampaignDetail preview sample is now a table with SoD badges per row.
  tsc clean, vite build into backend/static/.
- Tests 12/12 (was 8): test_sod_rules (CRUD validation + audit chain for
  rule writes + 401s), test_sod_e2e (violating identity across TWO sources
  ‚Äî one account carries one entitlement ref, so a toxic pair needs two
  accounts ‚Äî preview flags with named pair, review detail shows, approve
  stays manual, inactive rule flags nothing).
- LIVE PROOFS: migration 0002 applied on the EXISTING volume without down
  -v (psql: alembic_version=0002, sod_rules table present) ‚Äî the [H] from
  the secrets session is now [V]. smoke.sh PASS incl. kill-a-replica.
  scripts/live_sod_check.py: login -> GET rules -> POST rejected 400 ->
  chain valid, against real Postgres.
- Trap (recurring): file_editor corrupted a line in routers/sod.py
  (walrus-junk in delete_rule) ‚Äî caught on read-back, fixed. Also wrote an
  unfinished stub test the first time. Post-write verification stays
  mandatory. Migrate container's alembic output is swallowed by a broken
  log format (`%(levelname)` lines) ‚Äî prove migrations via psql, not logs.
- Commit 83bc69d. Stack running @ :8090, 6 commits total.
- Next up: reminder-email task queue ‚Äî fork A RATIFIED by user;
  full build spec in the section below. Later: chain anchoring, real
  LDAP/Entra connectors, rule deactivation UI polish.

### 2026-08-17 (secrets session ‚Äî candidate #1 done)
- All hardcoded dev secrets removed from tracked files. compose.yaml uses
  ${VAR:?err} for IAG_POSTGRES_PASSWORD / IAG_APP_DB_PASSWORD /
  IAG_SECRET_KEY / IAG_BOOTSTRAP_ADMIN_PASSWORD ‚Äî missing .env means
  compose refuses to start (verified). Real values live in gitignored
  .env (generated by scripts/gen_env.py); .env.example is the template.
- deploy/initdb.sh (new): entrypoint wrapper passes IAG_APP_DB_PASSWORD
  into initdb.sql as psql var :'app_password'. The .sql is mounted at
  /opt/initdb (NOT initdb.d) so the entrypoint runs it exactly once.
  Wrapper must use psql -U "$POSTGRES_USER" ‚Äî default role 'postgres'
  does not exist in this stack (POSTGRES_USER=iag_migrate).
- Two real traps the fresh-volume verification caught:
  1. The postgres entrypoint SWALLOWS initdb.d script failures ‚Äî stack
     came up "healthy" with no iag_app role (any login = 500). Fixed:
     db healthcheck now asserts SELECT 1 FROM pg_roles WHERE
     rolname='iag_app' alongside pg_isready.
  2. The canvas file_editor writes CRLF on this host; a CRLF initdb.sh
     breaks at container boot. scripts/fix_eol.py normalizes after
     writes; .gitattributes pins *.sh and env files to LF repo+checkout.
- smoke.sh now sources ../.env, defaults BASE_URL to :8090, no fallback
  password. Login is admin / <IAG_BOOTSTRAP_ADMIN_PASSWORD from .env>.
- Fresh-volume proof PASSED: down -v -> up --build -> CREATE ROLE green
  -> bootstrap admin from .env -> smoke PASS incl. kill-a-replica.
  pytest 8/8. Commit 871c797, no remote. NOTE: changing DB passwords
  later requires down -v (initdb only runs on an empty volume).

### 2026-08-17 (stack + proof session ‚Äî ALL TASKS DONE)
- Docker stack built & verified: compose.yaml (db -> migrate -> app-1..3 ->
  nginx), deploy/initdb.sql (iag_app DML-only role), deploy/nginx.conf
  (SPA + /api LB), Dockerfile (node24 build -> python:3.12-slim, runtime
  invokes /app/.venv/bin/* DIRECTLY ‚Äî bare python/alembic and `uv run`
  both fail in the image: not on PATH / cache perms under USER nobody).
  nginx on host port **8090** (8080 is occupied by opik-backend-1).
- Kill-a-replica proof PASSED: login -> audit chain valid -> stop
  iag-app-2 -> health + chain + dashboard all OK through survivors ->
  app-2 restarted, rejoined healthy. Stateless session portability
  proven (cookie minted pre-kill honored post-kill).
- 3 real bugs the container run surfaced (all masked by SQLite/tests):
  1. alembic 0001 had `import *` INSIDE functions ‚Äî compile-time error
     ast.parse cannot see. Gate upgrade: use py_compile, not ast.parse.
  2. Aware datetime defaults into naive TIMESTAMP columns ‚Äî asyncpg
     rejects (Postgres), aiosqlite silently accepts. Fixed: utcnow()
     returns NAIVE UTC (models/identity.py) + 6 call sites; convention:
     DB layer is naive-UTC everywhere.
  3. uv cache init fails under USER nobody ‚Üí runtime uses venv binaries.
- Stack is RUNNING now (5 containers healthy). Login: admin /
  Admin123!secret at http://localhost:8090. Teardown: docker compose
  down (add -v to also drop data + seeded static volume).
- Git: initialized, commit ec90389 (70 files), identity
  ponofinlayson-web + openhands co-author. No remote configured.
- Next candidates (post-v1 spec): reminder-email task queue inside app
  replicas (never a separate writer), SoD rules, external chain
  anchoring, real LDAP/Entra connectors. Also consider: prod-grade
  secrets (env file / secret manager) ‚Äî compose currently hardcodes
  dev passwords, fine for local stack, not for any real deployment.

### 2026-08-17 (frontend session)
- Tests green 8/8; prod drivers asyncpg 0.31.0 + psycopg2-binary 2.9.12 added.
- Frontend built & verified end-to-end: React 18 + TS + Vite SPA, typed
  client mirroring all routers, 9 views (Login/Dashboard/Identities/
  Sources/Entitlements/Campaigns/CampaignDetail/Reviews/Audit).
  `npm install` + `tsc -b` clean + `vite build` ‚Üí backend/static/
  (192 kB js / 60.2 kB gzip).
- E2E smoke via FastAPI TestClient (in-process, no sockets ‚Äî sandbox
  blocked uvicorn binds winerror 10013): create_all ‚Üí bootstrap ‚Üí
  GET / serves SPA ‚Üí login 200 ‚Üí /me 200 admin/system_admin ‚Üí
  /api/dashboard 200. File: backend/smoke_testclient.py (kept for reuse;
  rerun = fresh sqlite dev db + bootstrap, see below).
- Campaign lifecycle UI (preview/stage/start/cancel/metrics) was missing
  from original 8 views; added CampaignDetail.tsx at /campaigns/:id with
  DRY-RUN preview table (skips w/ reasons + reviewer sample).
- "Search name‚Ä¶" placeholder was never broken ‚Äî hex dump proved E2 80 A6
  present; terminal font renders ellipsis as '.'. Trust bytes, not display.
- Corruption guard still real: ~6 new junk-marker incidents this session
  (.ts-holder, TS_TH_MARK, router_page_guard_fn, .ts-review-id etc.),
  all caught by post-write verification + tsc. Keep writes ‚â§120 lines.

## Reminder-email task queue ‚Äî FORK A RATIFIED (2026-08-17, pre-build)

Contract comes from the frozen specs; do not re-derive:
- ARCHITECTURE.md slot: "Email: outbound only, via an in-app task queue.
  Never a writer." Resilience contract 4: "No cron, no schedulers, no
  sidecars with write credentials. Future reminder emails must run inside
  an app replica as a task queue, never as a separate writer."
- REQUIREMENTS.md: email templates/delivery were DEFERRED from v1 (kept as
  design slot), reminder emails are the v2 build of that slot. So:
  outbound only, no inbound processing, no read receipts.
- Multi-replica reality: 3 app replicas; whatever picks up reminder work
  must be safe with all three running (idempotent claim semantics or
  single-flight locking). Sessions/cookies are stateless; nothing shared
  but Postgres.

DECISION (user-ratified 2026-08-17): fork A. Do not present A-vs-B again;
build A. Spec follows; the constraints block above it still applies.
- A. DB table `email_outbox` + a periodic in-replica worker loop (asyncio
  task started at app startup) that claims due rows and sends. Claim via
  `UPDATE ... WHERE status='pending' ... RETURNING` or SELECT FOR UPDATE
  SKIP LOCKED so replicas don't double-send.
Full fork-A build spec:

Model ‚Äî `EmailOutbox` (models/email.py, table `email_outbox`, migration
0003, explicit DDL like 0002):
- id PK; campaign_id FK campaigns CASCADE; review_id FK reviews CASCADE
  (one reminder per review ‚Äî the natural dedup key); reviewer_id FK
  users CASCADE; recipient TEXT (resolved at enqueue time); subject TEXT;
  body TEXT; due_at TIMESTAMP naive-UTC; sent_at TIMESTAMP null;
  attempts INTEGER default 0; status TEXT pending/sending/sent/failed/
  cancelled.
- Enqueue: on campaign start ONLY (v1): one pending row per review
  created, due_at = now + IAG_REMINDER_DELAY_MINUTES (default 60).
  Campaign cancel marks outstanding pending rows cancelled.

Worker ‚Äî `app/core/email_worker.py`, asyncio task per replica started
at app startup (FastAPI lifespan in main.py):
- Loop: sleep IAG_REMINDER_POLL_SECONDS (default 60) ‚Üí claim due rows ‚Üí
  send ‚Üí finalize. 
- Claim: SELECT ... FOR UPDATE SKIP LOCKED on Postgres (multi-replica
  safe); SQLite tests serialize, acceptable. Claim TX marks rows
  'sending' + attempts+1. SEND HAPPENS OUTSIDE THE CLAIM TX (network
  I/O never holds DB locks); finalize TX commits sent/failed. Replica
  death between claim and finalize leaves rows 'sending'; reclaim after
  IAG_REMINDER_STUCK_MINUTES (default 15).
- Retry: failed sends retry next poll up to IAG_REMINDER_MAX_ATTEMPTS
  (default 3), then dead-letter (status stays 'failed').
- Send: SMTP via IAG_SMTP_HOST/PORT/USER/PASSWORD/FROM. DEV MODE: host
  unset ‚Üí log-only delivery (log the email, mark sent) ‚Äî how the stack
  runs today; keeps smoke honest without an SMTP server. If host IS set,
  creds validated at boot (fail-fast, secrets discipline).
- Audit: one 'email_sent' entry per delivered row via append_audit
  (same-transaction, house pattern). Failed attempts get 'email_failed'
  entries; actor = system (actor_id None, actor_username 'system').

API surface (read-only, CertAdminUser):
- GET /api/reminders/outbox ‚Äî paged, filter campaign_id + status
- GET /api/campaigns/{id}/reminders ‚Äî rows for one campaign

Tests (SQLite, log-only send path; no real SMTP):
- enqueue-on-start: start creates one pending row per review, due_at ok
- claim-and-send: due row ‚Üí sent, audit 'email_sent', sent_at set
- no-double-send: second claim returns nothing (SKIP LOCKED proven on
  Postgres via live script)
- retry-then-dead-letter: failures retry to max attempts then stop
- cancel-cancels: campaign cancel ‚Üí outstanding rows cancelled
- boot: worker task starts with TestClient context, no error

Live proof (stack): scripts/live_reminder_check.py ‚Äî login ‚Üí start
campaign with pending reviews ‚Üí outbox rows exist via API ‚Üí wait for
sent (log-only) ‚Üí audit chain still valid.

Non-goals (do not build): templates/editing UI, HTML email, inbound
mail, read receipts, per-reviewer digesting, email prefs. One plain-
text reminder per pending review, one time, v1.

## Known design decisions (context you'd otherwise lack)

- SQLite for tests / Postgres for prod, same models: only portable column
  types used. DateTime columns are timezone-naive in DB but set from
  datetime.now(timezone.utc); AuditEntry.ts hashes ISO format with tz.
- Session auth = HMAC-SHA256 signed token in httpOnly cookie "iag_session".
  Stateless ‚Äî any replica validates any session (that's what makes the 3
  replicas interchangeable). Token payload: sub/username/role/exp.
- Audit chain: record_hash = SHA256(prev_hash + canonical_json(payload));
  payload keys: action, actor_id, actor_username, details (canonical JSON
  string), entity_id, entity_type, ts (ISO 8601 with tz). GENESIS = 64 zeros.
  append_audit() reads last entry INSIDE the caller's transaction and
  commits with it ‚Äî change and audit land atomically or not at all.
- Campaign start deletes existing reviews for that campaign BEFORE
  inserting new ones (re-start = regenerate). Reviewer resolution:
  source_owner mode uses source's owner User (skip + report if none);
  manager mode uses identity's manager's User, fallback = campaign creator.
- Campaign auto-completes when last review is decided (submit path checks
  done==total and flips status; bulk-submit does NOT auto-complete ‚Äî
  acceptable for skeleton, noted).
- Entitlement natural key = (data_source_id, source_column, source_value
  lowercase). Catalog IDs ENT-00001+ from count+1 (race-safe enough for
  single-writer; note for later if concurrent imports).
- conftest seeds admin INSIDE the override's first call (same event loop
  as TestClient) to avoid aiosqlite cross-loop errors. test_db_path is
  exposed on app.state for the tamper test's raw sqlite3 access.

## Sequence for next session

1. Recover terminal; run pytest; fix until green (test_auth, test_workflow,
   test_audit_tamper ‚Äî 10 tests total).
2. uv add psycopg2-binary asyncpg (prod drivers) ‚Äî verify db_url_sync
   maps postgresql+asyncpg ‚Üí postgresql+psycopg2 for Alembic.
3. Frontend: Vite React-TS scaffold, typed client from /api/openapi.json,
   views per REQUIREMENTS.md section 4, build ‚Üí backend/static/.
4. Docker: Dockerfile (multi-stage node‚Üípython), compose.yaml (5 services
   per contract), nginx.conf, smoke.sh.
5. docker compose up --build; run smoke.sh; prove kill-a-replica survives.
6. git init + first commit. Report to user with [V]-labeled results.

## User's exact words for the new chat

"Continue the IAG rebuild at D:\Projects\iag ‚Äî read HANDOFF.md first."

## USER DECISIONS RATIFIED (2026-08-18, session close)

1. **Fresh-volume reset: ACCEPTED.** The next session may run `docker
   compose down -v` immediately to prove migration 0003 on an empty volume.
   All accumulated local data (identities, campaigns, audit history) is
   knowingly sacrificed. Do not re-ask; just do it as step 1 and verify via
   psql (`alembic_version=0003` + `email_outbox` present), then proceed to
   the feature-2 spec.
2. **Arc order reaffirmed:** connectors (2) → remediation (3) → API keys
   (4) → risk/PDF/SIEM (5) → SCIM-class (6). Design spec required before
   each of 3–6; feature 2 has a reserved architecture slot and can proceed
   to spec directly.
