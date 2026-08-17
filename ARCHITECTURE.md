# IAG ΓÇö Architecture (v2)
Clean-room rebuild. The stack is chosen for what the domain demands:
transactional audit integrity, a relational entitlement graph, and a
fault-tolerant deployment topology the user can actually run.
## Stack
| Layer | Choice | Why |
|---|---|---|
| API | FastAPI (Python 3.12), Pydantic v2 | contract-first schemas, DI |
| ORM | SQLAlchemy 2.x typed declarative | relational integrity |
| Migrations | Alembic | migrate container is the only schema authority |
| DB | PostgreSQL 16, single instance | one writer of truth |
| Frontend | React 18 + TypeScript + Vite | typed contract mirroring Pydantic |
| Proxy | nginx | stateless LB across 3 app replicas |
| Tests | pytest + httpx | runs on SQLite, no Docker needed |
## Container diagram
Browser -> nginx (LB, no DB creds, no writes)
         -> iag-app-1, iag-app-2, iag-app-3 (stateless FastAPI + SPA)
         -> iag-db (postgres:16, named volume, the single source of truth)
         -> iag-migrate (one-shot Alembic at boot, then exits)
## The resilience contract
1. Single writer of truth. Postgres is the only durable state. If the DB
   container dies, the app degrades to errors; data survives in the volume.
2. Stateless replicas. No local file storage on any app replica. Uploads
   land in the DB as bytes + metadata. Sessions are signed stateless JWTs,
   so any replica can validate any session. Kill any replica mid-request:
   worst case that request fails and is retried on a survivor; nothing is
   half-written thanks to transactional boundaries.
3. Migration authority. Only iag-migrate runs Alembic. App replicas wait
   for a healthy DB but never alter the schema.
4. Write-path invariant. If all three app replicas are down, nginx returns
   502 and nothing writes. No cron, no schedulers, no sidecars with write
   credentials. Future reminder emails must run inside an app replica as a
   task queue, never as a separate writer.
5. Audit-of-record. The audit_entries table is append-only and hash-chained:
   record_hash = SHA256(prev_hash + canonical_json(entry)). Container logs
   are telemetry, never evidence.
6. Fault tolerance is tested, not assumed: scripts/smoke.sh kills one
   replica and expects continued service.
## Runtime topology
| Container | Image | Role | DB creds | Writes |
|---|---|---|---|---|
| iag-db | postgres:16-alpine | source of truth | full | app data |
| iag-migrate | iag-app image | one-shot Alembic | full | schema only |
| iag-app-1..3 | iag-app image | API + SPA | app-role creds | app data |
| iag-nginx | nginx:alpine | TLS/LB | none | none |
## Module layout
backend/app/core/     settings, security, audit chain, logging
backend/app/models/   one file per aggregate
backend/app/schemas/  Pydantic request/response contracts
backend/app/routers/  one router per domain, hard 400-line cap
backend/alembic/      migrations
backend/tests/        pytest, SQLite-backed
frontend/             React+TS+Vite SPA, built to static files
scripts/smoke.sh      fault-tolerance smoke test
compose.yaml          authoritative container list
Dockerfile            multi-stage: node build then python runtime
## Request flow
1. Browser loads the SPA from nginx (static files served by nginx directly).
2. SPA calls /api/* same-origin through nginx to the app replicas.
3. POST /api/auth/login sets an httpOnly JWT cookie; all other API routes
   require a valid session plus role checks.
4. Write endpoints execute in one transaction: change + audit entry commit
   together or not at all.
5. Exports stream CSV straight from the DB.
## Design slots (future, contract-preserving)
- Live LDAP/Entra/SQL connectors: background sync tasks inside app replicas.
- Email: outbound only, via an in-app task queue. Never a writer.
- SoD engine: read-side computation; rule writes follow audit discipline.
- External anchoring of the audit chain (weekly digest to a tamper-
  resistant location).
- Read replicas: possible later, always read-only.
