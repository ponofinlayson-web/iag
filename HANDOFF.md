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
backend/app/routers/deps.py — get_current_user (cookie OR Bearer API-key
  principal), ApiKeyPrincipal, read-only + keys-manage-keys chokes,
  require_roles, Annotated aliases: AdminUser, CertAdminUser, AnyUser,
  SessionUser (cookie-only), DbSession; exports _settings
backend/app/routers/auth.py — login (lockout), me/logout/change-password
  (all SessionUser; logout no longer anonymous)
backend/app/models/apikey.py — ApiKey (name/prefix/hash/role/is_active/
  expires_at/last_used_at), sa.Enum(Role) name-storage
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
backend/app/core/email_worker.py — reminder worker: _claim_due (FOR UPDATE
  SKIP LOCKED + stuck reclaim), send outside TX, _finalize sent/failed/
  dead-letter + audit, run_pass, worker_loop (lifespan, skipped in test env)
backend/app/routers/reminders.py — read-only: GET /api/reminders/outbox
  (paged, campaign/status filter), GET /api/reminders/campaigns/{id}
  (by_status counts); CertAdminUser only
backend/app/models/email.py — EmailOutbox + OutboxStatus
backend/alembic/versions/0003_email_outbox.py — explicit DDL, portable types
backend/tests/test_reminders.py — enqueue, claim/send+chain, no-double-send,
  retry→dead-letter, cancel-blocks-claim, 401/403, boot (suite 19/19)
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

## Current status (2026-09-10, session 29 close) — AGENTS.md LANDED (PR #4)
Reviewed + verified PR #4 (agents-md): all claims checked against
repo state — 290 tests collected (count still exact), all referenced
paths exist. One-line polish: `.openhands/memory/` noted as
host-local/gitignored in the read order. Rebased onto 7804dca, CI
green (backend 2m44s, frontend, CodeQL py+js), squash-merged as
1c3a81b. AGENTS.md is now the canonical agent primer for this repo.
This HANDOFF entry was a user-authorized direct commit to main
(2026-09-10, single approval — not a standing rule).

HOST ALERT (needs user decision, non-blocking): primary checkout
`~/Projects/GitHub/ponofinlayson-web/iag` is ahead 6 / behind 2 with
~40 uncommitted docs-site files (forge residue). The 6 local commits =
Linux forge port (2be80b6), publish fixes, W1 minors, RUNBOOK-linux,
nginx hardening, CSP fix — real work, never pushed. Reconcile (push
vs rebase+PR) before the next forge/docs session; do not discard.

## Current status (2026-08-25, session 28 close) — P1-P3 BACKLOG CLEARED, LIVE-VERIFIED
Session opened as recovery of a hung chat (harness KeyError mid-E2E);
all P1-P3 work reconstructed from event forensics and verified on disk
before this session's E2E/commit pass. Closes session-26 findings 1+2
(403 shell leak; no self-service change-password) and the connector
PUT replace-semantics hazard. Commits: 68f22a7 (P1+P2), d191ee4 (P3).
Pushed 2026-08-25 (user-authorized): origin/main == 51dc106, local and
remote level. All items [V] unless noted:

P1 — hide page shell on 403 (frontend only; backend stays the boundary):
- App.tsx: route role gates derived from the NAV role map the topbar
  filters on (single source of truth); unauthorized direct-nav now gets
  a full-page no-shell Forbidden screen instead of shell + notice.

P2 — self-service change-password:
- ForcedPasswordChange.tsx (new): full-page gate mounted INSTEAD of the
  shell when me.must_change_password; logout is the only escape; after
  change, me is refreshed and the gate releases.
- Layout.tsx: topbar Change password modal (all roles) →
  POST /api/auth/change-password; success signs the user out (fresh
  session; no stale cookie).
- Live E2E: wrong old pw → in-modal "Current password incorrect",
  session intact, no logout; correct change → forced logout; re-login
  with the new password succeeds; forced interstitial blocks the shell
  until the change completes (verified live in the hung session,
  2026-08-24; modal path verified this session).

P3 — connector config PUT merge-not-replace:
- sources.py: PUT merges config against stored — absent keys keep
  stored values, present-but-blank keys are cleared pre-validate;
  merged config is what the adapter validates (a failed partial PUT
  can no longer wipe stored fields). sync_interval_minutes uses
  model_fields_set: absent keeps stored, explicit null clears (and
  nulls next_sync_at). Audit logs the effective values.
- Sources.tsx: interval box sends explicit null when empty, so UI
  clearing works under merge semantics.
- Live proof vs the glauth source (id 6): failed partial PUT left
  stored config 100% intact; blank url → 400 "ldap config missing
  url"; absent interval kept 45; explicit null cleared it and nulled
  next_sync_at. Interval restored to 45 after the test.

Gates this session: tsc clean; production build ok; backend pytest
290/290 (includes two new P3 regression tests); App.tsx EOF blank-line
cleanup (byte-verified, tsc re-run after).

