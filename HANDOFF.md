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
backend/app/routers/deps.py ‚Äî get_current_user (cookie OR Bearer API-key
  principal), ApiKeyPrincipal, read-only + keys-manage-keys chokes,
  require_roles, Annotated aliases: AdminUser, CertAdminUser, AnyUser,
  SessionUser (cookie-only), DbSession; exports _settings
backend/app/routers/auth.py ‚Äî login (lockout), me/logout/change-password
  (all SessionUser; logout no longer anonymous)
backend/app/models/apikey.py ‚Äî ApiKey (name/prefix/hash/role/is_active/
  expires_at/last_used_at), sa.Enum(Role) name-storage
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

## Current status

FEATURE 6 Phase A COMPLETE (session 17, d529760). Spec
RATIFIED (session 16) at SPECS/feature-6-scim-provisioning-
enforcement.md. Built this phase: models/scim.py (ScimSettings
single-row, SHA-256 token_hash at rest, enabled=false default);
models/remediation.py (ENFORCE action + ENFORCE_TARGETS + rule
target String(20) nullable, null=remove_entitlement); alembic
0008 (scim_settings owned table + guarded rules.target, 0004
inspector pattern); core/scim.py pure helpers (honest SPC,
EQ-only fullmatch filter parser, Identity<->SCIM mapping,
replace-only PATCH incl. Okta path-less shape, ScimError
envelope); tests/test_scim_core.py (36 tests). Suite 208/208
[V]. Migration 0008 APPLIED LIVE [V]: alembic_version=0008,
row (1, {"enabled": false}, null token), target column varchar
nullable - verified via psql, NOT container logs. NOTE:
iag-migrate image rebuilt this session; app replicas still on
the pre-feature-6 image (Phase A adds no runtime surface;
Phase B router rides the next rebuild). Docker daemon healthy
throughout (no crash this session). NEXT (fresh chat): Phase B
per spec build phases - SCIM protocol router (routers/scim.py,
prefix /api/scim/v2) + require_scim_token dependency (Bearer
only, constant-time, 503/401 SCIM envelopes) + integration
tests; green gate; commit; then rebuild app replicas so the
surface exists at nginx.
## Session log (newest first)

### 2026-08-22 (session 17): FEATURE 6 PHASE A (models + 0008 + core helpers)

- Commit d529760. Suite 208/208 (172 + 36 new) [V]. Stack
  healthy all session; daemon 29.7.2, no crash-loop.
- LIVE 0008 [V]: first run FAILED (NotNullViolation - raw
  op.execute INSERT bypasses ORM defaults; remediation_settings
  never hit this because it has no timestamp column). Fix: bind
  updated_at explicitly in the INSERT (naive-UTC). Postgres DDL
  transactional -> clean rollback, second run clean. LESSON:
  single-row settings migrations with NOT NULL timestamps must
  bind them in the seed INSERT; 0005 pattern is insufficient
  verbatim.
- Junk-gate hits on "placeholder" were all intentional v1-defect
  references in docstrings/tests - gate is heuristic, read the
  lines before "fixing".
