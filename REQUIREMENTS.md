# IAG ΓÇö Requirements (v2 rebuild)
Derived from a forensic read of the original IAM-Simplified project.
No code was carried over; only behavior, data semantics, and invariants.
## 1. Product statement
A self-hosted identity and access governance (IAG) application: ingest
identities and their access from external sources, normalize it into an
entitlement catalog, run certification campaigns over it, and keep a
tamper-evident audit trail.
## 2. Personas and roles
| Role | Can do |
|---|---|
| system_admin | Everything: users, settings, sources, campaigns, audit |
| certification_admin | Manage identities, sources, entitlements, campaigns; view audit |
| reviewer | See assigned reviews, submit decisions; own profile |
| auditor | Read-only: campaigns, reviews, audit logs, reports |
| report_viewer | Read-only dashboards and campaign reports |
Dropped from v1: the developer role (not a governance persona).
Every login account (User) is backed by exactly one Identity; not every
Identity is a User.
## 3. Core domain rules (invariants)
1. Canonical identity key. employee_id is unique and is the join key used by
   imports and links. Email and username are unique when present.
2. Manager hierarchy. An identity's manager is another identity (manager_id,
   SET NULL on delete). Cycles are rejected at write time.
3. Accounts. An Account belongs to exactly one DataSource and MAY link to an
   identity (unlinked = service/orphan account). Deleting a source deletes
   its accounts; deleting an identity orphans (not deletes) its accounts.
   One account carries one entitlement reference; a person's access
   footprint is the set of entitlements on their linked accounts.
4. Entitlement catalog. Each distinct access value in a source normalizes to
   one catalog row keyed by a stable natural key
   source_id|column|value_lowercase. Catalog IDs (ENT-00042) are assigned
   once, never reused. Re-imports match on natural key, refresh
   last_seen_at, never duplicate.
5. Privilege classification. An entitlement's privilege level is one of
   low, moderate, high, very_high. Null means "not yet classified".
6. Campaign lifecycle. draft -> staged -> active -> completed | cancelled.
   Only draft/staged campaigns may be edited. start generates one Review
   per in-scope account; re-start clears and regenerates. A campaign
   completes when every review has a decision.
7. Campaign scope. JSON filters: data_source_ids, departments,
   privileged_only, unlinked_only. Empty scope = all active accounts.
8. Reviewer resolution. Mode source_owner: the User linked to the source's
   owner identity; accounts in a source with no owner User are skipped and
   reported. Mode manager: the User linked to the account identity's
   manager; a missing manager or non-User manager falls back to the
   campaign creator.
9. Reviews. One review per (campaign, account). Status
   pending -> in_progress -> approved | revoked. Revocation requires a
   comment. Bulk submit applies one decision to many pending reviews.
   Reviews cannot be submitted for a non-active campaign.
10. Audit trail. Every state-changing API action appends an audit record in
    the SAME database transaction as the change. Records are append-only
    and hash-chained (each entry hashes the previous entry's hash); an
    endpoint walks the chain and reports any tamper.
## 3a. v1 lessons applied (what we designed OUT)
- Monolith files (app.py/api.py at 5,300 lines each): routers are capped at
  one domain per file, hard rule.
- No migrations (create_all + in-place alters): Alembic from day one; the
  migrate container is the only schema authority.
- JSON columns that silently fail to persist (flag_modified gotcha): JSON
  fields are replaced whole-value on write, never mutated in place.
- Audit possibly decoupled from action: audit commits atomically with the
  change, enforced at the service layer.
- Secrets committed in .env: .env is gitignored; boot-time validation
  fails fast.
- Single server process, no fault tolerance: 3 stateless replicas behind
  nginx; killing any container leaves the service up.
- Global module-level config imported everywhere: typed Settings delivered
  by dependency injection.
## 4. Functional requirements (skeleton scope)
- Auth: login (username+password, bcrypt), JWT in httpOnly cookie, /auth/me,
  logout, change password. Per-user rate limiting and lockout.
- Identities: list/search/page, create, edit, delete, CSV import
  (employee_id, username, email, names, department, title,
  manager_employee_id), CSV export.
- Data sources: CRUD; CSV upload parses accounts + entitlements per column
  mapping. Connector types ldap/entra/sql are modeled, stubbed.
- Accounts: list per source, link/unlink, bulk link by username/email.
- Entitlements: catalog browser, privilege filter, set privilege, stats.
- Campaigns: CRUD, stage, start (with dry-run preview of scope and reviewer
  resolution BEFORE real start), metrics, cancel, complete.
- Reviews: my queue, detail, submit (approve/revoke + comment), bulk
  submit, history.
- Audit: filterable viewer, chain verification, CSV export.
- Dashboard: portfolio counts, active campaigns, my pending workload,
  privileged access summary.
Deferred from v1 (documented, not built): live connectors, email templates
and delivery, SoD engine, SCIM, remediation, SIEM, screen recording,
multi-tenancy, plugins, API keys, risk scoring, PDF reports.
## 5. Non-functional requirements
1. Resilience topology (explicit user requirement):
   - Exactly ONE database container (Postgres 16): the single source of
     truth. All writes go through the API replicas.
   - THREE stateless API/UI-service containers behind nginx; killing any
     one leaves the service up with zero data loss.
   - A one-shot migration container runs Alembic at boot; API replicas
     never touch the schema.
   - Invariant: if all API replicas are down, nothing writes. nginx and
     the browser hold no write path.
   - Invariant: container logs are NOT the audit-of-record. The
     hash-chained DB audit trail is.
2. Auditability under failure: the audit-of-record commits atomically with
   each change; container logs are structured JSON on stdout, rotated by
   the Docker json-file driver with bounded size.
3. Security: bcrypt hashing, signed JWTs in httpOnly cookies, security
   headers, per-user login rate limiting and lockout, role checks on every
   route, secrets via environment (validated at boot, fail-fast).
4. Portability: the ORM layer avoids DB-specific column types so unit
   tests run on SQLite while production runs Postgres.
5. Testability: the full test suite runs without Docker; a compose smoke
   test verifies the resilient topology end to end.
## 6. Out of scope for the skeleton
Live connectors, email delivery, PDF reports, SoD, SCIM, remediation, SIEM,
screen recording, multi-tenancy, horizontal DB scaling. Each has a reserved
design slot in ARCHITECTURE.md.
