# Feature 4 - API keys (machine access, read-only)

Status: DRAFT 2026-08-20, awaiting USER ratification of decisions D1-D7.
NO feature-4 code before ratification. Fills the REQUIREMENTS.md 4
deferred list ("API keys"). No ARCHITECTURE.md design slot exists yet;
one line is added at ratification (same pattern as feature 3):
"API keys: bearer-token machine access, read-only, role-scoped."

## Goal

Let external systems and scripts read IAG data without a browser
session: named, revocable API keys authenticate via
`Authorization: Bearer`, carry one existing role, and are restricted to
read-only use. The immediate consumers are feature 5 (SIEM export,
risk/PDF reports) and ops scripting (CSV pulls, health checks). Key
lifecycle (create/list/revoke) is admin-only and audit-chained like
every other state change.

## Clean-room divergence from v1 (behavioral, not code)

v1 never built API keys - ROADMAP.md tier 5 lists them as a "bonus"
("Named, revocable connection tokens") and no backend code exists.
v2 designs fresh, so there is no inherited behavior to diverge from;
the only v1 artifact worth noting is its separate tier-5 aspiration
"Per-User Rate Limit", which this spec deliberately does NOT include
(see D7).

Design anchors taken from the v2 arc instead:

- Reuse the five existing Role values (REQUIREMENTS.md 2) - no new
  roles, no scope language. The role IS the scope.
- Storage discipline follows the connector-secret lesson (feature 2):
  secrets are never returned by the API after creation. But unlike
  connector_secret (plaintext by user decision), key material gets a
  one-way hash - keys are credentials presented by strangers on every
  request, and hashing costs nothing at lookup (D2).

## Non-goals (v1 of this feature)

- Write access of any kind (see D1 - this is the headline decision).
- Per-key rate limiting / quotas (D7).
- Key rotation endpoint (rotation = create new + revoke old).
- Fine-grained endpoint allowlists per key (role is the scope).
- OAuth2, mTLS, or any issuance protocol - opaque bearer tokens only.
- Service accounts in the users table (a key is not a login; it never
  gets a password, an identity, or a session cookie).

## Data model - migration 0006

New table `api_keys`:

| column | type | notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(100), unique | human label, shown in UI + audit |
| `key_prefix` | String(16) | first chars of the full key, e.g. `iag_7f3a` - display + leak triage |
| `key_hash` | String(64), unique, indexed | SHA-256 hex of the full key |
| `role` | Enum(Role) | one of the five existing roles (D1 restricts which) |
| `is_active` | Boolean default true | revoke = set false, row kept |
| `expires_at` | DateTime nullable | null = never expires (D5) |
| `last_used_at` | DateTime nullable | best-effort, throttled write (D5) |
| `created_by_id` | FK users SET NULL, nullable | audit trail survives user deletion |
| `created_at` / `updated_at` | DateTime | |

No DELETE endpoint - revocation is soft, rows are permanent (the audit
chain references them by name/id; hard delete would orphan history).

## Key format and storage - decision D2

Full key: `iag_{id}_{token}` where token is `secrets.token_urlsafe(32)`
(43 chars, ~256 bits entropy). Example: `iag_12_9fKx...` (43 chars).

- The `iag_` prefix makes leaked keys greppable in logs/repos.
- The embedded id gives O(1) lookup: parse id -> fetch row -> constant-
  time compare `hmac.compare_digest(sha256(presented), key_hash)`.
- SHA-256 (not bcrypt) is deliberate: the token is a 32-byte random
  secret, not a human password - there is nothing to brute-force
  offline, and SHA-256 keeps per-request auth ~free (bcrypt would burn
  ~100ms x every API call). Same trade GitHub/GitLab make for PATs.
- The full key is returned EXACTLY ONCE, in the create response. List
  endpoints show name/prefix/role/dates only. key_hash is never
  serialized anywhere.

## Auth path - how a key becomes a principal

Resolution order in `get_current_user` (deps.py):

1. `Authorization: Bearer iag_...` header present -> API-key path.
2. Else fall through to the existing `iag_session` cookie (unchanged -
   the browser SPA never changes behavior).

API-key path:

1. Parse `iag_{id}_{token}`; malformed -> 401.
2. Fetch key by id; constant-time `hmac.compare_digest` of
   sha256(full presented key) vs stored key_hash; mismatch -> 401
   (same message as malformed - no oracle).
3. `is_active == false` -> 401 "API key revoked".
4. `expires_at` in the past -> 401 "API key expired".
5. Build `ApiKeyPrincipal` (dataclass with key_id, name, role and an
   `id` property aliasing key_id) - NOT a User row. Guards and
   endpoints that only read `.role` / `.id` accept it unchanged.

Two hard restrictions enforced AT THE PRINCIPAL LAYER (single choke
point, not per-router):

- **Read-only (D1)**: if `request.method not in ("GET", "HEAD",
  "OPTIONS")` -> 403 "API keys are read-only". One check covers every
  write endpoint that exists or will exist.
- **Keys cannot manage keys**: path starts `/api/api-keys` -> 403
  regardless of role. A leaked key must never be able to mint friends.

### Personal endpoints (decision D4)

Endpoints whose semantics are "the logged-in human" must not quietly
return empty/garbage for a key. They get a new dependency alias
`SessionUser` (cookie auth only; key principal -> 403 "API keys cannot
access personal endpoints"):

- `/api/auth/me`, `/api/auth/logout`, `/api/auth/change-password`
- `/api/reviews/queue`, `/api/reviews/count`, `/api/reviews/history`,
  `PUT /api/reviews/{id}` (reviewer-scoped by user.id)
- `/api/reminders/outbox` scoped variants if any (audit each router
  during phase B; the phase-B test list is the checklist)

`GET /api/dashboard` is MIXED (portfolio counts + my-workload). For a
key principal it returns the portfolio sections and zeroes for the
personal section, with `"principal": "api_key"` in the payload - an
integration pulling dashboards gets real data, not a 403. (D4)

`GET /api/reviews/{id}` stays role-guarded (auditor role can view) and
works for keys with the auditor role - reads are the point of D1.

## Audit

Key lifecycle events only - NOT per-request auditing (that would flood
the hash chain; usage evidence = `last_used_at` + nginx access logs):

- `api_key_created` details: {name, key_id, role, expires_at}
- `api_key_revoked` details: {name, key_id}

Actor = the admin user performing the lifecycle action. Entries append
inside the same transaction as the change (invariant 10). Expiry is
passive (checked at auth time) and emits no event.

`last_used_at` updates best-effort: on a request whose key's
`last_used_at` is null or >60s old, one UPDATE, no audit entry, wrapped
so a failure never fails the request.

## API (new router `routers/apikeys.py`, prefix `/api/api-keys`)

| method + path | guard | behavior |
|---|---|---|
| `GET /` | AdminUser | list: name, key_prefix, role, is_active, expires_at, last_used_at, created_at. Sorted newest first. |
| `POST /` | AdminUser | body {name, role, expires_at?}. Validates name non-empty/unique (409 dup), role in allowed set (400 under D1). Returns 201 with `key` = full key ONCE + the list-shaped row. Audit `api_key_created`. |
| `POST /{id}/revoke` | AdminUser | is_active=false. Idempotent (revoking a revoked key = 200 no-op). Audit `api_key_revoked`. |

No PUT (keys are immutable; rotate = create + revoke). No DELETE (D5).
OpenAPI gains a bearer scheme so /api/docs shows how to use keys.

## Frontend (minimal surface)

New "API Keys" view, system_admin nav only:

- Table: name, prefix (mono), role chip, status (active/expired/
  revoked derived at render), expires, last used, created.
- Create dialog: name, role select (D1-restricted set), optional
  expiry date.
- Reveal-once modal after create: full key, copy button, "store it now
  - it will not be shown again" warning.
- Revoke button with confirm.

client.ts gains an `apiKeys` namespace. TSC clean; no other views
touch auth behavior (cookie flow untouched).

## Tests (pytest, SQLite, real code paths)

Auth path (via a real key created through the API):

- Bearer key reaches `GET /api/dashboard` (200, personal zeros,
  `principal: api_key`).
- Wrong token -> 401; revoked -> 401; expired -> 401; malformed -> 401.
- Key on a GET allowed by its role (auditor: `/api/audit`).
- Key role below endpoint guard -> 403 (report_viewer key on
  `/api/audit`).
- ANY write method with a key -> 403 read-only (spot-check POST
  `/api/identities`, PUT remediation settings).
- Key on `/api/api-keys` GET -> 403 keys-cannot-manage-keys.
- Key on `/api/reviews/queue` -> 403 personal-endpoint.
- Cookie flow regression: browser client still works for every
  existing test (the suite IS this proof - zero new failures).

Lifecycle:

- Create -> response contains full key exactly once; list shows prefix
  only, never the key or hash.
- Duplicate name 409; bad role 400; past expires_at 400.
- Revoke -> 401 on next use; revoke twice -> 200 idempotent.
- Audit entries `api_key_created` / `api_key_revoked` exist and chain
  verifies.
- `last_used_at` set after first use; not rewritten within 60s.

## Live proofs (real Postgres, per house style)

`scripts/live_apikey_check.py` on the running stack:

1. Admin login (cookie) -> create auditor key with expiry.
2. `curl`/httpx with Bearer: dashboard 200, audit export CSV non-empty,
   identities list 200.
3. Write attempt -> 403 read-only; key-management attempt -> 403.
4. Revoke -> Bearer now 401.
5. Audit chain verify still PASS.
6. Cleanup: revoke (row stays - it is audit evidence, matches DB
   residue conventions).

## Build phases (each ends green: pytest + stack healthy + commit)

- **A - model + security core**: migration 0006, `models/apikey.py`,
  `core/apikeys.py` (generate/parse/hash - pure functions, unit-tested
  in isolation like remediation_engine).
- **B - auth wiring**: principal union in deps.py, read-only choke,
  keys-manage-keys block, SessionUser alias, personal-endpoint switch
  (checklist per phase-B test list), dashboard mixed-payload handling.
- **C - API + frontend**: router + audit entries + OpenAPI bearer
  scheme; API Keys view + nav + client namespace.
- **D - live proof + HANDOFF**: script, run on stack, HANDOFF update.

## Open decisions for ratification

- **D1 scope - THE BIG ONE**: keys are READ-ONLY and restricted to the
  two read roles `auditor` and `report_viewer` (create with any other
  role -> 400). Enforcement lives in the principal layer (method
  check), not per-router, so it cannot drift as endpoints are added.
  Alternative rejected: full-role keys (a system_admin key = full
  write control from a leaked string; nothing in the arc - features
  5-6 are reads + SCIM - needs it). If scripted WRITES are ever
  wanted, that is a new decision and a new spec section, not a quiet
  relaxation.
- **D2 format/storage**: `iag_{id}_{token_urlsafe(32)}`; SHA-256 hash
  at rest; prefix + once-only reveal. (Reasoning above; bcrypt
  explicitly considered and rejected for per-request cost.)
- **D3 transport**: `Authorization: Bearer` header ONLY. No X-API-Key
  alias, no query-param support (logged everywhere - never put secrets
  in URLs), no cookie for keys. Bearer shape matches what SIEM/report
  tooling already speaks.
- **D4 personal endpoints**: explicit SessionUser alias + 403 for keys
  on reviewer-scoped/personal routes; dashboard returns portfolio
  data with zeroed personal block instead of 403. Rejected: letting
  keys hit personal endpoints and returning empty (silent lies).
- **D5 lifecycle**: create/list/revoke only; soft revoke (is_active
  false, row permanent); optional expires_at (null = never); no PUT,
  no DELETE, rotation = create+revoke. Rejected: hard delete (orphans
  audit history); auto-expiry enforcement job (checked at auth time -
  no cron needed).
- **D6 audit granularity**: lifecycle events only, no per-request
  audit; last_used_at throttled 60s best-effort. Rejected: auditing
  every authenticated request (chain flood; nginx logs already cover
  access evidence).
- **D7 rate limiting**: none in this feature (v1 aspiration not
  carried). Local nginx-fronted tool; if it ever gets exposed beyond
  localhost, add per-key limits at nginx FIRST. Revisit with feature 5
  SIEM polling if it matters.

## Settings / env

None. No new env vars, no compose.yaml change (feature-2 lesson: only
map env that actually overrides). The 60s last_used_at throttle and
token length are constants in `core/apikeys.py`, not knobs.