DB deltas (e2e residue): p6_browser (reviewer) password now
p6-new-pw-2026b (E2E change-password subject); e2e_admin state as
session 26. admin id=1 untouched.

## Prior status (2026-08-24, session 27 close) — T6 PASS, RELEASE v0.3.0 SEALED
Release packaging complete à la the session-24 T4 recipe. All gates
[V] on this session's own runs:
- Knob audit: users router has ZERO Settings references (grep) —
  Feature 7 added no new knobs; 28/28 app knobs documented in
  .env.example (4 required + 24 commented), all commented values
  match Settings defaults; IAG_DATABASE_URL/IAG_ENV are
  compose-managed (interpolated per-service / pinned) [V].
- Compose audit: `docker compose config` (and with
  `--profile connectors`) validates clean — no warnings, no legacy
  version: key, single published port 8090, glauth/openldap profile-
  gated out of the default stack [V].
- Rebuild gate: all 4 images rebuilt from the tagged tree (cache-
  warm), `up -d`, all replicas healthy, /api/health == 0.3.0 [V].
- Suite gate: backend pytest 288/288 (129s) against the rebuilt
  stack [V]. Frontend unchanged since 779fe8e (tsc/build green
  recorded session 25; no re-run needed).
- Version-surface check: README L120/123, CHANGELOG [0.3.0] entry,
  pyproject, package.json all at 0.3.0 [V]. Tag v0.3.0 verified
  SYMMETRIC local+remote, annotated, on 779fe8e [V].
Post-tag delta remains HANDOFF.md only (this commit). T6 commits
land after the tag, untagged, per the ratified decision.

## Prior status (2026-08-24, session 26 close) — T5 PASS
E2E browser pass over Feature-7 surfaces. Session opened on a stale
stack serving 0.1.0 — all images rebuilt (incl. migrate container),
`docker compose ps` clean, /api/health reports 0.3.0 [V]. e2e_admin
(id=2) reset via backend/scripts/e2e_admin.py (pw `e2e-browser-25`),
then promoted certification_admin → system_admin through the real
users API (audit-chained). All items below [V] unless noted:
- Non-admin leg (cert_admin): no Users nav; direct /users → clean 403
  naming system_admin; Users nav appears after promotion with NO
  re-login (guards re-read the DB row per request)
- Users CRUD: Add-user modal (Typeahead excludes identities that
  already have users; native role select; Generate = 14-char); create
  t5_browser → reveal-once password modal (Copy/Done); deactivate and
  reactivate instant; 10 bad logins → locked badge + failures=10 +
  Unlock button → unlock resets failures to 0; reset pw → second
  reveal-once modal; then logging in AS t5_browser with the admin-reset
  password succeeds — reset flow proven end-to-end; own-row guards
  hold (Role disabled, Deactivate disabled while own account active;
  clicking them does nothing, no modal)
- Tooling limit (same class as session 22): the browser tool cannot
  open native <select> options, so the role-change VALUE was exercised
  via the same PUT endpoint through the API (that is how e2e_admin was
  promoted); the role modal itself verified in-UI. Not a product gap.
- Theme: toggle reactive (no reload — element indices stable across
  the toggle); choice sticky in localStorage (iag.theme); pre-paint
  script confirmed present in the SERVED index.html (flash-of-wrong-
  theme impossible); hard reload honors the stored choice even on a
  light-OS host. Icon shows the switch TARGET (Layout.tsx L51), not
  the current theme.
- Accents: nav active (.navlink.active = accent + accent-soft);
  sorted-column indicator (▲ on Username sort); filter chips (the
  Identities "Search table." — suggestion click commits a chip, ×
  removes it; chips exist on Identities/Sources/Campaigns/SoD, not
  Users — by design); role badges incl system_admin
- Stat tones: Dashboard warn (unlinked 13, privileged 13) + ok
  (campaigns 5, pending 0) — both branches live; Risk bands critical/
  medium/low (no high rows — data, not a defect). Both themes
  screenshotted: users table, dashboard, risk, chips, login screen.
Findings (non-blocking, no code changed):
1. A reviewer direct-navigating /risk sees the page shell + a small
   "Insufficient role" notice + "No snapshots" empty state. Backend is
   correct (reviewer is not in the ReportViewer gate, deps.py L104;
   nav correctly omits Risk). Cosmetic leak of the shell only — same
   pattern as the /users 403 page. Future polish: hide shell on 403.
2. must_change_password has no self-service UI: endpoint
   POST /api/auth/change-password exists but nothing surfaces it and
   login does not force a redirect. t5_browser simply keeps using the
   admin-reset password. Candidate for a future feature; outside
   Feature-7 scope.
DB deltas (e2e dataset, acceptable residue): e2e_admin promoted;
identity 15 (E-T5-01 / t5_browser) + its login user (reviewer)
created; one lockout + unlock cycle; two password resets. admin id=1
untouched. Tree clean @ 59ad56c; no commits this session (ops/E2E).


