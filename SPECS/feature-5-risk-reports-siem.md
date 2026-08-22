# Feature 5 - Risk scoring, PDF reports, SIEM feed

Status: RATIFIED (user: "Ratified", session 12, 2026-08-21 late). D1-D8
as drafted. Phases A-E unlocked; D1 SIEM pull-only is the locked
divergence from v1.
Fills three REQUIREMENTS.md 4 deferred-list entries ("risk scoring,
PDF reports, SIEM") in one feature because they share one surface:
they are the read-side outputs of the governance data features 1-4
assembled (identities, catalog, campaigns, audit). No ARCHITECTURE.md
design slot exists yet; one line is added at ratification (same
pattern as features 3-4): "Risk, reports, and SIEM feed: read-side
computation over governed data; SIEM is pull-only."

## Goal

Three outputs the data exists to produce:

1. A transparent risk score per identity (0-100, weighted signals,
   an auditor can see exactly why a score is what it is).
2. A printable executive report per campaign (print-optimized SPA
   view; the browser saves the PDF).
3. A machine-readable audit-event feed for SIEM ingestion (pull-only
   GET, API-key authenticated, chain hashes included).

## Clean-room divergence from v1 (behavioral, not code)

v1 shipped all three (`risk_service.py`, `siem_service.py`, the
tier5/tier6 report endpoints; read-only reference, no code copied).
Behaviors worth keeping are kept; deployment anti-patterns are
designed out:

- v1 risk: 7 signals, weights summing to 100, snapshot rows for
  trend. KEPT, adapted to the v2 schema (D3). v1's
  `compute_all_risks` committed per identity inside a bare
  try/except; v2 computes pure and persists one snapshot set per
  run in a single transaction. v1 snapshots had no run grouping, so
  trend queries interleaved rows from different runs; v2 snapshots
  carry a run_id.
- v1 SIEM: push forwarder - a threading.Thread, global mutable
  config, an in-memory queue that silently dropped events when
  full, provider-specific formatters. DROPPED entirely (D1). A push
  forwarder is a sidecar with credentials and delivery semantics to
  manage; the resilience contract's spirit forbids it, and v1's
  queue dropped events under load without a trace.
- v1 PDF: WeasyPrint first, then abandoned mid-project for
  print-optimized HTML + browser print-to-PDF (GTK unavailable on
  Windows). ADOPTED as the v2 starting point (D6): the SPA renders
  the report with print CSS; the user saves the PDF. No server-side
  rendering, no PDF library, no files on replicas.
- v1 report CSVs were written to server disk (UPLOADS_DIR) - a
  stateless-replica violation. v2 streams CSVs (house pattern,
  audit export).
- v1 dormant_access measured "not reviewed / used in 90 days" -
  but IAG has no usage telemetry, so v2 measures what actually
  exists: review-decision recency. Renamed unreviewed_access.

## Non-goals (v1 of this feature)

- Push SIEM forwarding of any kind (Splunk HEC, Sentinel DCR,
  syslog). Pull-only endpoints only.
- SIEM provider-specific formatters - the feed is plain JSONL rows
  of audit records. Any SIEM maps plain fields; none gets a bespoke
  envelope.
- Risk alerting/webhooks on thresholds, risk-driven campaigns, ML
  scoring, per-tenant configurable weights.
- Scheduled/automatic risk computation - an explicit admin POST
  triggers a run (no cron-shaped anything; D4).
- PDF output for anything except campaigns; emailing/scheduling
  reports.
- Browser PDF libraries (jsPDF etc.) - browser print-to-PDF only.
- Audit events for any read in this feature (reads never audit,
  house rule; SIEM pulls are themselves evidenced by the entries
  they fetch).

## Part 1 - Risk scoring

### Data model - migration 0007

New table `risk_snapshots`:

| column | type | notes |
|---|---|---|
| `id` | Integer PK | |
| `run_id` | String(36), indexed | uuid4 hex; groups one run's rows |
| `identity_id` | FK identities SET NULL, nullable | survives identity delete |
| `identity_employee_id` | String(100) | frozen key at score time |
| `score` | Float | 0-100, one decimal |
| `band` | String(10) | low / medium / high / critical (D3) |
| `signals` | Text (JSON) | {signal name: points earned} |
| `factors` | Text (JSON) | detail rows (below) |
| `computed_at` | DateTime | run timestamp, naive UTC |

Indexes: `(run_id)`, `(identity_id, computed_at)`. Rows are
permanent (trend evidence); no delete endpoint.

### Signals (definitions adapted to v2; weights D3)

A person's access footprint = entitlements on accounts linked to
the identity (REQUIREMENTS 3.3). Basis tables: Account, Entitlement,
Review, Identity, plus sod_engine (live, read-side).

| # | signal | weight | v2 definition |
|---|---|---|---|
| 1 | unreviewed_access | 20 | fraction of the identity's linked accounts with NO review decision (approved or revoked) on any campaign within RISK_UNREVIEWED_DAYS=90 days (Review.completed_at) |
| 2 | privileged_access | 20 | linked accounts with privilege high/very_high, very_high counted double; min(count/10, 1) x 20 |
| 3 | sod_violations | 20 | open SoD violations from sod_engine.violations_for_identities; min(n/3, 1) x 20 |
| 4 | privilege_creep | 10 | fraction of the identity's accounts created in the last 30 days |
| 5 | orphaned_access | 10 | identity holds accounts but has no manager |
| 6 | stale_identity | 10 | identity is_inactive while still holding accounts |
| 7 | source_concentration | 10 | max accounts on one data source; min(max/20, 1) x 10 |

Bands: critical >= 75, high >= 50, medium >= 25, low below (v1
thresholds kept). Score = sum of signal points, clamped 100.

Each factor row persisted in `factors`: {signal, weight, raw,
raw_total, contribution, detail} where detail is a human sentence
("4 of 7 accounts last decided 90+ days ago") - the transparency
requirement is the point of the feature.

Computation lives in `app/core/risk_engine.py` (sod_engine shape):
pure async functions over the session - `score_identities(db,
identity_ids)` batch-scores, no writes; the router persists. A
revoked-then-resurrected account counts as reviewed the day it was
decided; recency is what the signal measures, not correctness.

## Part 1 API (new router `routers/risk.py`, prefix `/api/risk`)

| method + path | guard | behavior |
|---|---|---|
| `POST /runs` | CertAdminUser | Score ALL active identities now. One run_id, one transaction: engine computes pure, router persists snapshot rows + audit `risk_run_completed` {run_id, scored, band_distribution}. 202 with summary {run_id, scored_identities, average_score, band_distribution}. |
| `GET /snapshots` | ReportViewer | Latest run only by default (D4): rows sorted score desc, paged. Query params: `run_id` (trend view of any run), `band`, `department` (join identities), `page`. |
| `GET /trend/{identity_id}` | ReportViewer | All snapshot rows for one identity across runs (score/band/signals/computed_at), oldest first. |
| `GET /summary` | ReportViewer | Portfolio summary of latest run: band_distribution, average_score, scored_identities, top 10 risky (name, score, band, top 3 factors), run timestamp. |

Guards: new alias `ReportViewer` = require_roles(REPORT_VIEWER,
AUDITOR, CERTIFICATION_ADMIN, SYSTEM_ADMIN) - reads are the point of
the report_viewer role (REQUIREMENTS 2); write trigger (runs) stays
CertAdminUser. API keys with auditor/report_viewer roles work on
all four GETs (feature-4 D1 pays off here).

Frontend: new "Risk" view (nav for the four read roles): summary
cards (bands, average, last run), top-10 table with factor drill-out,
full snapshot table (band chip, department filter), "Compute now"
button (cert_admin+), per-identity sparkline trend from /trend.
client.ts `risk` namespace. No print CSS here (not a PDF surface).

## Part 2 - Campaign report (print-to-PDF)

### Content (mined from v1's report, adapted to v2)

`GET /api/campaigns/{id}/report` (ReportViewer; same visibility as
metrics) returns a JSON report object; the SPA renders it at
`/campaigns/:id/report` with print CSS and a "Print / Save as PDF"
button (window.print()):

- Campaign header: name, description, status, review mode,
  deadline, created, generated_at.
- Completion block: totals + completion percentage.
- Decision breakdown: approved / revoked / pending / in_progress.
- Reviewer workload table: per reviewer - assigned, approved,
  revoked, pending (sorted pending desc - who is the bottleneck).
- Revocations detail: identity, entitlement, source, decided_at,
  reviewer, comment (comments are mandatory on revocation -
  REQUIREMENTS 3.9 - so this table is always meaningful).
- Risk block: if a risk run exists, band distribution of the
  campaign's reviewed identities (bridges Part 1 into the report;
  no run = block omitted).

