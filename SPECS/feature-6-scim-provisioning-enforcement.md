# Feature 6 - SCIM provisioning & enforcement write-back

Status: RATIFIED (session 16, 2026-08-22 - user rulings: D1 bundle;
D2, D4-D8 as drafted; D3 ratified with the schema-alignment
amendment). Phases A-E unlocked.
Fills the REQUIREMENTS.md 4 deferred-list entry "SCIM", the ARCHITECTURE.md
slot line added at ratification (proposed: "SCIM provisioning and
enforcement: inbound token-authed SCIM user feed; enforcement is connector
write-back driven by remediation actions."), and - the explicit promise -
feature 3's D1: "Real enforcement (disabling an account in the source
directory) is write-back - that is feature 6 (SCIM-class) with its own
spec, using the connector infrastructure."

## Goal

The last feature closes the identity lifecycle loop at both ends:

1. **Inbound SCIM 2.0 server** (`/api/scim/v2/*`): an IdP (Okta, Entra
   ID, any SCIM client) pushes joiner/mover/leaver events as Identity
   records - create, update, deactivate - token-authed, audit-chained.
2. **Outbound enforcement write-back**: a remediation action with
   `action_type=enforce` writes the reviewer's revocation back to the
   source directory through the feature-2 connector infrastructure
   (remove the entitlement / disable the account), riding the existing
   remediation state machine (approval gate, retry, audit).

Together: joiner (SCIM create) -> access discovered (connectors) ->
certified (campaigns) -> revoked (review) -> enforced (write-back) ->
leaver (SCIM deactivate). SCIM supplies identity lifecycle; connectors
supply the access mirror; campaigns decide; enforcement acts. Each
layer stays single-purpose.

## Clean-room divergence from v1 (behavioral, not code)

v1 shipped the inbound half only (`scim_service.py` + tier5 routes;
read-only reference, no code copied). v1 had NO outbound enforcement
anywhere - that half is designed fresh against feature-2 adapters.

Kept from v1, adapted:
- Endpoint set: ServiceProviderConfig, Users list/get (with EQ filter
  on userName / emails.value / externalId), create, PUT, PATCH
  (replace-only subset), DELETE. 1-based startIndex/count paging.
- SCIM error envelope (schemas + status + detail) on every failure.
- Bearer-token auth for the protocol surface; admin endpoints for
  config/token management.

Designed out (v1 defects, verified in source):
- **Token at rest**: v1 stored the bearer token reversibly encrypted
  in a SystemSetting row. v2: SHA-256 hash at rest, reveal-once
  generation, never readable back (feature-4 key pattern).
- **Auto-created login accounts**: v1 defaulted
  `auto_create_user_account=True` - an IdP push could mint a
  governance-tool login (with no password and no admin surface to
  manage it). v2: designed out entirely. Verified against the codebase:
  v2 has no user-management endpoint (only bootstrap mints the first
  admin), so the option is unimplementable without building user admin
  first - out of scope, and feature-3 D1's rule stands regardless:
  governance decisions never touch login accounts.
- **Hard delete**: v1's `deprovision_action=delete` hard-deleted the
  Identity (and its audit FKs). v2: DELETE is soft (is_active=False),
  always; identities are governance records.
- **Separate event log**: v1 wrote a parallel `SCIMEvent` table via
  its own commit - a second, non-chained, non-atomic source of truth.
  v2: the hash-chained audit trail IS the event log (invariant 10),
  one entry per SCIM write in the same transaction; the SIEM feed
  carries them out.
- **Advertised lies**: v1's docstring listed `GET /Groups` and its SPC
  claimed `sort: true` - neither existed. v2: SPC reflects reality
  (filter: EQ subset only, sort: false, bulk: false, etag: false);
  Groups is a non-goal (IAG mirrors entitlements; it does not manage
  them for the directory).
- **Phone placeholder**: v1 mapped `phone = emails[0].value` behind a
  `# placeholder` comment. v2: Identity has no phone; do not fake one.
- **Config store**: v1 SystemSetting key/value blob. v2: single-row
  typed `scim_settings` table (remediation_settings pattern).

## Non-goals (v1 of this feature)