## Prior status (2026-08-24, session 25 close) — FEATURE 7 DONE, v0.3.0 TAGGED

Feature 7 (RBAC users + themes) COMPLETE, committed, pushed, tagged.
Commits: 0ce3122 (spec ratified) → 7032bdd (D1 users router, 14 tests,
self-guards, audit-chained) → 9381483 + 75e98e7 (D5: version 0.3.0
everywhere incl. stale FastAPI/health 0.1.0, CHANGELOG, README,
contrast gate) → 62897f9 (D2-D4: Users view, theme system, accent
dispersion) → 779fe8e (mojibake purge). Tags SYMMETRIC local+remote:
v0.1.0 (44e1985), v0.2.0 (600e2cf, retroactive), v0.3.0 (779fe8e).
Suite 288/288 [V], tsc/build green [V], contrast PASS both themes [V].

Mojibake purge (this session): three CP1252-layer variant families
found; ARCHITECTURE/REQUIREMENTS titles + 107 runs in THIS file fixed
to proper UTF-8. One commit message deep in history (de5561a) still
carries it — user ruled: leave it, no rewrite.

### NEXT (in order), fresh chat each:

NOTHING BLOCKING. The v0.3.0 release is sealed: features 1-7 built,
T1-T6 release tasks all closed, tag symmetric local+remote. What
remains is optional polish / backlog, user's call on priority:

P1 (T5 finding 1, cosmetic): hide the page shell on 403 — reviewer
direct-navigating /risk sees shell + "Insufficient role" notice +
"No snapshots" empty state. Backend correct; nav correct. Same
pattern as the /users 403 page. Small frontend fix.
P2 (T5 finding 2, candidate feature): must_change_password has no
self-service UI — POST /api/auth/change-password exists, nothing
surfaces it, login does not force redirect. t5_browser keeps using
the admin-reset password. Design + build a change-password flow.
P3 (backlog, old): connector config panel remounts empty + PUT
replace-semantics (session-22 polish item 1 — echo stored config,
consider merge-not-replace).

DECISION STILL RATIFIED (2026-08-24): v0.3.0 tag STAYS on 779fe8e.
Do NOT delete/retag. Remote tag untouched. Post-tag commits untagged.

### Superseded (history only, do not follow):
- "Sequence for next session (feature 5 build)" (farther down)
- "User's exact words for the new chat" (feature-5/6 era, farther down)

### Environment notes (canvas host, this session):
- Terminal FRAGILE: console host crashed once (Win32 pipe FailFast);
  multi-cd chained compounds wedge. Use ONE short command per
  invocation. No inline python -c with nested quotes — temp scripts.
- Gate: no apostrophes in Python comments (regex stripper eats them;
  root cause pinned, real fix deferred).
- Files panel cannot serve D:\Projects\iag (workspace rooting) —
  open files for the user via `code <path>`; never claim panel
  visibility without agent-server log check.
- Stack state NOT verified this session: check docker daemon +
  `docker compose ps` before any live work. .env SMTP lines remain
  [disabled] (session-24 landmine note below still applies).


## Current status

FEATURE 6 PHASE C COMPLETE (session 19, be1f3a1). Built: scim.py
admin_router (GET/PUT /api/scim/config; POST/DELETE /api/scim/token -
reveal-once iag_scim_* urlsafe, sha256 at rest, prefix+created_at in
config, rotate kills old bearer same commit, revoke idempotent w/
already_revoked, plain 400s not RFC7644 envelopes on the admin
surface; audits scim_config_updated/scim_token_rotated/scim_token_revoked,
session-auth AdminUser); remediation.py ACTIONS+enforce with target
CRUD (target in {remove_entitlement,disable_account}, enforce+webhook
400, default_action still rejects enforce), D6 tri-state
require_approval (None => enforce ON / others unchanged), _rule_out
exposes target; remediation_trigger.py snapshot freezes rule target +
data_source_id (phase-D seam: queue Sync now links to source);
remediation_worker.py _DELIVERERS registry + _deliver_unsupported -
unknown action types fail with their own name (was: silent webhook-arm
misroute; enforce now honestly says no delivery arm until D ships);
frontend: client.ts scim namespace + ScimConfig/ScimTokenCreated +
rule.target + snapshot keys, Remediation.tsx system_admin SCIM card
(toggle/prefix/rotate/revoke-confirm) + reveal-once token modal w/
externalId join-key guidance + enforce form option + target select +
queue enforce badge/target/Sync now; docs/admin-guide.md (NEW dir;
plain-English, task-shaped, troubleshooting). Tests: 14 new
(test_scim_admin.py), suite 247/247 [V]. LIVE smoke PASS
(scripts/live_scim_admin_smoke.py, 24 legs, reset-first idempotent,
reads IAG_BOOTSTRAP_ADMIN_PASSWORD from env). All 3 replicas rebuilt
healthy [V] (service names are iag-app-N in compose - `docker compose
build iag-app-1 iag-app-2 iag-app-3`; `app-1` is not a service).
## Current status (2026-08-23, session 22 close)
T1 E2E BROWSER PASS COMPLETE [V]. Full UI spine walked end-to-end in
the real browser as e2e_admin (certification_admin) against the live
glauth stack: source -> configure connector (live bind validation) ->
sync (3 accounts + 4 entitlements) -> campaign create (UI) + scope
(PUT API; no UI scope editor yet) -> preview 3/3 -> stage -> start ->
decide (approve via UI; two revokes via API) -> campaign
auto-completed 100% -> report page + CSV + Print/PDF. Remediation
rule created/fired/deleted via UI (notify_owner actions #31/#32 ->
failed ConnectionRefused after 3 retries; no SMTP container by
design). Enforce rules 55-57 scoped to sources 17/18, so no
accidental enforcement against the dead openldap container.
Why revokes went via API: Reviews.tsx uses window.prompt for the
mandatory revoke comment; native dialogs are outside browser-tool
reach (same class of limit as native <select>). Product fix queued in
polish list, not a defect found in the API.
T3 POLISH LIST (from live findings, in priority order):
1. Connector panel remounts empty + backend PUT replace-semantics
   means saving with a blank field wipes the stored config (echo the
   stored config back into the form; consider merge-not-replace).
