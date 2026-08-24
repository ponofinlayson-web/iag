# Changelog

All notable changes to IAG are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[SemVer](https://semver.org/).

## [0.3.0] - 2026-08-24

Feature 7: RBAC user management and the theme system (light/dark with
accent dispersion). Users are administered in-app by system_admins;
the UI gains a validated light palette and a deliberate accent
hierarchy (identity + state, not decoration).

### Added

**User management (backend, system_admin)**
- `GET /api/users` - list with role, status, lock state, `last_login`
  from the most recent login audit row, and failure counts.
- `POST /api/users` - create a login account on an existing identity
  (admin-set password, `must_change_password` enforced; rejects
  identities that already have a user).
- `PUT /api/users/{id}/role` - change role; applies on the user next
  request (fresh DB role read), no re-login required.
- `PUT /api/users/{id}/status` - deactivate/reactivate. Users are
  never deleted, so the audit trail keeps referential integrity;
  deactivated users are rejected at login.
- `PUT /api/users/{id}/unlock` - clear lockout (failed-attempt counter
  and `locked_until`).
- `PUT /api/users/{id}/reset-password` - admin-set replacement with
  `must_change_password`.
- Self-guards: an admin cannot change their own role or deactivate
  their own account (409).
- All mutations audit-chained (`user_created`, `user_role_changed`,
  `user_status_changed`, `user_unlocked`, `user_password_reset`).

**Users view**
- DataTable over the user list: role/status badges, must-change and
  failure columns, last login, per-row actions (role, unlock when
  locked, deactivate/reactivate, reset password) with self-guards
  mirrored client-side as disabled buttons.
- Add-user modal with identity `Typeahead`, role picker, and
  generated-or-typed initial password (min 8).
- Reset/create passwords are revealed exactly once in a copy-now
  modal; never logged, never re-fetchable.

**Theme system**
- Light/dark themes via `data-theme` on `:root` with a pre-paint
  inline script in `index.html`: explicit choice (localStorage) wins;
  first visit follows the OS `prefers-color-scheme`; dark default.
  No flash of wrong theme on load.
- Sun/moon toggle in the top bar; choice is sticky across sessions.
- New tokens: `--accent-soft`, `--info`, `--overlay`; badge tints are
  token-derived (`color-mix`) so both themes stay in palette.

**Accent dispersion + stat semantics**
- Accent carries identity and state only: nav active link, card title
  bar, sorted-column indicator, active filter chips, admin/role
  badges. Buttons stay jade-filled; a `ghost` variant added for
  tertiary actions.
- `Stat` gains `ok`/`warn`/`bad` tones; Dashboard (unlinked/privileged
  pending = warn, active campaigns = ok) and Risk (critical = bad,
  high = warn, low = ok) now color by meaning.
- `Badge` gains `info` (source type, SCIM status) and `accent`
  (system_admin) tones.

### Changed
- `scripts/contrast_check.py` now validates the light palette with the
  same bar as dark (AA text, AAA text/muted on panels, badge-on-tint
  AA) and exits nonzero on failure. Light palette tuned to pass:
  muted `#47525f`, accent `#1b7450`, ok `#277044`, warn `#825d14`,
  info `#28659a`.
- Version markers unified at 0.3.0 (`pyproject.toml`,
  `package.json`, FastAPI app + `/api/health`; the latter two were a
  stale 0.1.0).

## [0.2.0] - 2026-08-24

UI Polish Pass 2: shared UI primitives, per-view conversions, and a jade
theme retune. Backend additions: SoD manual evaluation.

### Added

**Shared UI primitives**
- `Modal` component (Esc/backdrop close, focus trap with restore, wide
  variant) replacing all hand-rolled overlays (API key reveal, SCIM token
  reveal, review revocation).
- `Typeahead` debounced autocomplete (keyboard nav, `value` field for
  submit values distinct from display label).
- `DataTable` primitive: per-column text/select filters, header sort,
  global search with autocomplete chips, column show/hide + native
  drag-to-reorder in a Columns popover (pinned `id`/`name` excluded),
  sticky header + sticky first columns, per-view column prefs persisted
  to localStorage.

**Sources**
- Create-source modal with owner `Typeahead` over real identities
  (`GET /api/identities?q=`); unmatched owner text blocks submit with an
  inline error instead of silently passing an unknown ID to the API.

**Campaigns**
- Create-campaign modal (name, mode, description, deadline).

**SoD**
- Manual rule evaluation: `POST /api/sod/rules/{id}/run` evaluates a rule
  live across all identities, persists a `sod_evaluations` row with
  violations as JSON evidence (hash-chained audit entry, same discipline
  as every state change), and returns the violation list. Rules list now
  surfaces last-run (violations count + timestamp).
- SoD view: create-rule modal with debounced entitlement filtering; Run
  button per rule with a violations result modal (identity, entitlement
  pair, severity).

**Identities**
- Converted to `DataTable` (filters, sort, search chips) with active
  status and source columns; CSV export retained.

### Changed

**Theme**
- Accent retuned steel blue → jade (`--accent: #2fa87c` for text/links,
  new `--accent-strong: #17805c` fill ramp for buttons), all pairs
  WCAG-AA-validated against panel surfaces (white-on-fill 4.9, accent
  text 5.3–6.3, muted 8.0, text AAA 15.3).
- Buttons restyled as solid fills with distinct borders, hover/active
  states, and focus-visible rings (previously bare text-link pills).
- Table grid lines: visible column separators + row borders
  (`--border` bumped to `#3a4450`), so tables read as grids.
- Contrast bump: `--text` → `#eef1f5`, `--muted` → `#a8b1bd` (AAA on
  panels); badge tones unchanged.

## [0.1.0] - 2026-08-23

First release: complete clean-room rebuild of the IAG governance tool,
feature-complete against [REQUIREMENTS.md](REQUIREMENTS.md).

### Added

**Core governance**
- Identity model with canonical employee_id key, manager hierarchy
  (cycle-rejected), and role-based access: system_admin,
  certification_admin, reviewer, auditor, report_viewer.
- Data sources with CSV upload ingestion; entitlement catalog with stable
  natural keys (re-imports refresh, never duplicate) and privilege
  classification.
- Certification campaigns: draft → staged → active → completed/cancelled
  lifecycle, JSON scope filters (source, department, privilege,
  unlinked-only), reviewer resolution (source-owner or manager mode with
  fallback), single + bulk decisions, mandatory revoke comments,
  auto-completion at 100% decided, campaign reports with CSV export.
- Segregation-of-duties rules with read-side violation detection,
  surfaced in campaign previews and review details.
- Append-only, hash-chained audit trail written transactionally with
  every state change; chain-verification endpoint and a pull-only JSONL
  SIEM feed.
- Session auth with lockout, plus API keys for programmatic access.

**Live connectors (feature 2)**
- LDAP/AD, Microsoft Entra ID, SQL, and CSV-on-URL adapters with a
  fork-A sync worker (SKIP LOCKED claim, delivery outside transaction,
  stuck-run reclaim); upsert-only semantics — missing rows counted,
  never deleted.
- Live bind validation from the admin UI before saving connector
  credentials (secret stored write-only, non-secret config echoed back).

**Remediation & enforcement (features 3 + 6)**
- Decision-triggered remediation rules (AND filters, regex entitlement
  match, catch-all), high-privilege approval gate, action queue with
  retry/requeue/dead-letter and full snapshots.
- Deliverers: owner-notification email and webhook out of the box.
- Enforcement write-back arms — LDAP member removal, Entra group writes,
  SQL statements — all idempotent (clean state completes without
  writing), with per-adapter behavior documented in the admin guide.
- SCIM 2.0 provisioning router (token auth) plus identity lifecycle
  management UI (create/activate/deactivate into a SCIM target).

**Risk, reports, SIEM (feature 5)**
- Seven-signal risk engine (unreviewed-access age, privilege weighting,
  orphans, more), risk router, per-identity and campaign reports.
- SIEM pull-only feed serving audit entries as paginated JSONL.

**Email (feature 1)**
- Review reminder queue per reviewer with due dates, adaptive SMTP
  delivery (STARTTLS when offered, AUTH when offered, loud plaintext
  fallback), retry → dead-letter, cancellation-aware claims.
- Code-stored Jinja2 templates rendered at enqueue (template failure is
  a 400 at campaign start, never a silently dead email).

**UI polish from live browser testing (T3)**
- Connector config prefill from echoed storage; in-app revoke-comment
  modal; campaign scope editor (sources, departments, privileged-only,
  unlinked-only); remediation rule source filter.

**Operations**
- Docker Compose stack: nginx LB → 3 stateless FastAPI replicas →
  PostgreSQL 16, one-shot Alembic migrate container as the only schema
  authority, least-privilege DB roles, baked SPA bundle.
- `.env`-driven configuration for every knob (SMTP, worker cadences,
  session timeouts, risk window, CORS), documented in `.env.example`.
- `scripts/smoke.sh` fault-tolerance proof: kills a replica mid-service,
  expects uninterrupted service and a valid audit chain.
- Optional `connectors` compose profile with glauth (read-only LDAP) and
  OpenLDAP (writable) proof directories.

### Fixed

Live-container proofs caught three defects mocks could not (feature 6,
phase E):

- LDAP reachability probe treated `sizeLimitExceeded` (result 4) as
  failure — real directories return it for the size_limit=1 probe while
  remaining perfectly reachable.
- LDAP sync requested `attributes=['*']`, which never returns the
  operational `memberOf` attribute — entitlement mirroring would have
  silently produced zero rows against real directories.
- Audit chain forked under concurrent replicas: `SELECT ... FOR UPDATE`
  cannot serialize the head lookup under READ COMMITTED; replaced with a
  Postgres advisory transaction lock taken before the head read.