- SCIM Groups, /Me, /Bulk, server-side sorting, ETag/IfMatch.
- Outbound provisioning (IAG creating accounts in directories): IAG
  governs access, it does not originate identities or access.
- PATCH add/remove operations (replace-only subset; SCIM clients in
  the wild use replace for deprovision).
- Auto-linking SCIM users to accounts at ingest time (connector sync
  already links by exact username/email on its next run - no new
  linking code).
- SCIM-born manager hierarchy (manager_employee_id is governance
  data, curated in IAG, not asserted by the IdP feed).
- Enforcement for csv/xlsx sources (nothing to write back to - a CSV
  is not a live directory), for accounts with no source-side match,
  or as remediation `default_action` (enforcement requires an
  explicit matching rule; an unfiltered catch-all that disables
  accounts in a production directory must be a deliberate act).
- Rate limiting on the SCIM surface (nginx concern if ever exposed
  beyond localhost; feature-4 D7 deferral carries).

## Part 1 - Inbound SCIM 2.0 server

### Data model - migration 0008

New table `scim_settings` (single row, id=1 enforced; remediation_settings
pattern - whole-value JSON replace on write):

| column | type | notes |
|---|---|---|
| `id` | Integer PK (always 1) | |
| `config` | Text (JSON) | `{enabled}` |
| `token_hash` | String(64), nullable | SHA-256 of the bearer token; null = no token = surface returns 503 |
| `token_prefix` | String(16), nullable | display ("iag_sc_abc...") |
| `token_created_at` | DateTime, nullable | |
| `updated_at` | DateTime | |

Defaults on first boot: enabled=false. The surface is
OFF until an admin turns it on and generates a token (two deliberate
acts; nothing listens until both).

No enum change: `Identity.source` is a plain String column (default
"manual"), not a SourceType value - SCIM provenance is just
`identity.source = "scim"`, no ALTER TYPE, no new source type.
Enforcement (Part 2) targets existing ldap/entra/sql sources; no
`scim` DataSource is ever created (SCIM provisions identities, not
accounts - accounts arrive via connectors/CSV as always).

### Authentication

One bearer token per installation (feature-4 shape, minimal for a
single-tenant local tool):

- POST /api/scim/token (AdminUser) generates `iag_scim_{token_urlsafe(32)}`,
  stores SHA-256 + prefix + created_at, returns the full token ONCE.
  Regenerating rotates (old token dies at the same commit).
- Dependency `require_scim_token`: Authorization Bearer only; constant-
  time compare against token_hash; disabled surface or null token ->
  503 SCIM error envelope; bad token -> 401 envelope + WWW-Authenticate.
