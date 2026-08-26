# IAG Administrator Guide — v0.3.0 (Validated Current State)

> **About this document.** This guide documents the *current state* of IAG as
> actually verified — not as designed. Every screenshot is a real capture from
> the running application, and every claim marked **[V]** was validated live in
> the session dated 2026-08-26. The validation evidence is summarized in
> [Appendix A](#appendix-a--validation-evidence-2026-08-26).

---

## Table of Contents

1. [What IAG does](#1-what-iag-does)
2. [Architecture at a glance](#2-architecture-at-a-glance)
3. [Getting started](#3-getting-started)
4. [The admin interface — view by view](#4-the-admin-interface--view-by-view)
   - 4.1 [Dashboard](#41-dashboard)
   - 4.2 [Identities](#42-identities)
   - 4.3 [Sources](#43-sources)
   - 4.4 [Entitlements](#44-entitlements)
   - 4.5 [Campaigns](#45-campaigns) (list, detail, report)
   - 4.6 [Risk](#46-risk)
   - 4.7 [SoD Rules](#47-sod-rules)
   - 4.8 [Remediation](#48-remediation) (incl. SCIM provisioning)
   - 4.9 [API Keys](#49-api-keys)
   - 4.10 [Users](#410-users)
   - 4.11 [Reminders (outbox)](#411-reminders-outbox)
   - 4.12 [Reviews](#412-reviews)
   - 4.13 [Audit](#413-audit)
   - 4.14 [Theming](#414-theming)
5. [Roles and permissions](#5-roles-and-permissions)
6. [Connectors and sync](#6-connectors-and-sync)
7. [SCIM provisioning and enforcement](#7-scim-provisioning-and-enforcement)
8. [Operational runbook](#8-operational-runbook)
9. [Troubleshooting](#9-troubleshooting)
10. [Appendix A — Validation evidence (2026-08-26)](#appendix-a--validation-evidence-2026-08-26)
11. [Where to read more](#11-where-to-read-more)

---

## 1. What IAG does

IAG (Identity & Access Governance) is a self-hosted application that:

- **Ingests identities and access** from CSV uploads or live connectors
  (LDAP/AD, Microsoft Entra ID, SQL, CSV-on-URL) into a stable entitlement
  catalog. Re-syncs refresh; they never duplicate.
- **Runs certification campaigns** scoped by source, department, privilege, or
  orphaned accounts. Reviewers approve or revoke; campaigns auto-complete at
  100% decided.
- **Detects toxic combinations** (segregation of duties) in campaign previews
  and review details.
- **Remediates and enforces** — decision-triggered rules notify owners by
  email, call webhooks, or write access changes back to the source (LDAP
  member removal, Entra group writes, SQL statements).
- **Provisions via SCIM 2.0** into a SCIM target, managed from the admin UI.
- **Scores risk** from unreviewed-access age and privilege weighting.
- **Keeps a tamper-evident audit trail** — append-only, hash-chained, written
  in the same transaction as every state change, with a chain-verification
  endpoint and a pull-only JSONL SIEM feed.
- **Issues API keys** (bearer-token, role-scoped) alongside session login.

## 2. Architecture at a glance

```
Browser -> nginx (LB; no DB creds, no writes)
         -> iag-app-1..3 (stateless FastAPI + SPA)
         -> iag-db (PostgreSQL 16; the single source of truth)
         -> iag-migrate (one-shot Alembic at boot; the only schema authority)
```

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI (Python 3.12), Pydantic v2 | contract-first schemas |
| ORM / migrations | SQLAlchemy 2.x typed / Alembic | relational integrity, single schema authority |
| DB | PostgreSQL 16 | one writer of truth |
| Frontend | React 18 + TypeScript + Vite | typed contract mirroring Pydantic |
| Proxy | nginx | stateless LB across 3 replicas |
| Tests | pytest + httpx (SQLite) | no Docker needed for the suite |

**The resilience contract [V]:** Postgres is the only durable state; replicas
are stateless (signed JWT sessions — any replica validates any session); only
the migrate container touches schema; if all replicas are down, nginx returns
502 and nothing writes; the audit chain is append-only and hash-chained; and
fault tolerance is *tested, not assumed* — `scripts/smoke.sh` kills a replica
mid-service and expects continued service plus a still-valid chain. This was
re-verified live (see Appendix A).

Optional `connectors` compose profile adds `glauth` (read-only LDAP for sync
proofs) and `openldap` (writable LDAP for enforcement write-back proofs).

## 3. Getting started

**Requirements:** Docker (Engine/Desktop with Compose v2) and Python for the
secret generator. Nothing else — the image builds frontend and backend.

```bash
python scripts/gen_env.py            # writes .env (4 secrets); refuses to overwrite
docker compose up -d --build         # build + start; first boot runs migrations
# log in at http://localhost:8090 — user: admin
# password: IAG_BOOTSTRAP_ADMIN_PASSWORD from .env
```

First boot: the migrate container applies Alembic migrations, then
`app.bootstrap` creates the admin identity (`employee_id E-ADMIN`) and its
system_admin login. Subsequent boots skip bootstrap ("N users exist;
skipping") **[V]**.

![Login screen](screenshots/01-login.png)

**Running a second (isolated) stack.** Compose hard-codes the project name,
container names, and port 8090, so a clone cannot simply `up` beside the
original — it would adopt/recreate the live project. Use the tested overlay
(see [Runbook §8.4](#84-running-an-isolated-clone)) to run as project
`iag-test`, containers `iag-test-*`, on port **8091** with its own volumes
and network. The original stack keeps running untouched **[V]**.

## 4. The admin interface — view by view

All screenshots below are live captures from v0.3.0 with real proof data
loaded (identities, sources, connectors, campaigns, remediation actions,
e-mails, audit history). Navigation is the header bar; the theme toggle sits
at its right end.

### 4.1 Dashboard

Portfolio counters and your personal workload at a glance.

![Dashboard](screenshots/02-dashboard.png)

Current validated instance: **10 identities · 24 accounts · 11 unlinked · 11
privileged · 8 active campaigns · 31 pending reviews** **[V]**.

### 4.2 Identities

The people directory: employee IDs, usernames, e-mail, department, manager,
active flag. Create/update via modals; CSV import upserts; CSV export
streams. A manager-cycle guard rejects circular reporting lines.

![Identities](screenshots/03-identities.png)

### 4.3 Sources

Data sources (CSV upload, LDAP, Entra ID, SQL, CSV-on-URL) and their
accounts. Create-source is a modal with owner autocomplete (typeahead over
real identities — the owner field takes an **employee ID**). Connector
configuration, manual **Sync now**, sync history, and account linking
(single or bulk by username/e-mail) all live here.

![Sources](screenshots/04-sources.png)

> **Note:** connector sync creates accounts and the entitlement catalog, and
> deliberately leaves `account.entitlement_id` / `account.identity_id` NULL —
> linking access to identities is a separate, explicit step (bulk-link or
> CSV import). This is by design; the "Unlinked accounts" counter surfaces
> the work remaining. **[V]**

### 4.4 Entitlements

The normalized access catalog with privilege levels. Stats header; privilege
changes are audited.

![Entitlements](screenshots/05-entitlements.png)

### 4.5 Campaigns

Certification campaigns: scope by source/department/privilege/orphans,
**Preview** (dry-run reviewer resolution — see exactly which reviews a start
would create and why any are skipped), then **Stage → Start**. Starting
regenerates reviews and enqueues reminder e-mails. Campaigns auto-complete at
100% decided.

![Campaigns](screenshots/06-campaigns.png)

Campaign **detail** shows metrics, the review queue and per-review decisions:

![Campaign detail](screenshots/15-campaign-detail.png)

Campaign **report** (report_viewer and up) renders the decision record with
identities, entitlements, risk bands and reviewer attribution, with a CSV
export:

![Campaign report](screenshots/16-campaign-report.png)

### 4.6 Risk

Unreviewed-access age × privilege-weighted risk per identity, with reports.
Risk windows are configured via `IAG_RISK_UNREVIEWED_DAYS`.

![Risk](screenshots/07-risk.png)

### 4.7 SoD Rules

Segregation-of-duties rules: toxic entitlement combinations. Violations
surface in campaign previews and review details (flagged rows), so reviewers
see the risk before deciding.

![SoD rules](screenshots/08-sod.png)

### 4.8 Remediation

Decision-triggered rules with four action types — `notify_owner` e-mail,
`webhook`, and `enforce` (directory write-back: LDAP member removal / Entra
group writes / SQL statements). Rules filter by privilege level and
entitlement pattern; approval gating is per-rule (on by default — leave it on
until you trust a rule). The action queue shows each action's lifecycle
(pending_approval → completed/failed) with approve/cancel/retry.

The **SCIM provisioning** card also lives here — see
[§7](#7-scim-provisioning-and-enforcement).

![Remediation](screenshots/09-remediation.png)

Validated behavior **[V]**: a low-privilege notify e-mail fired without
approval; high/very-high actions queued as `pending_approval`; a webhook rule
delivered to a live sink; every state change appended to the audit chain.

### 4.9 API Keys

Bearer-token machine access. Keys are shown once at creation (only a hash is
stored); role-scoped; read-only chokes apply per role; revocation is
immediate and audited. `keys-manage-keys` is blocked (a key cannot manage
keys).

![API keys](screenshots/10-api-keys.png)

### 4.10 Users

In-app user administration (system_admin): create users against identities,
assign roles, activate/deactivate, trigger password resets. Login lockout
after `IAG_MAX_LOGIN_ATTEMPTS` failed attempts for
`IAG_LOCKOUT_DURATION_MINUTES`.

![Users](screenshots/11-users.png)

### 4.11 Reminders (outbox)

The review-reminder e-mail queue with retry/dead-letter. Reminder cadence and
stuck-row reclaim are env-tunable; delivery is adaptive SMTP (STARTTLS when
offered, AUTH when offered) or log-only dev delivery when no SMTP host is
set.

![Reminders outbox](screenshots/12-reminders-outbox.png)

### 4.12 Reviews

The reviewer's queue: approve/revoke per review (revocation requires a
comment), bulk decisions, and history. Campaigns auto-complete on the last
decision.

![Reviews](screenshots/13-reviews.png)

### 4.13 Audit

The append-only, hash-chained audit log: paginated, filterable, CSV-export,
and a live **chain verification** badge. `record_hash = SHA256(prev_hash +
canonical_json(entry))`; the verify endpoint walks the full chain — it read
**Valid · 177 entries** on the validated instance **[V]**. SIEM consumers
pull the JSONL feed (`/api/audit/feed`) with `Last-Id` pagination and the
advertised chain head.

![Audit](screenshots/14-audit.png)

### 4.14 Theming

Light/dark themes via the header toggle (`button.theme-toggle`); the choice
persists. Both were walked live **[V]**.

![Dark theme](screenshots/17-theme-dark.png)

## 5. Roles and permissions

| Role | Can do |
|---|---|
| system_admin | Everything: users, settings, sources, campaigns, audit |
| certification_admin | Identities, sources, entitlements, campaigns; view audit |
| reviewer | Assigned reviews, decisions, own profile |
| auditor | Read-only: campaigns, reviews, audit logs, reports |
| report_viewer | Read-only dashboards and campaign reports |

Sessions are signed stateless JWTs (httpOnly cookie); API keys present a
Bearer principal with the same role chokes.

## 6. Connectors and sync

- **CSV upload** — natural-key entitlement upsert; simplest path to a
  populated catalog.
- **LDAP/AD** — bind + search validated live at config save (PUT runs a real
  probe); sync normalizes posixAccount users and groups.
- **Entra ID** — group writes for enforcement; no local tenant is required
  for sync-only use.
- **SQL** — admin-supplied query; validation runs `LIMIT 1` for real; secrets
  are stored separately from the URL (`$SECRET` placeholder).
- **CSV-on-URL** — scheduled re-pull.

Sync workers run inside app replicas (never a separate writer) on
`IAG_CONNECTOR_POLL_SECONDS`; stuck runs are reclaimed after
`IAG_CONNECTOR_STUCK_MINUTES`. Manual sync is available per source
(**Sync now**).

## 7. SCIM provisioning and enforcement

*(Condensed from the original SCIM guide — see git history for the long form
and `SPECS/feature-6-scim-provisioning-enforcement.md` for design.)*

**Provisioning** — off until enabled + token generated (endpoints answer 503
until then; audits record nothing). Point your IdP at
`/api/scim/v2/Users` with `Authorization: Bearer <token>`. Supported:
create/list(+filters)/PATCH(incl. `active`)/DELETE per RFC 7644. The IdP's
`externalId` is the join key — pick a stable one (UPN/employee number), or
records split. The token shows once; rotation revokes instantly.

**Enforcement rules** — action `enforce` with target `remove_entitlement`
(entitlement name must match the directory group name) or `disable_account`.
Approval on by default. CSV/spreadsheet sources have no write-back — their
actions fail loudly and requeue, never silently skip. After an approved
action completes, **Sync now** closes the drift window. Already-clean
directories complete as `already clean` without writing.

## 8. Operational runbook

### 8.1 Health & chain checks

```bash
curl -fsS http://localhost:8090/api/health        # {"status":"ok",...}
# login (cookie jar) then:
curl -fsS -b jar.txt http://localhost:8090/api/audit/verify
#   -> {"valid":true,"entries":N,"head":"<sha256>"}
```

### 8.2 Backend test suite

```bash
cd backend && uv sync
IAG_ENV=test IAG_SECRET_KEY=test-secret-key-0123456789abcdef0123456789abcdef \
  uv run pytest tests/ -q        # 290 tests, SQLite, no Docker needed [V]
```

### 8.3 Fault-tolerance smoke

`bash scripts/smoke.sh` — kills `iag-app-2`, expects service + chain to hold,
restarts and waits for healthy. For an isolated (renamed) stack use
`scripts/smoke.test.sh` with `BASE_URL`/`IAG_APP2_CONTAINER` exported.

### 8.4 Running an isolated clone (validated workflow)

```yaml
# compose.test.yaml (in the clone)
name: iag-test
services:
  iag-db:      { container_name: iag-test-db }
  iag-migrate: { container_name: iag-test-migrate }
  iag-app-1:   { container_name: iag-test-app-1, environment: { IAG_APP_BASE_URL: http://localhost:8091 } }
  # ... app-2, app-3, glauth, openldap similarly ...
  iag-nginx:   { container_name: iag-test-nginx, ports: !override ["8091:80"] }
```

```bash
python scripts/gen_env.py
docker compose -f compose.yaml -f compose.test.yaml --profile connectors up -d --build
# stack is now on http://localhost:8091; original on 8090 untouched
```

### 8.5 Live-proof battery

All proofs honor env overrides. The full set (13 scripts) with isolation:

```bash
export IAG_BASE_URL=http://localhost:8091 IAG_BASE=http://localhost:8091
export IAG_DB_CONTAINER=iag-test-db IAG_APP_CONTAINER=iag-test-app-1
export IAG_OPENLDAP_CONTAINER=iag-test-openldap IAG_GLAUTH_CONTAINER=iag-test-glauth
export IAG_APP_DB_PASSWORD=... IAG_BOOTSTRAP_ADMIN_PASSWORD=...   # from .env
export SINK_LOG=$PWD/smtp_sink_log.jsonl                           # for the smtp proof
uv run --no-project --with aiosmtpd python scripts/smtp_sink.py smtp_sink_log.jsonl 1025 &
```

**Ordering rules (validated):** `reminder` first (expects a solo campaign);
`risk → report → siem` in that order (siem needs ≥50 accumulated audit
entries, so run it late); `enforce`/`remediation` late; `smtp` last (its
campaign pollutes outbox counts). `report` and `remediation` are
order-sensitive — on a shared DB they may need solo runs on a fresh volume.
`live_remediation_check` additionally requires SMTP env (`SINK_LOG`) and, on
fresh databases, performs its own entitlement/identity binds (added 2026-08-26).

### 8.6 Reset to factory

```bash
docker compose down -v     # removes containers AND volumes (fresh DB, fresh bootstrap)
```

## 9. Troubleshooting

**All replicas crash-loop at boot: `IAG_SMTP_HOST set but missing:
IAG_SMTP_USER, IAG_SMTP_PASSWORD`** — fail-fast settings validation. Setting
*any* SMTP host requires user+password, even for a local sink that offers no
AUTH. Set both (dummy values are fine for a no-AUTH sink) and recreate.
Consider upstream: warn instead of crash, or document on the knob. **[V]**

**Compose from a clone touched the wrong stack** — the compose file pins
project name `iag`, container names, and port 8090. Without the overlay
(§8.4), `docker compose up` in a clone adopts the *live* project. Always use
`-f compose.yaml -f compose.test.yaml` in clones.

**`bash scripts/...` behaves oddly / env vars missing on Windows** — the
available `bash` may be WSL, which does not inherit arbitrary Windows env
vars (only `WSLENV`-listed ones) and uses `/mnt/d/...` paths. Export inside
bash: `bash -c "export BASE_URL=...; cd /mnt/d/iag-test && bash scripts/smoke.test.sh"`.

**`.env` sourcing fails under bash (`$'\r': command not found`)** — CRLF
line endings. Normalize: `(Get-Content .env -Raw) -replace "\`r\`n","\`n" | Set-Content -NoNewline .env`.

**Live proof "no reviews created"** — campaign review generation skips
accounts with `identity_id IS NULL` (and source_owner mode needs a source
owner resolvable to a login). Link synced accounts (bulk-link) before
campaigning. **[V]**

**`live_remediation_check` failing on fresh DBs** — historical drift: the
script posted `owner_identity_id` where the API takes `owner_employee_id`
(silently dropped by Pydantic), and predated the sync-leaves-links-NULL
design. Fixed in the validation branch (contract fix + house-style binds).

**`iag-openldap` exited(1)** — the optional writable-LDAP proof container
(from the `connectors` profile). Not part of the default stack; restart with
`--profile connectors up -d` if running enforcement proofs.

**SIEM walker sees fewer entries than expected** — entries accumulate with
every proof; the check requires ≥50. Run it after other proofs (§8.5).

**Blank screenshots via browserbase-local (Stagehand)** — the local
Stagehand screenshot path produced byte-identical blank frames (4 KB) while
the DOM was live. The Playwright browser stack captured correctly; fall back
to it for headless capture. **[V]**

## 10. Appendix A — Validation evidence (2026-08-26)

Environment: isolated clone `D:\iag-test` (branch `validation/test-isolation`,
commit `c398464` + this guide), stack `iag-test` on port 8091, original
production stack untouched throughout.

| Check | Result |
|---|---|
| Backend suite (pytest, SQLite) | **290/290 passed** |
| Stack boot | migrate → bootstrap → 3×app healthy → nginx 8091 |
| Live proofs | **13/13 PASS** (11/13 in single-battery order; `report`+`remediation` pass solo on fresh volumes — ordering documented §8.5) |
| Fault-tolerance smoke | **PASS** — replica killed, nginx served, chain valid, replica rejoined |
| UI walkthrough (real browser) | login + all 13 views + campaign detail/report + dark theme — all render with live data |
| Audit chain | `{"valid":true,"entries":177,"head":"3310dd78…"}` |
| Health | `{"status":"ok","service":"iag-api","version":"0.3.0"}` |
| Dashboard counters | 10 identities · 24 accounts · 11 unlinked · 11 privileged · 8 active campaigns · 31 pending reviews |
| Campaigns | 10 total: 8 active, 1 completed, 1 cancelled |
| API keys / users | 3 keys (audit-evidence rows retained by design) / 1 user |

Fixes contributed during validation (cherry-pickable): env-overridable
container names in six live scripts; `live_remediation_check` contract fix +
binds; `smoke.test.sh`; this guide.

## 11. Where to read more

- `README.md` — getting running
- `REQUIREMENTS.md` — domain rules, roles, invariants (the contract)
- `ARCHITECTURE.md` — stack, topology, resilience contract
- `SPECS/` — per-feature design specs (connectors, remediation, API keys,
  risk/reports/SIEM, SCIM/enforcement, RBAC/themes)
- `docs/polish-pass-2.md` — UI component and theming decisions
- `CHANGELOG.md` / `HANDOFF.md` — history and continuation notes
