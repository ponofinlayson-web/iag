# Changelog

All notable changes to IAG are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[SemVer](https://semver.org/).

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