- Config and token management endpoints are session-auth (AdminUser)
  - the protocol surface is the only bearer surface. SCIM tokens are
  NOT ApiKey rows (different lifecycle, no role semantics - a SCIM
  token's authority is exactly the SCIM surface, never /api/* reads).

### Endpoints (new router `routers/scim.py`, prefix `/api/scim/v2`)

Mounted under /api/* deliberately: nginx already routes /api/* to the
replicas, so the SCIM surface needs no nginx location, no new origin,
no CORS story - it is just another API router to the proxy (v1's
/scim/v2/* prefix outside the API tree would need its own location
block and auth-bypass reasoning; /api/scim/v2 gets both for free,
with auth handled by the token dependency, not by nginx).

| method + path | behavior |
|---|---|
| `GET /ServiceProviderConfig` | Honest capabilities: patch {supported: true}, bulk false, filter {supported: true, maxResults: 200}, sort false, etag false, changePassword false. |
| `GET /Users` | List. 1-based startIndex (default 1), count (default 100, max 200). Filter: `userName eq "x"`, `emails.value eq "x"`, `externalId eq "x"` - EQ only, one clause; anything else -> 400 envelope. Returns totalResults/startIndex/itemsPerPage/Resources. |
| `GET /Users/{id}` | Single user by SCIM id. 404 envelope if absent. |
| `POST /Users` | Create. 400 missing userName; 409 if userName, email, or externalId (employee_id) already exists - an IdP re-pushing an existing user gets a protocol answer, never a constraint 500 (real SCIM clients recover from 409 by GET-by-filter then PUT/PATCH). externalId required (it becomes employee_id - the join key; v1's random-fallback invented untrackable keys). 201 + full resource. |
| `PUT /Users/{id}` | Replace mutable attrs (userName, name, emails, title, department, displayName, active). userName/email uniqueness 409. 200 + resource. |
| `PATCH /Users/{id}` | Replace-only subset: Operations[].op=replace on paths active / userName / name.givenName / name.familyName / title / department / emails / displayName, PLUS the path-less form (value object keyed by attribute) - the shape Okta's deprovisioning actually sends. add/remove -> 400 envelope (advertised nowhere). 200 + resource. |
| `DELETE /Users/{id}` | Soft deprovision: is_active=false. ALWAYS soft (D2). 204. Idempotent: deleting an inactive identity re-sets the same value and still 204s, still audited (the IdP retried; record it). |

### SCIM id scheme

SCIM id = `identity.employee_id` (externalId). Rationale: employee_id
is IAG's canonical join key (invariant 1), stable across IdP retries,
and round-trips through the filter (`externalId eq`). v1 used the
surrogate int id - stable, but meaningless to the IdP and a second
identifier to track. employee_id max length 100 fits SCIM's free-form
id; /[A-Za-z0-9-._~:@!$&'()*+,;=%]+/ accepted as-is (no normalization -
the IdP owns this key; IAG stores what it is given). Consequences:
PUT/PATCH carrying an externalId that DISAGREES with the path id ->
400 (the client is confused about which user it is writing; silently
rewriting employee_id would break every join key in the system).
Absent externalId in PUT/PATCH bodies: fine, id is immutable.

Schema alignment (ratified invariant, session 16): IAG assumes no
directory schema anywhere. Inbound: the IdP declares its own stable
key as externalId, and employee_id stores that value verbatim - an
AD-backed IdP pushes UPN, an HR-driven one pushes employee numbers;
each source aligns itself by choosing what it declares. Outbound:
enforcement resolves directory-native identifiers from per-source
connector_config (account_attr for AD sAMAccountName/UPN/mail,
object-id resolution for Entra, admin-supplied statements for SQL) -
never a hard-coded attribute. This invariant ships in the end-user
documentation (Part 3).

### Resource mapping (Identity <-> SCIM User)

Out (Identity -> SCIM): schemas, id=employee_id, externalId=employee_id,
userName (fallback email, fallback f"user_{id}"), active=is_active,
name.givenName/familyName, displayName (computed first+last),
emails [{value, type: work, primary: true}] when present, title=
job_title, department, meta.resourceType/created/lastModified
(naive-UTC + "Z", house convention). phoneNumbers: never emitted
(v1 placeholder designed out).

In (SCIM -> Identity): userName -> username; primary email (fallback
first) -> email; name.givenName/familyName -> first/last; displayName
parsed ONLY when name parts absent; title -> job_title; department ->
department; active -> is_active. Manager, phone: ignored (non-goals).

### Audit

One entry per SCIM write, same transaction (invariant 10):
`scim_user_created` / `scim_user_replaced` / `scim_user_patched` /
`scim_user_deprovisioned`, entity_type "identity", entity_id, details
{operation, userName, externalId, active}. Actor: `actor_id=null,
actor_username="scim"` - the first non-human actor in the chain; the
feed (feature 5) carries actor_username, so SIEM consumers see the
provenance without schema change. Reads (list/get/SPC) never audit
(house rule; v1's SCIMEvent logged reads too - noise designed out).
Failed writes (400/409/404) audit nothing - nothing changed.

## Part 2 - Enforcement write-back (the promised half)

Feature 3 D1: "Real enforcement (disabling an account in the source
directory) is write-back - that is feature 6 ... using the connector
infrastructure." This is that feature. It does not touch remediation's
workflow (rules, approval gate, worker discipline stay feature-3's);
it adds one delivery channel and one driver.

### What enforcement does

A remediation action with `action_type="enforce"` writes the reviewer's
revocation back to the source directory, through the feature-2 adapter
for the account's source:

- **remove_entitlement**: remove the entitlement from the user in the
  directory (LDAP: delete the member value from the group entry; Entra:
  DELETE group member; SQL: no default - admin-supplied statement, see
  adapters below).
- **disable_account**: deactivate the user in the directory (LDAP:
  modify replace on a configurable attribute, e.g. pwdLastSet /
  nsAccountLock / custom; Entra: PATCH accountEnabled=false; SQL: admin
  statement).

The action-level choice comes from the rule: `enforce` rules gain a
`target` field (`remove_entitlement` | `disable_account`; default
`remove_entitlement` - least-destructive default, a deliberate default
setting for the most dangerous action class in the system).

### Where it hooks in

Remediation stays the workflow layer; enforcement is a delivery
channel. The remediation worker's `run_pass` dispatches on
`action_type` (`notify_owner` / `webhook` today); enforcement adds a
third arm, same claim -> deliver-outside-TX -> finalize discipline,
same approval gate (require_approval stays available - writing to a
production directory behind a governance decision warrants a human
eye by default), same retry/stuck-reclaim semantics, same audit.

No new worker, no new state machine, no new tables for the action
itself - `action_type="enforce"` rides the existing
`remediation_actions` row (VARCHAR column, verified - no enum
surgery), carrying `target` in the existing snapshot JSON plus
`enforcement` result detail in the existing `result` field.

### Rule surface

`remediation_rules.action` gains value `enforce` (VARCHAR, no
migration; ACTIONS validator extended; default_action still rejects
it - enforcement must be a matching rule, never the fallback).

An `enforce` rule's filter shape (source, privilege, pattern) is
unchanged; `target` is the only new field, stored in the rule row as
a plain column (`target` String(20) nullable, null = remove_entitlement).
Migration 0008 adds the column (inspector-guarded add_column, 0004
pattern). Rule validation: target in {remove_entitlement,
disable_account}; enforce + webhook_url is a 400 (webhook_url is
webhook's field, not enforce's).

`enforce` rules and existing rules coexist: one revocation can trigger
notify_owner + webhook + enforce actions if multiple rules match
(feature-3 semantics: all matched rules fire, one action each).

### Resolution: finding the target in the directory

The action's frozen snapshot carries account_value, entitlement_name,
source name. Enforcement must translate these to directory-native
identifiers before writing:

- **ldap**: search the directory for the account by the connector's
  configured account_attr (sAMAccountName / userPrincipalName / mail,
  per the source's connector_config) to find the user DN. For
  remove_entitlement: resolve the group DN by searching base_dn for
  the entitlement name (cn=NAME under the configured group base) - the
  entitlement name IS the group name (sync's _dn_to_name collapses
  memberOf DNs to names; enforcement re-expands the name to a DN).
  disable_account: modify the user entry directly.
- **entra**: account_value is userPrincipalName. Both entra targets
  address users by object id, so resolve UPN -> id first (GET
  /users?$filter=userPrincipalName eq 'X'). remove_entitlement:
  resolve group object id by displayName (GET
  /groups?$filter=displayName eq 'NAME'), then DELETE
  /groups/{gid}/members/{uid}/$ref. If the user is not a (transitive)
  member, treat as already-clean and succeed (idempotent: revoking
  an entitlement the directory already removed is a success, not an
  error). disable_account: PATCH /users/{uid} accountEnabled=false.
- **sql**: there is no default write-back (a SQL source is a custom
  integration by definition). The rule's source filter selects a sql
  source; its connector_config may carry `remove_entitlement_sql` and
  `disable_account_sql` statements (admin-supplied, :account_value /
  :entitlement_name bind params, run via the source's existing sync
  engine EXCEPT not READ ONLY - enforcement is the one deliberate
  write; SET TRANSACTION READ WRITE, psycopg2).

If resolution fails (user not found, group not found, no statement
configured), the action FAILS with a clear result message - it never
guesses, never writes by approximate match.

If the account has no entitlement (entitlement_name is null in the
snapshot - CSV-grain accounts on connector sources), remove_entitlement
fails with "no entitlement in snapshot"; disable_account proceeds
(the account itself is the target).

### Idempotency & safety

- Directory-side state is authoritative: if the entitlement is already
  absent (or user already disabled), enforcement completes without
  writing (and says so in result). SCIM Delete and enforcement both
  respect "already-clean = success" - repeated IdP retries or worker
  retries after a partial failure never double-write.
- Destructive radius: enforcement can only ever target the account's
  own source (rule source filter or account's source via snapshot;
  disable_account additionally requires the resolved user DN/UPN to
  match the account_value it started from). Identity mismatches abort.
- The approval gate stays between trigger and delivery for enforce
  rules unless the admin explicitly opts out per-rule.
- Every enforcement attempt lands one audit entry at finalize
  (existing `remediation_action_executed` shape, action_type=enforce,
  result includes target + outcome).
- Enforcement never deletes mirror rows. The mirror reports reality;
  per-account entitlement membership is not stored for connector
  accounts at all (sync recomputes it from the directory each run -
  Account.entitlement_id stays null by design), so there is nothing
  to unwind locally: the next sync's snapshot simply no longer lists
  the entitlement for that account, and the catalog row's last_seen_at
  freezes (stale, not deleted) if no other account carries it. If the
  directory-side change fails, the mirror is untouched (correct:
  reality did not change).

### Mirror drift after enforcement (accepted, documented)

Enforcement writes to the directory; the mirror updates only at the
next sync. Between enforcement and next sync, the mirror shows access
that no longer exists (drift = enforcement latency). Accepted: drift
window = sync interval; the action row + audit are the enforcement
evidence in the meantime. A "sync now" hint on completed enforce
actions (frontend nicety) closes the loop visually.

## Part 3 - Management surface (session-auth, AdminUser)

| method + path | behavior |
|---|---|
| `GET /api/scim/config` | `{enabled, token_prefix, token_created_at}` - no secrets read back (token_hash never returned). |
| `PUT /api/scim/config` | `{enabled}` whole-value replace; audit `scim_config_updated`. |
| `POST /api/scim/token` | Generate + rotate: new token returned ONCE (201 `{token}`); old token invalid at same commit; audit `scim_token_rotated`. |
| `DELETE /api/scim/token` | Kill the token (surface -> 503 until regenerated); audit `scim_token_revoked`. |

These sit on the admin router in `routers/scim.py` (one router file
for the whole feature; the protocol surface and management surface
share the module - the 400-line router cap forces the SCIM mapping
helpers into `app/core/scim.py` anyway, keeping the router thin).

`app/core/scim.py`: SCIM User <-> Identity mapping (pure functions),
SCIM error envelope helper, filter parser (EQ-only, one clause,
fullmatch-anchored - v1's re.match anchored only the start, so
trailing junk after the quoted value was silently accepted; v2's
parser accepts the three clause shapes and nothing else), SPC
document. Pure, unit-testable, no DB.

### End-user documentation (ratified deliverable, session 16)

The join-key and schema-alignment story must be legible to the
person configuring IAG against a real IdP, not just to a spec
reader. Deliverables:

- `docs/admin-guide.md` (new repo dir docs/): an administrator's
  guide covering - enabling SCIM + generating/rotating the token;
  pointing an IdP at /api/scim/v2 (Okta + Entra SCIM-app settings,
  bearer token placement); how externalId becomes the join key and
  why it must be the authoritative source's stable key (AD-UPN vs
  HR-number examples); remediation enforce rules end-to-end
  (target choice, approval gate, mirror-drift window, "sync now");
  and per-source connector_config fields that carry schema
  alignment (account_attr, disable attribute, SQL statements with
  bind params). Plain-English, task-shaped ("To connect Entra:"),
  plain-English-content skill style.
- Settings panel (Phase C): the reveal-once token modal carries a
  one-paragraph hint - the token is shown once; the join key is
  whatever your IdP sends as externalId; pick a stable one (UPN or
  employee number, not display name).
- Remediation rules form (Phase C): enforce-target help text -
  remove_entitlement needs the entitlement name to be the directory
  group name; disable_account writes to the account_attr the
  connector matches on; SQL sources need admin-supplied statements.

This is a Phase C deliverable (ships with the UI it documents),
checked in the phase gate like any other work product.

## Frontend (minimal surface)

- **Settings panel (System section or Remediation view header)**:
  SCIM enable toggle + token generate/rotate/revoke with reveal-once
  modal (ApiKeys.tsx pattern), token prefix + created display.
  Admin-gated.
- **Remediation rules form**: action select gains `enforce` -> target
  select (remove_entitlement / disable_account) appears; rules table
  gains target column. Existing form patterns, no new libs.
- **Remediation actions queue**: action_type chip "enforce" + target
  in the snapshot summary; "Sync now" link on completed enforce rows
  (existing POST /api/sources/{id}/sync). Existing table patterns.
- client.ts: scim namespace (config/token) + remediation rule/action
  type extensions. No new views, no new routes.

## Settings / env

No new env knobs: page cap (200) and filter maxResults are constants
in the router; enforcement has none (it rides remediation worker
settings); SCIM mapping is protocol, not config. No compose.yaml
change.

## Tests (pytest, SQLite, real code paths)

SCIM core (pure, unit):
- Mapping round-trips Identity -> SCIM -> Identity for every field;
  fallbacks (userName <- email <- user_{id}); displayName parse only
  when name parts absent.
- Filter parser: the three EQ clauses parse; and/or/ne/co/sw/ew,
  multiple clauses, unquoted, garbage -> ValueError.
- SPC document is honest (no true we cannot serve).

SCIM API (integration, TestClient):
- 503 when disabled or token null; 401 bad/missing token; both as
  SCIM error envelopes with correct schemas urn.
- CRUD: create 201 + resource echo + audit `scim_user_created`
  (actor_username "scim"); dup userName 409; dup email 409; missing
  userName 400; missing externalId 400.
- List: paging (startIndex/count), totalResults, max-count clamp,
  each filter field, filter 400s on unsupported ops.
- PUT/PATCH: replace semantics incl. PATCH active flip (the depro
  path Okta actually uses); PATCH add/remove 400; uniqueness 409s.
- DELETE: is_active=false, 204, audit written; re-DELETE on inactive
  -> 204, second audit (IdP retry recorded).
- Config/token endpoints: session-auth 401/403 as an admin surface;
  token reveal-once; rotate invalidates old; delete -> 503 surface.
- Chain verifies after every flow (verify_chain).

Enforcement (integration + worker):
- Engine/rule: enforce rules match exactly like notify_owner rules;
  target validation (400s); enforce+webhook_url 400; default_action
  rejects enforce (400).
- Trigger: revoke with enforce rule -> action row action_type=enforce,
  snapshot carries target; approval gate applies; approve -> worker
  claims; audit entries as specced.
- Worker/adapter: ldap enforcement via ldap3 MOCK strategy (feature-2
  pattern - pytest runs without Docker; glauth is live-proof-only) -
  group membership actually removed from the mock entry, re-sync shows
  the entitlement gone; already-clean second run succeeds without
  writing. Entra via httpx.MockTransport (resolution + member delete +
  already-clean). SQL via a real SQLite file (bind params; statement
  absent -> fail; READ WRITE transaction). Failure paths: user/group
  unresolvable -> failed with clear result; identity-mismatch aborts.
- Mirror untouched: after enforcement, account row unchanged until a
  sync runs (assert no row deleted/changed).

Live proofs (real Postgres, per house style):
- `scripts/live_scim_check.py`: enable + token -> create user via
  bearer (assert audit actor "scim") -> PATCH active=false -> DELETE
  -> list filters -> rotate kills old token -> revoke. Chain valid.
- `scripts/live_enforce_check.py`: glauth profile stack; seed source +
  connector config + sync (members present) -> campaign -> revoke ->
  enforce rule action approved -> worker removes member from group
  (assert via glauth search: member gone) -> re-sync -> entitlement
  absent from account's snapshot, account row intact -> chain valid.
  Plus disable_account leg against glauth (attribute flip) and the
  already-clean idempotent second enforcement.

## Build phases (each ends green: pytest + stack healthy + commit)

- A - migration 0008 (scim_settings + rules.target column) + models +
  core/scim.py (pure mapping/filter/SPC) + unit tests.
- B - SCIM protocol router + token dependency + integration tests.
- C - management endpoints + frontend (settings panel, rules form,
  queue chips) + client types + docs/admin-guide.md (ratified
  deliverable) + TSC.
- D - enforcement: rules target + trigger wiring + worker enforce arm
  + adapter write-backs (ldap live-capable, entra MockTransport, sql
  file) + tests.
- E - live proofs (glauth enforce + disable, SCIM surface) + HANDOFF.

## Decisions (ratified session 16, 2026-08-22)

All eight ratified. D1: bundle (one feature, phases A-E). D3:
ratified as amended - schema alignment at the value level + the
end-user docs deliverable (Part 3). D2, D4-D8: as drafted.

- **D1 THE BIG ONE - bundle**: inbound SCIM + outbound enforcement in
  one feature. They share the SCIM-class identity-lifecycle theme,
  but the halves are otherwise independent (different tables,
  routers, workers' seams, tests, live proofs). Alternatives: split
  into 6a SCIM + 6b enforcement (two specs, two ratifications, two
  phase sets - the arc rule demands a spec before each anyway; this
  is the honest option if you want smaller ratification units), or
  enforcement only (drops the deferred-list "SCIM" entry - the
  REQUIREMENTS deferred list explicitly names SCIM, and v1 shipped
  it; dropping needs its own deliberate decision).
- **D2 deprovision semantics**: DELETE is always soft (is_active=false
  on the identity; accounts untouched). v1's hard-delete option
  designed out - identities are governance records; deleting one
  orphans its accounts, breaks FKs on reviews/audit. Alternative
  rejected: keep both options (the delete branch is the one that
  corrupts; soft is the only safe default and the only mode).
- **D3 SCIM id = employee_id**: stable join key, filter round-trip,
  no second identifier to maintain. Alternatives rejected: surrogate
  int (v1 - meaningless to the IdP), separate scim_id column (a new
  identifier for nothing: externalId IS the IdP's key for the user,
  and it is already unique).
  RATIFIED AS AMENDED (session 16): user requirement - the join key
  must align to the authoritative source's schema (AD may use UPN;
  Entra differs). Resolution: alignment happens at the VALUE level,
  not the id-scheme level - externalId is the IdP's own declaration
  of its stable key and becomes employee_id verbatim (no IAG-side
  schema assumption exists to misalign); directory-side alignment
  lives in per-source connector_config (account_attr, disable
  attribute, admin SQL), now stated as a ratified invariant; schema
  introspection/discovery designed out (fixed operations, per-source
  config is the mechanism); end-user documentation of all of this is
  a ratified deliverable (Part 3).
- **D4 token model**: single installation-wide SCIM token, SHA-256
  hash at rest, reveal-once, rotate = new + old dies at commit; NOT
  an ApiKey row (SCIM writes are not read-only - the feature-4 key
  model, with its read-only principal choke, is structurally wrong
  for an inbound writer; a SCIM token's authority is the SCIM surface
  only). Alternatives rejected: multiple tokens (multi-tenant
  machinery for a single-tenant tool), ApiKey with a scim "role"
  (overloads feature-4's read-only guarantee).
- **D5 enforce as remediation channel**: action_type=enforce rides
  the existing state machine (approval gate, retries, worker) rather
  than a bespoke enforcement pipeline. Alternatives rejected: direct
  synchronous write-back at review-submit time (no approval gate, no
  retry, directory latency inside the review request - a slow DC
  blocks the certifier; rejected), separate enforcement table +
  worker (a second state machine to maintain for identical
  semantics).
- **D6 approval default for enforce**: require_approval defaults ON
  for enforce rules (human sign-off before writing to a production
  directory). Alternatives rejected: default off (auto-enforcement
  writes to directories with a 30s worker delay - one mis-scoped
  rule and a rule matching too broadly can strip access at scale;
  the approval click is the throttle), per-target defaults (two
  settings to reason about).
- **D7 SQL write-back statements**: admin-supplied per-source
  statements in connector_config (bind params, validate-at-save =
  EXPLAIN or rollback-wrap). Alternative rejected: code-defined
  callbacks per "SQL flavor" (a directory is not a SQL source; there
  is no generic disable-user SQL; the admin owns the integration).
- **D8 new deps**: none. httpx + ldap3 already present (feature 2);
  token gen + hashing are stdlib; SCIM envelope/mapping are pure
  code. (glauth already a compose profile.)

A note on dependencies between the halves: enforcement (Part 2) does
not depend on SCIM (Part 1) at all - they share only the "identity
lifecycle" theme. If ratified as one feature, build phases A-E run in
order anyway (A builds both migrations together). If you would rather
ratify 6a/6b separately, say so and the spec splits along Part 1 /
Part 2 with zero rework.