2. Reviews revoke: window.prompt -> inline comment input.
3. Campaign create form has no scope editor (scope API-only).
4. Remediation rule form lacks a source filter (catch-all only).
5. Report page: 'identities:none scored' missing a space.
6. Sources list has no delete button (API-only by design; document).
T2 CLOSED (same session, 2026-08-23): the v1 deferred list is fully
landed - connectors, email queue+delivery, SoD, SCIM, remediation +
enforcement, API keys, risk scoring, SIEM feed (live smoke: 200,
application/x-ndjson, hash fields present). The final unverified leg
was real SMTP delivery; closed by standing up a minimal asyncio SMTP
sink on the host (workers connect to host.docker.internal:1025 per
.env - creds there are dev placeholders), then retrying failed
notify_owner actions #31/#32 from the UI: both completed on attempt
4 and the sink received two real RFC822 emails with correct
owner-routing, reviewer comments, and action references. Audit chain
valid at 556 entries after. Design facts worth keeping: notify_owner
without IAG_SMTP_HOST configured is a hard failure (ratified); empty
host = email worker log-only; both senders are adaptive (plaintext
fallback when the relay offers no STARTTLS, login skipped when no
AUTH extension).
NEXT: T3 polish (list above) -> T4 v0.1 release packaging. User's call.
## Current status (2026-08-23, session 23: T3 UI polish pass)
T3 items 1-4 DONE [V], test-first where a backend change was involved.
All verified on the live stack (rebuild: `docker compose build
iag-migrate iag-app-1 iag-app-2 iag-app-3 && docker compose up -d`;
nginx serves the baked bundle from the iag_static volume).
1. Connector config echo (item 1): GET /api/sources now returns
   connector.config (non-secret echo; secret stays write-only via
   has_secret). Red test first
   (test_connector_block_echoes_config_not_secret), then
   _connector_block change; test_syncs_api shape pin updated to
   include 'config'. ConnectorPanel prefills all fields + interval
   from the echo, so reopening no longer shows blanks and saving no
   longer silently wipes config. Verified live on source #21: all 6
   ldap fields prefilled [V]. NOTE: PUT is still replace-semantics
   (not merge); with prefill the wipe path is closed, merge left as
   deliberate non-goal for v0.1.
2. Reviews revoke modal (item 2): window.prompt replaced with an
   in-app modal (state + render); native-dialog limit gone.
3. Campaign scope editor (item 3): CampaignDetail gets a Scope
   summary card (all statuses) + ScopeEditor for draft/staged
   (sources checkboxes, departments CSV, privileged-only,
   unlinked-only). PUT round-trips name/mode/description/deadline
   unchanged (PUT is replace-semantics - must send full body).
   Verified live: created campaign 21, set scope
   {data_source_ids:[21],departments:[Engineering],privileged_only:true}
   via the UI form, read back exact match, deleted [V].
4. Remediation rule source select (item 4): backend already had
   data_source_id (validated FK); form got a source select + filters
   column shows 'source #N'. Verified live: options list renders [V].
Item 5 (report spacing) verified OK in session 22 (extraction
artifact). Item 6 stays documented-no-delete (by design).
Suite 268/268 [V] (was 267; +1 connector echo regression test).
Frontend tsc + vite build clean; live bundle index-BsFyhieq.
Also this tree: AuthProvider wrap in main.tsx + backend/scripts/
e2e_admin.py (E2E helper from session 22) ride along in the commit.
NEXT: T4 v0.1 release packaging. User's call.

