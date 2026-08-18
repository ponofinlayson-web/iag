# IAG v2 Rebuild — Handoff

Continuation point for a fresh agent session. Read this fully before acting.
Project root: `D:\Projects\iag` (the v1 codebase it replaces is `D:\IAM-Simplified` —
read-only reference; copy NO code from it).

## Mission

Clean-room rebuild of the user's first project (an IAM governance tool) as an
exceptional, sound web app. Specs already derived and frozen:
- `REQUIREMENTS.md` — domain rules, roles, invariants, resilience contract
- `ARCHITECTURE.md` — stack, container topology, design slots

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

backend/app/core/settings.py — pydantic-settings, IAG_* env aliases,
  db_url_sync() conversion, validate_secrets() fail-fast
backend/app/core/security.py — bcrypt (passlib) + scrypt fallback,
  HMAC-signed session tokens (new_session_token / verify_session_token)
backend/app/core/audit_service.py — append_audit() same-transaction append,
  verify_chain() full-chain walk; canonical_json in models/audit.py
backend/app/db.py — async engine, Base, get_db, SQLite FK pragma
backend/app/models/*.py — identity, user (Role enum), source (DataSource,
  Account, SourceType), entitlement (natural key uq constraint),
  campaign (Campaign/Review + status enums), audit (AuditEntry hash chain)
backend/app/routers/deps.py — get_current_user, require_roles, Annotated
  aliases: AdminUser, CertAdminUser, AnyUser, DbSession; exports _settings
backend/app/routers/auth.py — login (lockout), me, logout, change-password
backend/app/routers/identities.py — list/get/create/update/delete,
  /import CSV upsert, /export CSV, manager-cycle guard (_check_cycle)
backend/app/routers/sources.py — CRUD, /upload CSV (natural-key entitlement
  upsert), accounts list, link, bulk-link by username|email
backend/app/routers/entitlements.py — list, /stats, PUT privilege
backend/app/routers/campaigns.py — CRUD, /preview (DRY-RUN reviewer
  resolution — v1's best idea), stage, start (clears+regenerates reviews),
  cancel, /metrics
backend/app/routers/reviews.py — queue, count, history, detail, submit
  (revoke REQUIRES comment), bulk-submit, campaign auto-complete on last
backend/app/routers/audit.py — list (audit/system_admin/cert_admin only),
  /verify, /export CSV
backend/app/routers/dashboard.py — portfolio + personal workload counts
backend/app/main.py — FastAPI assembly, JSON logging, /api/health, SPA mount
backend/app/bootstrap.py — one-shot first-admin creator (env creds)
backend/alembic.ini, alembic/env.py, alembic/script.py.mako
backend/alembic/versions/0001_initial.py — metadata-driven create_all
backend/tests/conftest.py — per-test SQLite file DB, in-loop seeding,
  admin_client fixture, exposes app.state.test_db_path
backend/tests/test_auth.py — health, 401s, lockout, cookie, change-password
backend/tests/test_workflow.py — full E2E: import→source→upload→bulk-link→
  campaign→preview→stage→start→reviews→auto-complete→chain verify
backend/tests/test_audit_tamper.py — raw-SQL mutation must break chain
backend/pyproject.toml — deps + pytest config (pythonpath=["."])
uv.lock + .venv exist — `uv sync` completed successfully [V]

## Unverified / in-flight

Nothing. All six build phases complete and verified this session.

## Session log (newest first)

### 2026-08-17 (SoD session — feature complete)
- SoD engine shipped per ARCHITECTURE design slot: PURE READ-SIDE. Given
  identity entitlements + active rules -> violations, computed per request.
  No persistence of violations, no auto-revoke, no background anything.
  Reviewers decide; the engine informs.
- New: models/sod.py (SodRule: two entitlement FKs CASCADE, severity,
  is_active, unique name), alembic 0002 (EXPLICIT DDL — not create_all —
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
  — one account carries one entitlement ref, so a toxic pair needs two
  accounts — preview flags with named pair, review detail shows, approve
  stays manual, inactive rule flags nothing).
- LIVE PROOFS: migration 0002 applied on the EXISTING volume without down
  -v (psql: alembic_version=0002, sod_rules table present) — the [H] from
  the secrets session is now [V]. smoke.sh PASS incl. kill-a-replica.
  scripts/live_sod_check.py: login -> GET rules -> POST rejected 400 ->
  chain valid, against real Postgres.
- Trap (recurring): file_editor corrupted a line in routers/sod.py
  (walrus-junk in delete_rule) — caught on read-back, fixed. Also wrote an
  unfinished stub test the first time. Post-write verification stays
  mandatory. Migrate container's alembic output is swallowed by a broken
  log format (`%(levelname)` lines) — prove migrations via psql, not logs.
- Commit 83bc69d. Stack running @ :8090, 6 commits total.
- Next up: reminder-email task queue — pinned constraints + open design
  fork in the section below. Later: external chain anchoring, real
  LDAP/Entra connectors, rule deactivation UI polish.

### 2026-08-17 (secrets session — candidate #1 done)
- All hardcoded dev secrets removed from tracked files. compose.yaml uses
  ${VAR:?err} for IAG_POSTGRES_PASSWORD / IAG_APP_DB_PASSWORD /
  IAG_SECRET_KEY / IAG_BOOTSTRAP_ADMIN_PASSWORD — missing .env means
  compose refuses to start (verified). Real values live in gitignored
  .env (generated by scripts/gen_env.py); .env.example is the template.
- deploy/initdb.sh (new): entrypoint wrapper passes IAG_APP_DB_PASSWORD
  into initdb.sql as psql var :'app_password'. The .sql is mounted at
  /opt/initdb (NOT initdb.d) so the entrypoint runs it exactly once.
  Wrapper must use psql -U "$POSTGRES_USER" — default role 'postgres'
  does not exist in this stack (POSTGRES_USER=iag_migrate).
- Two real traps the fresh-volume verification caught:
  1. The postgres entrypoint SWALLOWS initdb.d script failures — stack
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

### 2026-08-17 (stack + proof session — ALL TASKS DONE)
- Docker stack built & verified: compose.yaml (db -> migrate -> app-1..3 ->
  nginx), deploy/initdb.sql (iag_app DML-only role), deploy/nginx.conf
  (SPA + /api LB), Dockerfile (node24 build -> python:3.12-slim, runtime
  invokes /app/.venv/bin/* DIRECTLY — bare python/alembic and `uv run`
  both fail in the image: not on PATH / cache perms under USER nobody).
  nginx on host port **8090** (8080 is occupied by opik-backend-1).
- Kill-a-replica proof PASSED: login -> audit chain valid -> stop
  iag-app-2 -> health + chain + dashboard all OK through survivors ->
  app-2 restarted, rejoined healthy. Stateless session portability
  proven (cookie minted pre-kill honored post-kill).
- 3 real bugs the container run surfaced (all masked by SQLite/tests):
  1. alembic 0001 had `import *` INSIDE functions — compile-time error
     ast.parse cannot see. Gate upgrade: use py_compile, not ast.parse.
  2. Aware datetime defaults into naive TIMESTAMP columns — asyncpg
     rejects (Postgres), aiosqlite silently accepts. Fixed: utcnow()
     returns NAIVE UTC (models/identity.py) + 6 call sites; convention:
     DB layer is naive-UTC everywhere.
  3. uv cache init fails under USER nobody → runtime uses venv binaries.
- Stack is RUNNING now (5 containers healthy). Login: admin /
  Admin123!secret at http://localhost:8090. Teardown: docker compose
  down (add -v to also drop data + seeded static volume).
- Git: initialized, commit ec90389 (70 files), identity
  ponofinlayson-web + openhands co-author. No remote configured.
- Next candidates (post-v1 spec): reminder-email task queue inside app
  replicas (never a separate writer), SoD rules, external chain
  anchoring, real LDAP/Entra connectors. Also consider: prod-grade
  secrets (env file / secret manager) — compose currently hardcodes
  dev passwords, fine for local stack, not for any real deployment.

### 2026-08-17 (frontend session)
- Tests green 8/8; prod drivers asyncpg 0.31.0 + psycopg2-binary 2.9.12 added.
- Frontend built & verified end-to-end: React 18 + TS + Vite SPA, typed
  client mirroring all routers, 9 views (Login/Dashboard/Identities/
  Sources/Entitlements/Campaigns/CampaignDetail/Reviews/Audit).
  `npm install` + `tsc -b` clean + `vite build` → backend/static/
  (192 kB js / 60.2 kB gzip).
- E2E smoke via FastAPI TestClient (in-process, no sockets — sandbox
  blocked uvicorn binds winerror 10013): create_all → bootstrap →
  GET / serves SPA → login 200 → /me 200 admin/system_admin →
  /api/dashboard 200. File: backend/smoke_testclient.py (kept for reuse;
  rerun = fresh sqlite dev db + bootstrap, see below).
- Campaign lifecycle UI (preview/stage/start/cancel/metrics) was missing
  from original 8 views; added CampaignDetail.tsx at /campaigns/:id with
  DRY-RUN preview table (skips w/ reasons + reviewer sample).
- "Search name…" placeholder was never broken — hex dump proved E2 80 A6
  present; terminal font renders ellipsis as '.'. Trust bytes, not display.
- Corruption guard still real: ~6 new junk-marker incidents this session
  (.ts-holder, TS_TH_MARK, router_page_guard_fn, .ts-review-id etc.),
  all caught by post-write verification + tsc. Keep writes ≤120 lines.

## Reminder-email task queue — constraints pinned (2026-08-17, pre-build)

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

Design fork left OPEN for the next session (both preserve the contract):
- A. DB table `email_outbox` + a periodic in-replica worker loop (asyncio
  task started at app startup) that claims due rows and sends. Claim via
  `UPDATE ... WHERE status='pending' ... RETURNING` or SELECT FOR UPDATE
  SKIP LOCKED so replicas don't double-send.
- B. Recompute-don't-persist: compute who needs reminding on the fly from
  reviews pending + deadline, no outbox table, send directly. Simpler, no
  new state, but no retry/dedup record and every replica might send.

My recommendation (not yet user-ratified): A with a strict minimal shape —
outbox table written ONLY by the API on campaign start/schedule change,
worker claims with SKIP LOCKED, SMTP settings via IAG_* env (fail-fast
like other secrets), audit entry on send attempt or per batch. But the
user is a novice vibe-coder who values being told when something is
fragile: present A vs B honestly, let them pick.

Regardless of fork: SMTP creds are secrets (.env, gitignored, gen_env.py
updated), delivery is outbound only, no scheduler sidecar, migrate
container owns any new table's migration, tests run on SQLite with no
real SMTP (stub/fakemail capture), py_compile gate on every write.

## Known design decisions (context you'd otherwise lack)

- SQLite for tests / Postgres for prod, same models: only portable column
  types used. DateTime columns are timezone-naive in DB but set from
  datetime.now(timezone.utc); AuditEntry.ts hashes ISO format with tz.
- Session auth = HMAC-SHA256 signed token in httpOnly cookie "iag_session".
  Stateless — any replica validates any session (that's what makes the 3
  replicas interchangeable). Token payload: sub/username/role/exp.
- Audit chain: record_hash = SHA256(prev_hash + canonical_json(payload));
  payload keys: action, actor_id, actor_username, details (canonical JSON
  string), entity_id, entity_type, ts (ISO 8601 with tz). GENESIS = 64 zeros.
  append_audit() reads last entry INSIDE the caller's transaction and
  commits with it — change and audit land atomically or not at all.
- Campaign start deletes existing reviews for that campaign BEFORE
  inserting new ones (re-start = regenerate). Reviewer resolution:
  source_owner mode uses source's owner User (skip + report if none);
  manager mode uses identity's manager's User, fallback = campaign creator.
- Campaign auto-completes when last review is decided (submit path checks
  done==total and flips status; bulk-submit does NOT auto-complete —
  acceptable for skeleton, noted).
- Entitlement natural key = (data_source_id, source_column, source_value
  lowercase). Catalog IDs ENT-00001+ from count+1 (race-safe enough for
  single-writer; note for later if concurrent imports).
- conftest seeds admin INSIDE the override's first call (same event loop
  as TestClient) to avoid aiosqlite cross-loop errors. test_db_path is
  exposed on app.state for the tamper test's raw sqlite3 access.

## Sequence for next session

1. Recover terminal; run pytest; fix until green (test_auth, test_workflow,
   test_audit_tamper — 10 tests total).
2. uv add psycopg2-binary asyncpg (prod drivers) — verify db_url_sync
   maps postgresql+asyncpg → postgresql+psycopg2 for Alembic.
3. Frontend: Vite React-TS scaffold, typed client from /api/openapi.json,
   views per REQUIREMENTS.md section 4, build → backend/static/.
4. Docker: Dockerfile (multi-stage node→python), compose.yaml (5 services
   per contract), nginx.conf, smoke.sh.
5. docker compose up --build; run smoke.sh; prove kill-a-replica survives.
6. git init + first commit. Report to user with [V]-labeled results.

## User's exact words for the new chat

"Continue the IAG rebuild at D:\Projects\iag — read HANDOFF.md first."