- test double _Identity (attr-bag) keeps mapping tests DB-free;
  one round-trip test exercises ScimSettings + rule.target
  against real SQLite create_all (current metadata, so target
  column present - matching the guard's fresh-volume path).

### 2026-08-22 (session 16): FEATURE 6 RATIFIED - PHASES A-E UNLOCKED

- User rulings on D1-D8: D1 bundle (one feature, phases A-E). D3
  the only debate - user required the join key to align to the
  authoritative source's schema (AD may use UPN; Entra differs)
  and suggested schema discovery/introspection. Resolved and
  ratified: alignment at the VALUE level (externalId is the IdP's
  own declared key -> employee_id verbatim); directory side is
  already per-source (connector_config account_attr etc. -
  verified connectors.py:106 [V]); discovery designed out
  (fixed ops + per-source config is the mechanism); invariant
  paragraph + end-user docs now ratified spec content. D2, D4-D8
  accepted as drafted; D8 deps claim fact-checked against
  pyproject.toml BEFORE recording [V].
- Spec edits: header DRAFT->RATIFIED, D3 amendment block,
  schema-alignment invariant paragraph, "End-user documentation"
  deliverable section (docs/admin-guide.md + UI help text, Phase
  C), Phase C line updated. ARCHITECTURE.md design-slots line
  added. pytest 172/172 re-run (house rule) [V].
- ENV: Docker daemon relaunched (Start-Process Docker Desktop)
  after crash-loop death at last close; server 29.7.2 up [V].
- NEXT (fresh chat): Phase A per spec build phases. Exact words
  below.

### 2026-08-22 (session 15): FEATURE 6 SPEC DRAFTED (awaiting ratification)

- Task per staged words: draft feature-6 spec, commit, STOP. Done:
  SPECS/feature-6-scim-provisioning-enforcement.md (505 lines,
  commit 7b2eb46), D1-D8 open. Zero code written (arc rule).
- Spec shape: Part 1 inbound SCIM 2.0 server (/api/scim/v2 - under
  /api so nginx needs no new location; token-authed with SHA-256
  hash-at-rest reveal-once token; audit actor_username="scim" - the
  first non-human chain actor; SCIM id = employee_id). Part 2
  enforcement write-back (action_type=enforce rides the remediation
  state machine - third delivery arm in run_pass; rule target
  remove_entitlement/disable_account, migration 0008 = scim_settings
  table + rules.target column; adapter write-backs ldap/entra/sql;
  already-clean = success idempotency; mirror untouched by design).
  Part 3 management surface + minimal frontend.
- Forensics: v1 scim_service.py read in full (15,471 bytes). v1 was
  INBOUND-ONLY (no outbound enforcement existed anywhere in v1) -
  enforcement half designed fresh against feature-2 adapters. v1
  defects designed out: reversibly-encrypted token at rest, IdP-
  mints-login-accounts (default ON in v1; unimplementable in v2 -
  no user-admin endpoint exists, verified), hard-delete deprovision,
  parallel un-chained SCIMEvent log, SPC advertising Groups + sort
  that never existed, phone=emails[0].value placeholder, unanchored
  filter regex.
- v2 facts verified during drafting: remediation_rules.action /
  action_type are plain VARCHAR (no enum surgery for enforce);
  Account.entitlement_id stays null for connector accounts (sync
  never sets it - per-account entitlement membership is not stored;
  recomputed from directory each run) - affects what enforcement can
  resolve and the mirror-drift section; no user-management endpoint
  exists (only bootstrap mints logins) - auto-create-login designed
  out; remediation snapshot carries entitlement_name from
  Account.entitlement_id (CSV grain) - connector-source revocations
  may have null entitlement_name, handled.
- Spec defects caught by self-review before commit: unneeded
  ALTER TYPE for a 'scim' SourceType (cut - Identity.source is plain
  String); auto_create_login described as implementable (cut to
  designed-out with the no-user-admin fact); LDAP test specced
  against glauth in pytest (fixed to MOCK strategy - pytest runs
  without Docker, house rule); missing externalId 409 on POST;
  PATCH path-less value-object form added (Okta's actual depro
  shape); filter regex anchored (v1 accepted trailing junk).
- ENV: Docker daemon DOWN at session open (known crash-loop; psql
  fact-checks skipped - spec work needed no stack). Terminal wedged
  once on an inline $_-in-string parse error; reset=true cleared it.
  Corruption mode silent (chunked writes + read-back gates, all
  clean; only fix was the terminal wedge, not file corruption).
- NEXT (fresh chat): ratification. User rules on D1-D8 -> record
  under USER DECISIONS RATIFIED -> add ARCHITECTURE.md design-slots
  line -> Phases A-E may proceed (A = migration 0008 + core/scim.py
  pure helpers + models + unit tests).


### 2026-08-22 (session 14): FEATURE 5 PHASE E - FEATURE COMPLETE

- Three live-check scripts written + gated (new scripts/
  verify_script_gate.py: py_compile + junk grep + delimiter balance
  after every write - corruption mode stayed silent this session).
- Stack rebuilt (docker compose up -d --build); Docker daemon died
  seconds after the first build finished (the known crash-loop);
  Start-Process relaunch + restart policies brought everything back
  healthy [V]; fresh image digests verified on all 3 replicas.
- Proofs (order risk -> report -> siem, each seeds unique-tag data):
  LIVE RISK CHECK PASS - deterministic risky identity (5 very_high
  accounts over 4 entitlements, 3 SoD rules, no manager) scores
  exactly 82.5 critical by hand-computed engine math; clean identity
  0.0; two runs; summary/snapshots/trend/band-filter asserts.
  LIVE REPORT CHECK PASS - campaign with 1 approve + 1 revoke-with-
  comment + 1 pending; report JSON shape (completion/decisions/
  workload/revocation detail/risk block); report.csv == metrics
  decisions; SPA shell served at /campaigns/:id/report.
  LIVE SIEM CHECK PASS - 209 entries walked in 9 pages with
  catch-up-to-head loop; CLIENT-SIDE chain recompute over the whole
  feed (re-canonicalize details, ts + "+00:00"); three-way
  consistency feed == CSV export == server verify (heads equal);
  report_viewer key 403 on feed; revoked key 401.
- REAL BUG FOUND + FIXED by the live proof: /api/risk/trend/{id}
  ordered by computed_at; a Docker-VM clock step stamped the LATER
  run ~44ms EARLIER (live capture: run2 .840 < run1 .884), inverting
  history. Fixed to order by id (ids monotonic per run TX);
  regression test test_trend_survives_clock_step. Suite 171 -> 172.
- Script gotchas hit: (1) list filter param is `q`, NOT `search`
  (identities + entitlements) - wrong param silently returns ALL
  rows; (2) source_owner campaigns SKIP accounts whose source has no
  owner-with-login at start (no creator fallback in that mode - only
  manager mode falls back) - proof sources must set
  owner_employee_id=E-ADMIN; (3) bulk-link matches exact username
  only - suffixed accounts need per-account PUT link.
- Residue on live DB (expected, per house convention): seeded
  risk/report data, campaign 5 staged-but-empty (first report-check
  attempt), 2 revoked probe keys, snapshot history for 3+ runs.

### 2026-08-21 late (session 13): FEATURE 5 PHASES C+D

- Phase C (1af1d8a): SIEM feed live in routers/audit.py - GET
  /api/audit/feed (JSONL, after_id cursor, limit 500/max 5000,
  X-IAG-Last-Id + X-IAG-Head headers, bounded pre-fetch then
  streamed) + GET /api/audit/feed/stats (totals + chain_head +
  chain_valid). details ships parsed (nested JSON) with raw-string
  fallback. 7 tests incl. client-side chain recompute walking
  pages (the transportable-evidence proof: feed alone suffices to
  verify integrity; recompute must re-canonicalize details and
  append +00:00 to naive ts).
- Phase D (9dec9bb): report endpoints in campaigns.py (GET
  /{id}/report JSON: header/completion/decisions/reviewer workload
  pending-desc/revocations detail/risk block from latest run;
  GET /{id}/report.csv streamed). Frontend: Risk.tsx (summary
  cards, top-10 factor drill-out, snapshots w/ band+department
  filters + paging, trend sparkline panel, Compute now cert_admin+),
  CampaignReport.tsx (/campaigns/:id/report, print CSS + window.print
  + CSV link), Report button on CampaignDetail, Risk nav (4 read
  roles). client.ts risk namespace + report methods.
- Gates: pytest 171/171 (166 after C, 171 after D), TSC 0 first
  pass, vite build -> backend/static.
- GOTCHAs hit: (1) corruption mode ACTIVE this session - 5 garbled
  writes (mangled keys, stray tokens like "Discipline:", junk
  expressions) caught by read-back/py_compile/junk-grep EVERY time
  before commit; chunks stayed small; (2) SQLAlchemy Row unpacking:
  multi-entity select rows unpack to plain columns - `for u, fn, ln
  in found` (NOT row.id); risk.py's whole-Row iteration is the
  exception; (3) CSV upload upserts per (source, account_value) -
  repeated account names collapse to ONE account (test fixture
  needs distinct account values); (4) queue items DO carry
  campaign_id; after a decision the queue shrinks - completed-
  campaign loops must submit idx 0 repeatedly.
- ENV: Docker Desktop fully dead at session start; Start-Process
  relaunch + restart policies brought the whole stack back [V].
  Stack healthy at close: all 3 replicas + db healthy.


### 2026-08-21 late (session 12): FEATURE 5 RATIFIED - BUILD STARTS

- User ratified D1-D8 as drafted ("Ratified"). Recorded in spec
  header, ARCHITECTURE.md design slots, ratified block below.
- Ratification commit 57e4f1a re-ran pytest 139/139 (doc-only
  house rule).
- Phase A (980acb7): migration 0007 + models/risk.py + pure
  core/risk_engine.py (7 signals, weights fixed, caps at weight
  per signal, bands 25/50/75) + 12 unit tests (151/151).
- Phase B (ac6da0a): routers/risk.py (POST /runs 202 one-TX
  persist+audit, GET /snapshots filters, /trend/{id}, /summary),
  ReportViewer alias in deps.py, 8 API tests (159/159).
- LIVE: 0007 applied to real Postgres [V]. Docker Desktop
  crash-looped 3x (env watch item, details in in-flight).
- Session stopped at the A+B boundary per context-window protocol.


### 2026-08-21 (session 11): FEATURE 5 SPEC DRAFTED (no code)

- Agent services crashed+restarted mid-recon; state verified intact
  (tree clean @ 5cd3828, no orphan files) - zero rework needed.
- SPECS/feature-5-risk-reports-siem.md drafted (347 lines, 3 parts):
  risk scoring (7 signals, weights 20/20/20/10/10/10/10, bands
  25/50/75, run-grouped snapshots, pure risk_engine), campaign
  report (JSON GET + print-CSS SPA view + browser print-to-PDF,
  streamed CSV), SIEM pull-only feed (JSONL /api/audit/feed with
  after_id cursor + chain hashes, auditor API key, /feed/stats).
- v1 mining: risk_service.py (7-signal shape KEPT), siem_service.py
  (push forwarder DROPPED - threading.Thread, queue drops), report
  endpoints (v1 abandoned WeasyPrint mid-project for print-to-PDF -
  ADOPTED as v2 start). Report CSVs to server disk = designed out.
- 8 open decisions D1-D8; D1 = SIEM pull-only (the big one).
- pytest 139/139 re-run at draft commit (doc-only house rule).
- STOPPED FOR RATIFICATION - no feature-5 code until user replies.


### 2026-08-21 (session 10): FEATURE 4 PHASES C + D - FEATURE COMPLETE

- Phase C (31eecff): routers/apikeys.py (GET list newest-first prefix-
  only, POST create 201 full key ONCE, POST {id}/revoke idempotent;
  409 dup name; 400 unknown role / non-read role / past expires_at;
  Role(value) conversion per gotcha 1; audit in-TX). main.py: router
  mounted + app.openapi override adds bearerAuth scheme. Phase-B test
  flipped 404->403 (branch removed as planned). New
  test_apikeys_lifecycle.py (9 tests). Frontend: client.ts apiKeys
  namespace, ApiKeys.tsx (prefix mono, role chip, derived status,
  reveal-once modal + copy, two-step revoke confirm), nav + route
  system_admin-only, modal/mono/key-box styles added. TSC 0, vite
  build green, suite 139/139.
- Phase D: scripts/live_apikey_check.py run on rebuilt stack (all 3
  images rebuilt + force-recreated per gotcha 2). LIVE PASS: cookie
  create (key + prefix match) -> key cannot list keys 403 -> dashboard
  200 principal:api_key -> audit CSV export 200 non-empty ->
  identities 200 -> write 403 read-only -> key-mint 403 -> chain
  valid (143) -> revoke 200 -> revoked key 401 -> revoke idempotent
  -> chain valid (144). Revoked probe row left in DB (audit evidence,
  house convention).
- GOTCHAS learned (C/D):
  1. deps.py choke ORDER: method (read-only) fires before path
     (keys-manage-keys) for POSTs - a POST /api/api-keys 403s with
     "read-only", not "manage". Tests/scripts asserting the message
     must accept either.
  2. conftest lazy-tables: a raw second engine seeding a user works
     ONLY after some DB-backed request ran (401 request suffices);
     seeding before that = "no such table".
  3. vite build output goes to backend/static (SPA mount) - rebuilt
     containers pick the new frontend up via image rebuild, no
     separate static step.
  4. urlopen success path can return non-JSON (CSV export) - live
     scripts need a text fallback in their call() helper.

### 2026-08-21 (session 9): FEATURE 4 PHASES A + B BUILT

- Phase A (b9c499f): migration 0006 + models/apikey.py +
  core/apikeys.py pure fns (generate/parse/hash/verify/is_expired).
  Applied on live stack; alembic_version 0006, table verified.
- Phase B (53415f9): deps.py Bearer resolution -> ApiKeyPrincipal;
  read-only choke + keys-manage-keys choke at principal layer;
  SessionUser sweep (auth me/logout/change-password, reviews
  queue/count/history/submit/bulk-submit); dashboard mixed payload
  (portfolio real, personal zeroed, principal:api_key);
  last_used_at 60s throttle.
- Live proofs (Postgres, real stack): key reads dashboard 200 +
  audit 200 (auditor role), write choke 403, personal choke 403,
  last_used_at set + NOT rewritten within 60s; cookie login/me/
  dashboard unchanged. 3 replicas rebuilt.
- GOTCHAS learned (matter for C/D):
  1. sa.Enum(Role) stores enum NAMES (AUDITOR) not values
     (auditor) - raw psql seeds must use names; Phase C router
     must convert request strings via Role(value).
  2. Each app replica has its OWN image (iag-iag-app-1/2/3):
     docker compose build EVERY service then --force-recreate,
     or nginx round-robins stale code.
  3. /api/api-keys currently 404s for keys (router absent);
     Phase-C test flips its branch to == 403 once the router
     exists (test written to accept both, keyed off app.routes).
  4. alembic runs in-container as iag_app (no DDL rights): apply
     via docker exec -e IAG_DATABASE_URL=...iag_migrate... or the
     compose migrate service. PG enum TYPE 'role' exists (0001);
     0006 uses native_enum=False (VARCHAR) to avoid collision.
  5. logout now requires a session (D4) - anonymous logout is
     401; test_login_lockout updated accordingly.
- Phase-C reminders from spec: AdminUser-guarded POST create
  returns full key ONCE (201); role restricted to auditor +
  report_viewer (400 otherwise); 409 dup name; past expires_at
  400; revoke idempotent 200; audit api_key_created/revoked in
  the same TX; OpenAPI bearer scheme; frontend API Keys view
  (system_admin nav), client.ts apiKeys namespace; TSC + build.

### 2026-08-20 (session 8): FEATURE 4 SPEC RATIFIED (no code yet)

- SPECS/feature-4-api-keys.md drafted + committed (a31f529), then
  USER ratified ALL of D1-D7 as drafted (`All ratified`).
- Ratification recorded in 3 places: spec header (this edit),
  ARCHITECTURE.md design-slots line, this HANDOFF (in-flight section
  + ratified-decisions block below).
- Spec shape: Bearer keys iag_{id}_{token_urlsafe(32)}, SHA-256 at
  rest, constant-time compare, once-only reveal, soft revoke, rows
  permanent. Roles: auditor + report_viewer ONLY (create with other
  role = 400). READ-ONLY enforced at principal layer (non-GET/HEAD/
  OPTIONS = 403) + keys cannot manage keys (/api/api-keys = 403).
  Personal endpoints get SessionUser alias (cookie only); dashboard
  returns portfolio + zeroed personal block with principal:api_key.
  Audit: api_key_created/api_key_revoked lifecycle only; last_used_at
  throttled 60s. No new env vars, no compose change.
- Build phases: A model+migration 0006+core/apikeys.py pure fns;
  B deps.py principal wiring + SessionUser sweep + dashboard;
  C router+audit+OpenAPI bearer+frontend API Keys view;
  D live proof script + HANDOFF.
- pytest 108/108 re-run at spec commit (doc-only house rule).

### 2026-08-20 (session 7): FEATURE 3 COMPLETE (Phases A-E + live proofs)
- Spec ratified by USER; phases built: A models+migration (RemediationRule/
  RemediationAction/settings), B engine+trigger+worker, C none needed
  (email/webhook handled in worker), D API + frontend Remediation view,
  E live E2E proof.
- Live proof PASS (scripts/live_remediation_check.py, commit 14c6aae):
  SQL sync (planted table) -> campaign -> revoke -> trigger creates
  actions for matched rules AND default action when nothing matched ->
  worker executes: low-priv notify_owner email delivers without approval
  (real SMTP to aiosmtpd sink); high/very_high gated pending_approval
  (require_approval_for_high_risk setting); privilege-keyed webhook rule
  through approve -> real HTTP sink (host.docker.internal:8642);
  audit chain valid end-to-end.
- SMTP env added to .env: IAG_SMTP_HOST=host.docker.internal,
  IAG_SMTP_PORT=1025, IAG_SMTP_FROM=iag@localhost (+ dummy USER/PASSWORD
  because validate_smtp requires them; sink ignored auth).
- KNOWN NUANCE (design, not bug): connector-synced accounts keep
  Account.entitlement_id NULL (catalog-is-truth decision, feature 2).
  remediation entitlement_pattern therefore only matches CSV-imported
  accounts; privilege_level/data_source_id filters match everywhere.
  Documented here + in proof script comments.
- Reviews queue is reviewer-scoped (/api/reviews/queue), no
  list-by-campaign endpoint; source_owner mode resolves reviewer =
  source owner's identity, which MUST have a login (else review
  silently skipped in preview/start - campaign shows 0 reviews).
  Proof worked around by owning the source as admin's identity.