## Current status (2026-08-22, session 21 close)

FEATURE 6 COMPLETE (phases A-E shipped; Entra remains mock-tested by
spec design - live proofs name glauth only).

Phase E (session 21, commit below): live proofs + 3 PRODUCT BUGS found
by the live harness and fixed (this is what live proofs are for):

1. `_ldap_validate` rejected every real directory: its size_limit=1
   base probe got result 4 (sizeLimitExceeded) on any base with >1
   entry and treated it as failure. glauth never surfaces it; osixia
   OpenLDAP does. Fix: result in (0, 4) = reachable.
2. LDAP fetch requested attributes=['*'] only - memberOf is an
   OPERATIONAL attribute, never returned by '*' alone, so real
   directories would mirror ZERO entitlements (mocks bypassed the
   kwarg). Fix: attributes=['*', 'memberOf'].
3. Audit chain forked under 3 replicas: append_audit's
   with_for_update() head lock cannot serialize under READ COMMITTED
   (loser's statement snapshot predates winner's commit -> re-reads
   stale head). Live repro: entries 308/309 both prev=f760...  Fix:
   pg_advisory_xact_lock (key 913731) before head lookup, PG-only,
   no-op semantics on SQLite. Historical forked rows healed once via
   in-container re-chain script (deleted after use).

Tests: 267/267 [V] (2 new regression tests pin the validate+fetch
fixes; advisory lock verified live - chain valid at 475 entries with
3 replicas racing).

LIVE PROOFS ALL GREEN [V] (nginx 8090, rebuilt images):
- scripts/live_enforce_check.py: LIVE ENFORCE CHECK PASS - osixia
  OpenLDAP writable member delete + disable-attr flip + already-clean
  idempotent seconds; SQL write-back leg on stack Postgres (planted
  table, admin statement, bound params, 1 row affected); chain valid.
  Overlay quirk: osixia memberOf overlay defaults
  groupOfUniqueNames/uniqueMember; script repoints to
  groupOfNames/member per-run (ephemeral config, no volume) before
  bootstrap. Divergence from spec's glauth documented here.
- scripts/live_scim_smoke.py + live_scim_admin_smoke.py: both PASS
  (bearer gate, CRUD, PATCH depro shape, filter, rotate kills old
  token, revoke 503s surface, chain valid, actor "scim" in feed).

Spec-vs-code sweep (phase-E scope): every bullet in the spec's
live-proof section maps to a passing script leg; SCIM surface covered
by the phase-B/C smokes rerun post-fixes; admin-guide.md exists
(phase C). REQUIREMENTS deferred-list "SCIM" + ARCHITECTURE slot line
landed at ratification - nothing outstanding.

Live-proof harness notes: script resets bob's disable attr via
MODIFY_DELETE (empty-value REPLACE is schema-illegal);
re-touch step re-adds members because groupOfNames requires >=1
member; entitlement binding must happen BEFORE revoke submit
(snapshot freezes at trigger).

NEXT (fresh chat): feature-6 closed. Open per REQUIREMENTS
deferred-list review + product backlog judgment: E2E browser test
pass, any remaining deferred-list entries, UI polish, release
packaging (v0.1 tag + notes) - user's call on priority.

## Session log (newest first)
### 2026-09-10 (session 29): PR #4 AGENTS.md review + merge
- PR #4 (docs primer) reviewed, verified, polished (memory path is
  host-local), rebased onto 7804dca, squash-merged as 1c3a81b.
- Discovered primary checkout divergence (6 ahead / 2 behind + dirty
  docs-site) — recorded as HOST ALERT in current status above.
- `.openhands/memory/` initialized on the Linux host (primary checkout).

### 2026-08-23 (session 22): T1 E2E browser pass + T2 deferred-list close
- T1 COMPLETE: full UI spine walked in-browser as e2e_admin vs live
  glauth stack - source -> connector config (live bind validation) ->
  sync (3 accounts/4 entitlements) -> campaign #20 via UI (scope via
  PUT) -> preview/stage/start -> decide (approve via UI; revokes via
  API because Reviews.tsx uses window.prompt - polish item) ->
  auto-complete 100% -> report + CSV + Print/PDF. Remediation rule
  created/fired/deleted via UI.
- T2 COMPLETE: deferred list fully landed; SIEM feed smoke (200,
  x-ndjson). Final gap = live SMTP delivery: minimal asyncio sink on
  host:1025, UI Retry of actions #31/#32 -> completed attempt 4,
  sink received 2 real emails (owner routing, comment, action ref).
  Chain valid 556 after. Scratch sink deleted after use.
- Findings -> T3 polish list (6 items) recorded in Current status.
- No code changes this session; data created: source #21, sync run
  #21, campaign #20, reviews #50-52, rule e2e-browser-notify
  (deleted), 2 delivered emails.
