# IAG — Identity & Access Governance

A self-hosted identity and access governance application: ingest identities and
their access from external sources, normalize it into an entitlement catalog,
run certification campaigns over it, and keep a tamper-evident audit trail.

This is a clean-room v2 rebuild. The domain rules, invariants, and architecture
are frozen in [REQUIREMENTS.md](REQUIREMENTS.md) and
[ARCHITECTURE.md](ARCHITECTURE.md) — read those for the contracts, this file
for getting running.

## What it does

- **Identity ingestion** — CSV uploads and live connectors (LDAP/AD, Microsoft
  Entra ID, SQL, CSV-on-URL) normalize accounts and access into a stable
  entitlement catalog. Re-syncs refresh; they never duplicate.
- **Certification campaigns** — scope by source, department, privilege, or
  orphaned accounts; reviewers resolve each access review to approve or revoke;
  campaigns auto-complete at 100% decided.
- **Segregation of duties** — rule-based toxic-combination detection surfaced
  in campaign previews and review details.
- **Remediation & enforcement** — decision-triggered rules that notify owners
  by email, call webhooks, or write access changes back to the source
  (LDAP member removal, Entra group writes, SQL statements).
- **SCIM provisioning** — create/activate/deactivate identities into a SCIM
  target from the admin UI.
- **Risk scoring** — unreviewed-access age and privilege-weighted risk per
  identity, with reports.
- **Email** — review reminder queue with retry/dead-letter, adaptive SMTP
  (STARTTLS when offered, AUTH when offered).
- **Audit trail** — append-only, hash-chained audit entries written in the
  same transaction as every state change, with a chain-verification endpoint
  and a pull-only JSONL SIEM feed.
- **API keys** — token auth for programmatic access alongside session login.

## Quickstart (Docker)

Requirements: Docker (Docker Desktop or Engine with Compose v2). That's it —
the image builds the frontend and backend for you.

```bash
# 1. Generate local secrets (writes .env, refuses to overwrite an existing one)
python scripts/gen_env.py

# 2. Build and start
docker compose up -d --build

# 3. Log in at http://localhost:8090
#    user: admin    password: value of IAG_BOOTSTRAP_ADMIN_PASSWORD in .env
```

First boot runs migrations and creates the admin user, then nginx serves the
UI. The stack is: nginx (LB) → 3 stateless FastAPI replicas → PostgreSQL 16,
with a one-shot migrate container as the only schema authority.

Optional live directory sources for testing connectors:

```bash
docker compose --profile connectors up -d   # glauth (read-only) + openldap (writable)
```

## Configuration

All configuration is environment-based. Copy [.env.example](.env.example) or
use `gen_env.py`; every knob is documented there (SMTP, worker cadences,
session timeouts, risk windows, CORS). Compose forwards them all — a value set
in `.env` reaches the containers.

## Development without Docker

Backend (Python 3.12, [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync
# tests run on SQLite, no database container needed
IAG_ENV=test IAG_SECRET_KEY=test-secret-key-0123456789abcdef0123456789abcdef \
  uv run pytest tests/ -q
```

Frontend (React 18 + TypeScript + Vite):

```bash
cd frontend
npm ci
npm run dev
```

## Fault-tolerance smoke test

```bash
bash scripts/smoke.sh
```

Kills one app replica mid-service and expects continued service through nginx
plus a still-valid audit chain (architecture contract #6 — fault tolerance is
tested, not assumed).

## Roles

| Role | Can do |
|---|---|
| system_admin | Everything: users, settings, sources, campaigns, audit |
| certification_admin | Identities, sources, entitlements, campaigns; view audit |
| reviewer | Assigned reviews, decisions, own profile |
| auditor | Read-only: campaigns, reviews, audit logs, reports |
| report_viewer | Read-only dashboards and campaign reports |

## Documentation

- [REQUIREMENTS.md](REQUIREMENTS.md) — domain rules, roles, invariants
- [ARCHITECTURE.md](ARCHITECTURE.md) — stack, topology, resilience contract
- [docs/admin-guide.md](docs/admin-guide.md) — SCIM provisioning, enforcement
  rules, troubleshooting
- [SPECS/](SPECS/) — per-feature design specs (connectors, remediation,
  API keys, risk/reports/SIEM, SCIM/enforcement)

## Status

v0.3.0. Feature-complete first release: all core domains implemented,
backend suite green (pytest on SQLite), fault-tolerance and live-connector
proofs run against real containers (LDAP bind, sync, enforcement write-back,
SMTP delivery, SIEM feed). v0.3.0 adds in-app user administration
(system_admin) and a validated light/dark theme system.