- All 3 replicas rebuilt on same image (round-robin stale-image 404s
  lesson re-applied); workers poll 30s.
- Gates at close: pytest 108/108, TSC 0, stack healthy, tree clean
  @ 14c6aae.
### 2026-08-20 (session 6): FEATURE 3 SPEC DRAFTED (no code)

- Commit 67aa079: `SPECS/feature-3-remediation.md` (319 lines,
  verified clean — no dup lines, no CRLF, no drafting artifacts).
  pytest 64/64 at draft time; tree clean except HANDOFF/memory edits.
- Scope mined from v1 `remediation_service.py` + tier5_models/tier5_api
  (read-only reference, no code copied): rules → matched actions →
  approval gate → execute. v1 actions: notify_owner, disable_account,
  remove_entitlement, webhook.
- **Core divergence (D1, needs ratification)**: v2 drops
  disable_account (mutating IAG's own auth/users because governance
  said so) and remove_entitlement (deleting mirror rows the next sync
  resurrects — violates feature-2 upsert-only/D3). Remediation =
  workflow layer (rules, approval, notify_owner email, webhook);
  enforcement write-back = feature 6 with its own spec.
- Design: trigger inside `_finalize` TX (single+bulk both flow
  through); pure matching engine `app/core/remediation_engine.py`
  (sod_engine shape); fork-A worker (SKIP LOCKED claim → deliver
  outside TX → finalize); action row IS the delivery record (no
  EmailOutbox reuse — constraint + semantic mismatch, D2); single-row
  `remediation_settings` table (D4); regex compiled at rule SAVE
  (fail-fast house style, D6).