### 2026-08-22 (session 21): FEATURE 6 PHASE E (live proofs + 3 live-found product fixes) - FEATURE COMPLETE

- Phase E plan: writable OpenLDAP (osixia 1.5.0, connectors profile,
  deploy/enforce.ldif) since enforcement needs real writes; glauth is
  read-only. Overlay repoint per-run: olcMemberOfGroupOC=groupOfNames,
  olcMemberOfMemberAD=member (osixia defaults groupOfUniqueNames).
- Commit (single): 3 product fixes + 2 regression tests + live harness
  + compose/ldif + HANDOFF. Suite 267/267 [V]; full live rerun green.
- Bugs (all found by live proof, all fixed test-first):
  1. validate: sizeLimitExceeded (result 4) on real dirs = reachable,
     not failure (test_ldap_validate_size_limit_is_success).
  2. fetch: ['*'] omits operational attrs -> memberOf never mirrored
     on real dirs (test_ldap_fetch_requests_operational_attributes
     pins ['*','memberOf']).
  3. audit append: pg_advisory_xact_lock(913731) before head lookup;
     with_for_update alone forked chain under 3 replicas (READ
     COMMITTED snapshot). Historical forks healed once in-container.
- LIVE ENFORCE CHECK PASS [V]: member delete (bob out, alice intact),
  disable-attr flip, both already-clean idempotent seconds, SQL
  write-back leg (1 row, bound params), chain valid 475 entries.
  SCIM smokes rerun post-fixes: both PASS.
- Harness gotchas: disable-attr reset must MODIFY_DELETE (empty-value
  REPLACE illegal); groupOfNames re-touch ADDs missing members first
  (>=1 member required); bind entitlement BEFORE revoke (snapshot
  freezes at trigger); harness re-created openldap after each docker
  daemon crash (recreate, not restart).

### 2026-08-22 (session 20): FEATURE 6 PHASE D (enforcement write-back engine)

- Commit 5d80980 (single commit: engine + worker hook + tests + docs).
  Suite 265/265 [V] (17 new test_enforcement.py + 1 retargeted
  dispatch-guard). Full-suite rerun green after all changes [V].
- enforcement.py arms: LDAP group-member MODIFY_DELETE / disable-attr
  MODIFY_REPLACE; Entra member $ref DELETE / accountEnabled PATCH; SQL
  admin-supplied statements, bound params pinned by test. Guards: no
  entitlement in snapshot (disable target ok), missing disable config,
  user/group not found fail clear; ldap unbind in finally.
- Already-clean semantics: second run completes without writing (pinned
  per adapter: ldap group attr, entra member set, sql statement result).
- Worker: _deliver_enforce resolves snapshot.target + data_source_id ->
  source row -> arm; errors requeue while attempts<max (same fork-A
  discipline), remediation_action_executed audit with target+result,
  hash chain verify green.
- Raw-SQL seeding gotchas hit + documented in memory: SQLAlchemy Enum
  stores NAMES ('PENDING'/'ACTIVE'); accounts/campaigns/entitlements
  rows need explicit created_at/status/scope/is_active; /api/audit
  returns details as a JSON string — parse client-side.
- test helper discipline: _make_enforce_rule deactivates prior enforce
  rules (feature-3 fires ALL matches); _revoke_bob scoped per-source +
  decision IS NULL (reviews one-shot); _ensure_bound re-binds MOCK conn
  after the arm's finally-unbind (inspection still works).

### 2026-08-22 (session 19): FEATURE 6 PHASE C (management + enforcement UX)

- Commit be1f3a1 (single commit: backend + frontend + docs + tests +
  smoke). Suite 247/247 [V] (14 new). npm run build (tsc -b + vite)
  green [V]. Replicas rebuilt + healthy [V].
- LIVE smoke 24/24 PASS [V] (scripts/live_scim_admin_smoke.py):
  401 no-session; admin config GET/PUT; token generate reveal-once
  (prefix shown, hash never); rotate kills old bearer same-commit;
  revoke => 503 surface + enabled stays true; enforce rule CRUD live
  (target pinned, approval ON default, bad target 400, enforce+
  webhook 400, default_action enforce 400); rule delete; audit chain
  valid. Script reads IAG_BOOTSTRAP_ADMIN_PASSWORD env (NOT
  hardcoded); /api/audit/verify is session-gated (feed is not).
- Worker dispatch guard: registry pattern (_DELIVERERS dict) replaces
  the notify/webhook ternary; unknown types (incl. enforce until D)
  raise "action_type X has no delivery arm in this build" and REQUEUE
  (attempts<max) - not dead-letter; test pins the message + requeue.
- Frontend gating: SCIM card only for me.role==="system_admin"
  (cert_admin uses Remediation page but never sees the card; config
  fetch fires only when the role grants it).
- docs/ dir created this session (admin-guide.md first occupant).
- GOTCHA (fresh): compose services are named iag-app-1/2/3 (project
  prefix iag-); `docker compose build app-1` => no such service.