Print CSS: A4-ish margins, table page-break rules, no nav chrome,
black-on-white. The report endpoint is a GET so an API-key pull
also works (tooling reuse).

CSV variant `GET /api/campaigns/{id}/report.csv`: decision rows
(identity, employee_id, source, entitlement, privilege, reviewer,
decision, decided_at, comment), streamed (house pattern),
ReportViewer guard.

## Part 3 - SIEM feed (pull-only)

### Why pull, not push (D1)

The SIEM owns the loop. IAG serves read-only pages of audit
entries; any scheduler/script (or a SIEM's native HTTP poller)
fetches them with an API key. Nothing runs inside IAG, nothing
holds SIEM credentials, no queue, no delivery retries, no drops -
the failure mode of a push forwarder is a stuck thread; the
failure mode of pull is "the poller asks again". At-least-once
delivery is trivially the SIEM's own retry policy.

### API (extends `routers/audit.py`)

| method + path | guard | behavior |
|---|---|---|
| `GET /api/audit/feed` | AuditViewer | JSONL: one audit entry per line, `after_id` cursor param (default 0 = from genesis), `limit` (default 500, max 5000). Response headers: `X-IAG-Last-Id`, `X-IAG-Head` (record_hash of newest entry served). Rows: id, ts, actor_id, actor_username, action, entity_type, entity_id, details, prev_hash, record_hash. |
| `GET /api/audit/feed/stats` | AuditViewer | {total_entries, last_id, last_ts, chain_head, chain_valid} - lets a poller detect gaps/tampering before pulling. |

Pagination contract: rows ordered by id ASC; next request sets
`after_id` = last row's id received. Chain hashes in each row let
the SIEM verify integrity independently (recompute SHA256(prev_hash
+ canonical_json) walking the feed) - the audit chain becomes
transportable evidence, not just an internal check.

JSONL not a JSON array: the SIEM consumes line-by-line at any
size; a 100k-entry array would need full buffering.

Feature-4 D7 note: if SIEM polling ever needs rate limits, they
land at nginx FIRST (per feature-4's deferred decision) - not in
this feature.

### OpenAPI

The feed endpoints ride the existing bearerAuth scheme (feature-4
C). Docs show the cursor pattern via a parameter example.

## Tests (pytest, SQLite, real code paths)

Risk engine (pure, unit):
- Each signal scores as defined against hand-built fixtures
  (dormant accounts, privileged counts, SoD violations, creep,
  orphan, stale, concentration) - exact expected points.
- Weights sum to 100; score clamps at 100; bands at 25/50/75.
- Empty portfolio (no identities) -> zero scores, clean summary.

Risk API (integration):
- POST /runs scores all active identities, one run_id, snapshot
  rows persisted, audit risk_run_completed chained.
- GET /snapshots latest-run default; run_id param reaches older
  runs; band/department filters; paging.
- GET /trend returns rows across runs oldest-first.
- GET /summary shape: bands, average, top-10 with factors.
- Guards: reviewer 403 on /runs; report_viewer 200 on GETs;
  auditor API key 200 on GETs (feature-4 principal).
- Inactive identities excluded from runs and snapshots.

Campaign report:
- Report JSON shape on a fixture campaign with mixed decisions.
- Report guard: reviewer 403, report_viewer 200 (metrics-visible
  campaigns only).
- report.csv streams decision rows, correct headers, mandatory
  comments present.
- Completed campaign auto-complete block present.

SIEM feed:
- Feed returns all entries after_id=0, ordered, JSONL parseable,
  limit respected, cursor follows id not ts (id is monotonic; ts
  could tie or drift).
- after_id mid-chain returns the tail only.
- X-IAG-Last-Id / X-IAG-Head headers match row data.
- /feed/stats fields incl. chain_valid true; after a raw-SQL
  tamper (test_audit_tamper pattern) chain_valid false.
- Auditor API key pulls feed 200; report_viewer key 403
  (AuditViewer guard); write attempts 403 (principal read-only).

## Live proofs (real Postgres, per house style)

`scripts/live_risk_check.py`:
1. Login admin -> seed a couple of risk-shaped identities
   (privileged, unreviewed, SoD-triggering).
2. POST /api/risk/runs -> 202, snapshot rows exist.
3. GET /summary -> band distribution contains the seeded shape.
4. GET /trend/{id} -> 2 rows after a second run.
5. Audit chain still valid.

`scripts/live_report_check.py`:
1. Fixture campaign with decisions -> GET /api/campaigns/{id}/report
   -> JSON shape; .csv non-empty, decision rows match metrics.
2. SPA route smoke: GET /campaigns/:id/report serves the SPA shell
   (nginx); rendering is a frontend concern (vite build + TSC).

`scripts/live_siem_check.py`:
1. Create auditor API key.
2. Walk the feed from after_id=0 in 2 pages -> concatenation equals
   the audit CSV export row-for-row (minus hashes) (three-way
   consistency: feed = export = DB).
3. /feed/stats chain_valid true, last_id matches final page.
4. Tamper non-negotiable here (would corrupt the live chain):
   instead verify feed hashes recompute correctly walking pages
   (client-side verify_chain port) -> PASS without writes.
5. Revoke the key.

## Build phases (each ends green: pytest + stack healthy + commit)

- A - model + engine: migration 0007, models/risk.py,
  core/risk_engine.py (pure), unit tests for all 7 signals.
- B - risk API + audit: routers/risk.py (4 endpoints), audit
  entry, ReportViewer alias, integration tests.
- C - SIEM feed: audit router extension, JSONL streaming, cursor
  tests, API-key pull tests.
- D - frontend + report: Risk view, report route + print CSS,
  report.csv button, client namespaces, TSC + vite build.
- E - live proofs + HANDOFF: three scripts, run on stack, HANDOFF.

## Open decisions for ratification

- **D1 SIEM shape - THE BIG ONE**: pull-only audit feed endpoint;
  no push forwarder, no Splunk/Sentinel formatters, no SIEM
  credentials stored anywhere. Alternative rejected: v1's push
  forwarder (sidecar-shaped delivery loop, silent queue drops,
  provider formatters to maintain, credentials at rest).
  Middle option rejected: push with an outbox table (turns every
  audit append into a delivery state machine; the hash chain is
  already the outbox - the feed just reads it).
- **D2 bundle**: risk + PDF + SIEM in one feature. Alternatives:
  three separate features (more overhead than value; they share
  guards, ReportViewer alias, and API-key consumers) vs all-in-one
  (rejected - it's already three parts; bundling risk+report+SIEM
  is the natural seam).
- **D3 risk model**: transparent 7 signals, fixed weights
  (20/20/20/10/10/10/10), bands at 25/50/75, v1 thresholds kept.
  No config UI for weights in v1 of this feature (constants in
  risk_engine.py). dormancy signal renamed unreviewed_access and
  measures review-decision recency (Review.completed_at) because
  IAG has no usage telemetry. Alternatives rejected: configurable
  weights (YAGNI now; constants with a comment), ML scoring
  (unexplainable - the feature's whole point is transparency).
- **D4 risk trigger + retention**: explicit admin POST triggers a
  run; snapshots permanent (trend evidence); no schedule. An
  identity deleted after scoring keeps its snapshot rows (FK SET
  NULL + frozen employee_id). Alternative rejected: nightly
  auto-run (a scheduler inside the app - cron-shaped; if wanted
  later it's a new decision).
- **D5 SIEM authentication**: auditor-role API key only (create
  per feature 4). No separate feed token, no IP allowlist, no
  mTLS. Alternatives rejected: dedicated feed tokens (another
  credential type to manage; feature-4 keys already exist and are
  read-only), IP allowlist (nginx concern, not app concern).
- **D6 PDF method**: print-optimized SPA view + browser
  print-to-PDF. No server-side rendering, no PDF library, no
  WeasyPrint, no jsPDF. Alternative rejected: server-side PDF
  (v1's own dead end - GTK/Windows pain; and server-side files
  violate stateless replicas).
- **D7 API-key role expansion**: feature-4 restricted keys to
  auditor + report_viewer; this feature adds NO new key roles,
  but report endpoints accept report_viewer keys (they are reads
  the role was created for). feed stays AuditViewer (auditor
  keys only) - audit data is the most sensitive surface. No
  alternative considered necessary; if key usage grows, revisit
  per feature-4 D7.
- **D8 new deps**: none. JSONL via streaming response, risk math
  in stdlib, CSV via existing pattern. No weasyprint, no pandas,
  no httpx additions (httpx already present for connectors).

## Settings / env

One new knob: `IAG_RISK_UNREVIEWED_DAYS` (default 90) - the only
time window with domain meaning. Everything else is a constant in
risk_engine.py. Feed limits (500/5000) are constants in the audit
router. No compose.yaml change.