- **AWAITING USER**: ratify/amend D1–D7 at end of spec. NO feature-3
  code before ratification. After ratification: phases A–E mirroring
  feature-2 cadence (models → trigger+engine → worker → API+frontend →
  live proofs), each ending pytest-green + stack healthy + commit.

### 2026-08-20 (session 5): FEATURE 2 COMPLETE (Phases C+D+E)

**Arc milestone: connectors shipped.** All spec phases green, 64/64
backend tests, TSC clean, stack healthy.

- **Phase C** (2fdeab2): `app/core/connectors.py` — registry
  (`get_adapter`) + LdapAdapter/EntraAdapter/SqlAdapter. ldap3 sync via
  to_thread; entra = httpx client-credentials with in-process token
  cache, paginated /users + transitiveMemberOf (ConsistencyLevel:
  eventual); sql = admin SELECT on throwaway engine, READ ONLY on
  Postgres, `$SECRET` URL placeholder. 16 new tests (ldap3 MOCK
  strategy, httpx MockTransport, real SQLite file through real engine).
- **Phase D** (3537151): API `PUT /api/sources/{id}/connector`
  (adapter validate() runs at save; empty secret keeps stored; interval
  drives next_sync_at; csv/xlsx 400), `POST .../sync` (409 in-flight),
  `GET .../syncs`, `GET /api/syncs/{id}`, `POST /api/syncs/{id}/cancel`
  (finished → 409). Source GET gains connector block. Frontend Sources
  view: config form per type, Sync now, status chip, run-history
  drawer. 11 new tests.