- GOTCHA (fresh): IAG nginx publishes 8090, NOT 80 (80 is Plane).
  localhost:80/api/scim/* => 404; use localhost:8090.
- GOTCHA (fresh): container python3 has no fastapi on PATH context -
  docker exec python -c "import app.main" fails; verify deployments
  via HTTP probes instead.
### 2026-08-22 (session 18): FEATURE 6 PHASE B (SCIM router + token dependency)

- Commits c1bbfb9 (router + dependency + 24 integration tests +
  normalize_patch composition fix) + 5438605 (live smoke script).
  Suite 233/233 [V]. All 3 replicas rebuilt on Phase B image [V].
- LIVE smoke PASS [V] (scripts/live_scim_smoke.py, 10 legs): 503
  disabled envelope; psql-seeded token (sha256) + enabled=true ->
  list 200; bad bearer 401; create 201 id=externalId; PATCH Okta
  shape active=false; DELETE 204; externalId filter; chain valid +
  scim actor in feed; disabled restored. Script resets the settings
  row FIRST (prior failed run leaves enabled=true + stale hash -
  idempotent re-run rule).
- REAL BUG (phase-A gap): normalize_patch emitted flat "name.givenName"
  keys; scim_to_identity_fields reads only nested name dicts - a
  name-only PATCH silently no-opped. The phase-A round-trip test
  passed only because displayName "A B" parsed to the same values the
  dotted paths were supposed to set. Fixed: fold dotted paths into
  nested name dict; regression test pins composition.
- GOTCHA: exception HANDLERS must return, never raise - a raise
  inside a handler escapes to ServerErrorMiddleware (plain 500), it
  does not re-enter the app's handlers.
- GOTCHA: feed/stats key is total_entries (not entries).
- GOTCHA: urllib filter URLs need quote() (spaces = control-char
  InvalidURL).
- GOTCHA: verify_script_gate apostrophe false positive - a possessive
  in a comment (token's) makes the string-stripper regex eat code;
  reword the comment, do not chase a phantom imbalance.
- GOTCHA: compose anchor gives app-2/3 their OWN image tags - build
  each service (or all three) explicitly; --force-recreate alone
  recreates from STALE per-service images (verified: scim.py
  missing in 2/3 until individually built).
- ENV: daemon dead at session open (crash-loop pattern continues);
  Start-Process relaunch + ~10s wait; healthy since (no crash
  during this session's builds).
- NEXT (fresh chat): Phase C per staged words in Current status.



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
  neither), scripts/smtp_sink.py (aiosmtpd dev sink, bind 127.0.0.1 —
  aiosmtpd probes `hostname`, 0.0.0.0 invalid on Windows; Docker Desktop
  proxies host.docker.internal to host loopback), scripts/live_smtp_proof.py.
- 4decb98 proof-harness fixes: unique source/campaign names (live DB carries
  history — hardcoded names collide on rerun), expected count derived from
  start response, greeting assert CRLF-tolerant + name-agnostic (live admin
  is "System", fixture is "Ada"; SMTP wire is \r\n). compose.yaml now maps
  IAG_SMTP_PORT/USER/PASSWORD/FROM into app env (only HOST was mapped;
  validate_smtp correctly refused boot on the gap — fail-fast worked).

Proofs: pytest 27/27; live E2E PASS — 9 emails through REAL SMTP branch to
aiosmtpd sink on live Postgres, rendered subject/URL/greeting asserted in
sink log, outbox all sent, audit chain valid. First-ever exercise of the
SMTP branch.

Post-proof state: .env SMTP block REMOVED (log-only restored — next campaign
won't dead-letter against a dead sink). Re-enable for proofs: append 5 lines
(IAG_SMTP_HOST=host.docker.internal, PORT=1025, USER/PASSWORD=any, FROM=
iag@localhost), start sink (uv run --with aiosmtpd python scripts/smtp_sink.py
D:\Projects\iag\smtp_sink_log.jsonl 1025), docker compose up -d, then
scripts/live_smtp_proof.py.

Arc status: 1/6 done. Next: feature 2 (live connectors) — needs migration
0004, so do the fresh-volume reset proof (0003 on empty volume) FIRST.
Remaining arc order: 3 remediation, 4 API keys, 5 risk/PDF/SIEM, 6 SCIM etc
(design conversation required before 3-6; no reserved slots for them).

### 2026-08-17 (reminder-email session - FORK A SHIPPED)

- **Fork A built, live-proven, committed 9e3f03b.** Enqueue on campaign
  start (resolved reviewer emails), in-replica worker
  (claim SKIP LOCKED → send outside TX → finalize TX; stuck reclaim,
  retry→dead-letter, log-only dev delivery), read-only API + /outbox
  frontend view, migration 0003 on existing volume.
- Proof: pytest 19/19; smoke.sh PASS incl kill-a-replica with worker
  deployed; scripts/live_reminder_check.py PASS (enqueue → sent within
  poll window → cancel path → chain valid); 0003 via psql.
- Compose now passes reminder/SMTP knobs through with defaults; .env has
  IAG_REMINDER_DELAY_MINUTES=0, IAG_REMINDER_POLL_SECONDS=5 for fast
  proofs (60/60 code defaults remain for any deployment).
- Test gotchas fixed: audit API returns details as JSON string (parse
  before .get); worker skip in test env (SessionLocal points at prod URL).
- Live-script gotchas: unique username per run (import 500s on
  ix_identities_username collision); all call() sites need the session
  cookie (module-level _COOKIE fallback added).
- .gitignore: frontend/tsconfig.tsbuildinfo untracked.

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
- Next up: reminder-email task queue — fork A RATIFIED by user;
  full build spec in the section below. Later: chain anchoring, real
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

## Reminder-email task queue — FORK A RATIFIED (2026-08-17, pre-build)

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

Model — `EmailOutbox` (models/email.py, table `email_outbox`, migration
0003, explicit DDL like 0002):
- id PK; campaign_id FK campaigns CASCADE; review_id FK reviews CASCADE
  (one reminder per review — the natural dedup key); reviewer_id FK
  users CASCADE; recipient TEXT (resolved at enqueue time); subject TEXT;
  body TEXT; due_at TIMESTAMP naive-UTC; sent_at TIMESTAMP null;
  attempts INTEGER default 0; status TEXT pending/sending/sent/failed/
  cancelled.
- Enqueue: on campaign start ONLY (v1): one pending row per review
  created, due_at = now + IAG_REMINDER_DELAY_MINUTES (default 60).
  Campaign cancel marks outstanding pending rows cancelled.

Worker — `app/core/email_worker.py`, asyncio task per replica started
at app startup (FastAPI lifespan in main.py):
- Loop: sleep IAG_REMINDER_POLL_SECONDS (default 60) → claim due rows →
  send → finalize. 
- Claim: SELECT ... FOR UPDATE SKIP LOCKED on Postgres (multi-replica
  safe); SQLite tests serialize, acceptable. Claim TX marks rows
  'sending' + attempts+1. SEND HAPPENS OUTSIDE THE CLAIM TX (network
  I/O never holds DB locks); finalize TX commits sent/failed. Replica
  death between claim and finalize leaves rows 'sending'; reclaim after
  IAG_REMINDER_STUCK_MINUTES (default 15).
- Retry: failed sends retry next poll up to IAG_REMINDER_MAX_ATTEMPTS
  (default 3), then dead-letter (status stays 'failed').
- Send: SMTP via IAG_SMTP_HOST/PORT/USER/PASSWORD/FROM. DEV MODE: host
  unset → log-only delivery (log the email, mark sent) — how the stack
  runs today; keeps smoke honest without an SMTP server. If host IS set,
  creds validated at boot (fail-fast, secrets discipline).
- Audit: one 'email_sent' entry per delivered row via append_audit
  (same-transaction, house pattern). Failed attempts get 'email_failed'
  entries; actor = system (actor_id None, actor_username 'system').

API surface (read-only, CertAdminUser):
- GET /api/reminders/outbox — paged, filter campaign_id + status
- GET /api/campaigns/{id}/reminders — rows for one campaign

Tests (SQLite, log-only send path; no real SMTP):
- enqueue-on-start: start creates one pending row per review, due_at ok
- claim-and-send: due row → sent, audit 'email_sent', sent_at set
- no-double-send: second claim returns nothing (SKIP LOCKED proven on
  Postgres via live script)
- retry-then-dead-letter: failures retry to max attempts then stop
- cancel-cancels: campaign cancel → outstanding rows cancelled
- boot: worker task starts with TestClient context, no error

Live proof (stack): scripts/live_reminder_check.py — login → start
campaign with pending reviews → outbox rows exist via API → wait for
sent (log-only) → audit chain still valid.

Non-goals (do not build): templates/editing UI, HTML email, inbound
mail, read receipts, per-reviewer digesting, email prefs. One plain-
text reminder per pending review, one time, v1.

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
(session 16; phases A-B DONE: A=d529760, B=c1bbfb9+5438605,
suite 233/233, live smoke PASS, all replicas on the Phase B
image). In this chat: build Phase C only - management endpoints
(GET/PUT /api/scim/config, POST/DELETE /api/scim/token,
session-auth AdminUser, audits scim_config_updated/
scim_token_rotated/scim_token_revoked) + frontend (settings
panel reveal-once token modal per ApiKeys.tsx pattern, rules
form enforce->target select + target column, queue chips +
Sync-now link) + client.ts scim namespace + docs/admin-guide.md
(ratified D3 deliverable, plain-English task-shaped) + TSC
gate; green-gate, commit, and stop at the phase boundary.
Docker daemon was healthy at last close - verify before build."

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