- **Phase E live proofs** (this session, both PASS):
  1. SQL self-referencing: `scripts/live_connector_check.py` — planted
     table in stack's own Postgres, connector as iag_app user, manual
     sync → worker pass → accounts+entitlements+valid chain.
  2. LDAP glauth: `scripts/live_ldap_check.py` — compose profile
     `connectors` (iag-glauth, deploy/glauth.cfg), svc-iag bind, manual
     sync → 3 accounts, 4 entitlements, chain valid.
- **Bugs found live** (both fixed, suite green):
  - ldap3 `receive_timeout` must be int — float reaches pyasn1's BER
    decoder as non-integer socket arg ("error: required argument is not
    an integer"). Fixed: `receive_timeout=int(timeout)`.
  - glauth groups nest as `ou=<name>,ou=groups,...` (not cn=) and users
    are `posixAccount` (not person). Adapter DN regex now accepts
    cn|ou first RDN; proof uses filter `(objectClass=posixAccount)`,
    account_attr `uid`. Real AD is unaffected (cn= + person).
- **Entra**: MockTransport-tested only; no local tenant. Manual
  checklist for first production use lives in
  `SPECS/feature-2-connectors.md` (live-proofs section).

Session gotchas (new): compose `build` must target `iag-app-1` (the
anchor service); after rebuild, `--force-recreate iag-app-2 iag-app-3`
too or nginx load-balances stale code into your proof. API DELETE
/api/sources/{id} has no cascade — live proofs clean up via psql
(DELETE FROM accounts/sync_runs/entitlements WHERE data_source_id ...)
then the source row.

### 2026-08-20 (session 4): Feature 2 Phase B shipped

- pytest **37/37** (10 new worker tests). Commit `cfbb92b`.
- `app/core/sync_worker.py` NEW — fork-A pattern adapted for connectors:
  `run_pass` = enqueue due sources (next_sync_at <= now, honoring per-source
  sync_interval_minutes) → claim ONE run (FOR UPDATE SKIP LOCKED + stuck
  reclaim: `syncing` older than connector_stuck_minutes) → fetch snapshot
  OUTSIDE any transaction → finalize (apply + ONE audit entry + schedule
  advance) in a single commit. Cancelled runs never resurrected (fresh-status
  check before finalize → skipped_cancelled).
- Apply semantics = CSV upload ground truth: natural-key entitlement upsert;
  per-(source,value) account upsert; last_seen bumps; missing counted not
  deleted; identity auto-link by exact username/email match; existing
  entitlement links never rewritten (Account.entitlement_id untouched —
  single-valued CSV shape vs multi-ent connector accounts; catalog is truth).
- Worker loop wired in lifespan alongside email worker (env != test only).
  Live proof: rebuilt stack, 3 replicas healthy, log line
  `"connector worker start (poll=60s)"` in app-1, zero tracebacks [V].
- **Footguns found (all test-side, worker code was correct):**
  1. `Settings(field=value)` kwargs are SILENTLY IGNORED — alias-only
     pydantic-settings mode (`populate_by_name` not set). Test variants
     must be built via env vars: `IAG_CONNECTOR_MAX_ROWS=1` + `Settings()`.
  2. After a rollback (duplicate-enqueue IntegrityError), SQLAlchemy
     expires the first instance — `r1.id` after rollback triggers greenlet
     error. Capture ids BEFORE the conflicting call.
  3. `await fetch()` where fetch is a plain lambda returning a snapshot →
     TypeError that the worker correctly fails the run on. Adapter contract:
     `async def fetch(config, secret) -> SyncSnapshot`.
  4. `asyncio.run()` nesting: all test bodies use the test_reminders
     pattern (fresh-engine factory per asyncio.run call).
- Scratch probe scripts cleaned up; `scripts/_check_0004_fresh.py` +
  `_check_0004_pg.py` REMOVED from repo (one-shot migration checks,
  superseded by live verification on the real stack).



### 2026-08-20 (session 3 — D2 deferred, Phase A built)

- **USER DECISION: D2 deferred to polish.** Secrets stored plaintext in
  DB (same trust boundary as .env SMTP creds), no `cryptography` dep now.
  Spec Secrets section + model WARNING comment document this + the polish
  backfill path. D1 deps therefore `ldap3` + `httpx` only. D1/D3/D4/D5/D6
  ratified as written.
- **Phase A SHIPPED** (migration 0004 + models + settings):
  - `backend/app/models/sync.py` — SyncRun model, partial unique index
    `uq_sync_run_inflight` (one in-flight run per source; `sa.text()`
    predicate — plain strings are NOT coerced by SQLAlchemy 2.x, that
    cost 13 test errors before the fix).
  - `source.py` — 5 connector columns (config, secret[plaintext, D2
    deferred], interval, next_sync_at, last_sync_at).
  - `settings.py` — IAG_CONNECTOR_{POLL_SECONDS=60, STUCK_MINUTES=15,
    TIMEOUT_SECONDS=30, MAX_ROWS=50000}; defaults sane so no compose change.
  - `0004_connectors.py` — guarded add_column (inspector check) +
    sync_runs + both indexes. 
- **Fresh-volume regression found & fixed**: 0001 builds tables from
  CURRENT metadata (create_all), so it now emits the connector columns;
  0004's blind add_column then died with duplicate-column on any fresh
  volume. Fix: inspector-guard in 0004. Proven BOTH paths: live stack
  upgrade (existing volume) [V] + scratch fresh-volume (SQLite sim AND
  throwaway postgres:16-alpine on :55432) [V]. Downgrade 0004→0003 clean.
  Proof scripts committed as reusable tooling:
  `backend/scripts/_check_0004_fresh.py` (SQLite) + `_check_0004_pg.py`
  (real PG, self-contained docker run/rm).
- pytest 27/27; stack rebuilt healthy at 0004; corruption guard earned
  its keep 4x this session (2 file_editor writes, 1 old_str, 1 scratch
  script) — all caught at write time, none reached a commit.

### 2026-08-20 (session 2 — reset proof + feature 2 spec)

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

## Sequence for next session (feature 5 build)

GATED ON RATIFICATION: if the user has not ratified D1-D8, stop and
ask. If ratified, record it in 3 places first (spec header,
ARCHITECTURE.md design-slots line: "Risk, reports, and SIEM feed:
read-side computation over governed data; SIEM is pull-only.",
ratified-decisions block below - same pattern as features 3-4).
Corruption guard ON for every write (AST-check python, junk-grep,
dup-line check; writes under ~120 lines).

1. Phase A [DONE 980acb7]: migration 0007 (risk_snapshots: run_id, identity FK
  SET NULL + frozen employee_id, score/band/signals/factors JSON,
  computed_at; indexes run_id + (identity_id, computed_at)),
  models/risk.py, core/risk_engine.py pure signals (sod_engine
  shape; settings kwarg gotcha - use env vars in tests), unit
  tests for all 7 signals + weights-sum + clamp + bands.
2. Phase B [DONE ac6da0a]: routers/risk.py (POST /runs 202 one-TX persist+audit
  risk_run_completed, GET /snapshots latest-run default + run_id/
  band/department/page, GET /trend/{id}, GET /summary),
  ReportViewer alias in deps.py (report_viewer/auditor/cert_admin/
  system_admin), integration tests incl. guards + API-key reads.
3. Phase C [DONE 1af1d8a]: SIEM feed in routers/audit.py - GET /feed JSONL
  (after_id cursor, limit 500/max 5000, X-IAG-Last-Id + X-IAG-Head
  headers) + GET /feed/stats; cursor-follows-id tests; auditor-key
  200 / report_viewer-key 403; streaming (no full buffering).
4. Phase D [DONE 9dec9bb]: campaign report backend (GET /api/campaigns/{id}/report
  JSON incl. reviewer workload + revocations + risk block;
  report.csv streamed) + frontend (Risk view, /campaigns/:id/report
  print CSS + window.print, client risk/report namespaces, nav);
  TSC 0 + vite build (output = backend/static, image rebuild picks
  it up).
5. Phase E [DONE 8391746]: scripts/live_risk_check.py + live_report_check.py +
  live_siem_check.py (walk feed pages = audit CSV export three-way
  consistency; client-side chain recompute; NO tamper on live DB);
  run on REBUILT stack (build every service + force-recreate all 3
  app replicas - round-robin stale-image lesson); HANDOFF, commit.
  Live proof also surfaced + fixed trend ordering (id not
  computed_at; clock-step regression test added).
6. Each phase: pytest green + stack healthy + commit (msg-file
  method w/ trailer) + TSC when frontend touched.

### Context-window protocol (applies to every build session)

- Budget ONE fresh chat per 1-2 phases: chat 1 = Phases A+B, chat 2 =
  Phases C+D. A phase that fights back (3+ failed fix iterations in a
  row) ends the chat at the next green checkpoint instead of pushing
  through on fumes.
- Every phase boundary is a resume point: commit + append [DONE] to
  the phase's Sequence step + one session-log line. A fresh chat
  must be able to pick up at ANY phase boundary with zero loss.
- Never end a chat mid-phase. If truly forced, record exact in-flight
  state (files touched, test status, very next action) under
  Unverified/in-flight BEFORE the chat ends.
- Lean-output discipline: pytest -q piped to the last 2 lines; docker
  build/compose logs tailed, never streamed; targeted Select-String
  over full-file reads; never re-verify what this session already
  proved [V] - the label carries.
- Startup reading budget: this file + SPECS/feature-6-scim-provisioning-enforcement.md
  fully; REQUIREMENTS/ARCHITECTURE only on demand (the spec encodes
  the build). Do not cat whole source files unmodified this session.
- Early-warning self-check: re-reading the same file twice, losing
  phase state, or a fix loop past 3 attempts = STOP, checkpoint to
  this file, tell the USER to open a fresh chat. Say so plainly.

## User's exact words for the new chat

"Continue the IAG rebuild at D:\Projects\iag - read
HANDOFF.md first. Feature 6 (SCIM + enforcement) spec is RATIFIED
(session 16 - SPECS/feature-6-scim-provisioning-enforcement.md,
D1-D8 ruled; D3 carries the schema-alignment amendment + Phase C
end-user-docs deliverable). In this chat: build Phase A only
(migration 0008 + models + core/scim.py pure helpers + unit
tests), green-gate it, commit, and stop at the phase boundary.
Docker daemon was up at last close (29.7.2) - verify before
build."

## USER DECISIONS RATIFIED (2026-08-22, session 16)

1. **Feature-6 spec D1-D8: RATIFIED** (D1 bundle + D3 amended; D2,
   D4-D8 as drafted).
   - D1 (the big one): BUNDLE - inbound SCIM + outbound enforcement
     in one feature, phases A-E in order. 6a/6b split declined.
   - D3 (the only contested one): SCIM id = employee_id stands, but
     RATIFIED AS AMENDED by the user's requirement that the join
     key align to the authoritative source's schema. Resolution:
     alignment at the VALUE level - externalId is whatever the IdP
     declares as its stable key (AD may push UPN, HR-backed feeds
     push employee numbers) and becomes employee_id verbatim;
     directory-side alignment is per-source connector_config
     (account_attr / disable attr / admin SQL - no assumed schema
     anywhere, now a ratified invariant paragraph); schema
     introspection/discovery designed out. User explicitly required
     this be clear in END-USER DOCUMENTATION -> docs/admin-guide.md
     + UI help text are ratified Phase C deliverables.
   - D2: DELETE always soft (v1 hard-delete designed out). D4: one
     install-wide SCIM token, SHA-256 at rest, reveal-once, NOT an
     ApiKey row. D5: enforce rides the remediation state machine as
     a third delivery arm. D6: require_approval defaults ON for
     enforce rules. D7: SQL write-back = admin-supplied statements
     with bind params, validate-at-save. D8: zero new dependencies
     (fact-checked vs pyproject.toml before recording [V]).
   - ARCHITECTURE.md design-slots line added; ratification commit
     re-ran pytest 172/172 (house rule). Build phases A-E may
     proceed. Feature 6 is the LAST feature - arc closes at E.

## USER DECISIONS RATIFIED (2026-08-21 late, session 12)

1. **Feature-5 spec D1-D8: RATIFIED AS DRAFTED** ("Ratified").
   - D1: SIEM feed is PULL-ONLY (the big one) - GET /api/audit/feed
     JSONL with after_id cursor + chain hashes; no push forwarder,
     no provider formatters, no SIEM credentials anywhere.
   - D2: one feature bundling risk + PDF + SIEM (shared guards and
     consumers). D3: 7 transparent signals, fixed weights
     20/20/20/10/10/10/10, bands 25/50/75; dormancy renamed
     unreviewed_access (review-decision recency - no usage
     telemetry exists).
   - D4: explicit admin POST triggers risk runs; snapshots permanent;
     no scheduler. D5: feed auth = auditor-role API key only.
   - D6: PDF = print-CSS SPA view + browser print-to-PDF; nothing
     server-side, no PDF library. D7: no new API-key roles;
     report/risk GETs accept report_viewer keys, feed stays
     auditor-only. D8: zero new dependencies.
   - Bundled: ARCHITECTURE.md design-slots line added ("Risk,
     reports, and SIEM feed: read-side computation over governed
     data; SIEM is pull-only."); ratification recorded here.
     Build phases A-E may proceed.

## USER DECISIONS RATIFIED (2026-08-20, session 8)

1. **Feature-4 spec D1-D7: RATIFIED AS DRAFTED** (`All ratified`).
   - D1: keys READ-ONLY, roles auditor + report_viewer only (the
     big one - enforcement at principal layer, not per-router).
   - D2: iag_{id}_{token_urlsafe(32)}, SHA-256 hash at rest, prefix
     shown in list, full key returned ONCE at create.
   - D3: Authorization Bearer header ONLY (no X-API-Key, no query).
   - D4: SessionUser alias for personal endpoints (403 for keys);
     dashboard mixed payload (portfolio real, personal zeroed).
   - D5: create/list/revoke only; soft revoke; rows permanent;
     rotation = create + revoke; optional expires_at (null=never).
   - D6: lifecycle-only audit (api_key_created/api_key_revoked);
     last_used_at best-effort 60s throttle, no per-request audit.
   - D7: no rate limiting this feature; revisit at nginx if ever
     exposed beyond localhost (feature-5 SIEM polling may revisit).
   - Bundled: ARCHITECTURE.md design-slots gains the API-keys line;
     ratification recorded here. Build phases A-D may proceed.

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

## USER DECISIONS RATIFIED (2026-08-20, this session)

3. **D1–D6 of the feature-2 spec (D2 deferred):** user ratified all six
   decisions as drafted, EXCEPT D2 (secrets-in-DB encryption) is deferred
   to the polish phase — connector secrets stored as ordinary rows, no
   `cryptography` dep now, no new security surface. Spec section
   "Secrets" documents the deferral and the migration-0005 (or later)
   backfill path. D1 new-deps list is therefore `ldap3` + `httpx` only.
   Build phases A–E may proceed.

## USER DECISIONS RATIFIED (2026-08-20, session 6)

4. **Feature-3 spec D1-D7: RATIFIED AS DRAFTED** ("ratify all").
   - D1: drop v1 disable_account + remove_entitlement; remediation =
     workflow layer (rules, approval gate, notify_owner / webhook
     delivery); enforcement write-back is feature 6's scope.
   - D2: remediation email bypasses EmailOutbox; the remediation
     worker sends SMTP directly; the action row is the delivery record.
   - D3: revoke-only trigger. D4: single-row remediation_settings
     table. D5: retry keeps attempts, one attempt per retry click.
   - D6: regex compiled at rule save, backtracking risk accepted.
     D7: source-owner email as recipient.
   - Bundled: ARCHITECTURE.md design-slots list gains the remediation
     line; ratification recorded here (this entry).
   Build phases A-E may proceed.
