# Feature 7: RBAC user management + theme system (light/dark + accent dispersion)

RATIFIED 2026-08-24, post-0.2.0. Decision points D-a…D-e are
resolved as inlined in this document (no DELETE; self-guards as
written; admin-set passwords, no email flow; OS-preference first-visit
default, else dark, explicit choice sticky; version 0.3.0).

## 0. Why

Pass-2 left the User model half-served: login accounts exist only via
bootstrap or hand-run scripts (`e2e_admin.py`); no endpoint can create,
re-role, deactivate, unlock, or reset a user (D0). Separately, the UI is
dark-only with color appearing only in badges/buttons; the user wants a
light/dark toggle and more consistent color across pages without
abandoning the jade palette.

## D1 — Backend: users router (system_admin)

`app/routers/users.py`, prefix `/api/users`, all routes AdminUser
(system_admin), every state change audit-chained (same transaction).

- `GET ""` — list users joined to identity: id, username, email, names,
  department, role, is_active, must_change_password, failed_attempts,
  locked_until, last_login (from latest `login` audit row for that
  actor_id; read-side join, no new column).
- `POST ""` — body {identity_id, role, password}. Creates the User row
  on an existing Identity that has no User yet (409 if taken; 404 if
  identity missing). Sets must_change_password=true. Password rules =
  existing change-password constraints (min 8). No email-sending.
- `GET /{id}` — detail (same fields + recent audit actor activity count).
- `PUT /{id}/role` — body {role}. Guard: cannot change own role
  (400 — prevents locking yourself out mid-session).
- `PUT /{id}/status` — body {is_active}. Guard: cannot deactivate self.
  Deactivation is immediate (get_current_user checks is_active per
  request — D0 finding; no token revocation list needed).
- `PUT /{id}/unlock` — clears failed_attempts + locked_until. Allowed
  on self (a locked-out admin is the reason this exists).
- `PUT /{id}/reset-password` — body {password}: sets hash +
  must_change_password=true. Audited as password_reset with actor ≠ target.
- No DELETE (deactivate instead — audit-referential integrity; matches
  identities pattern where delete exists but users are login surface).

Sessions: token carries role but guards read the DB row each request
(deps.py), so role/deactivate/unlock apply on the next request with no
token-versioning column. [D0 verified]

Tests (in-repo SQLite pattern): create/list/role-change incl. self-guard,
deactivate incl. self-guard, unlock, reset-password flow, audit rows
written, 403 for cert_admin, cannot create second user on same identity,
login as created user, login blocked when deactivated, must_change_password
reflected in /auth/me.

## D2 — Frontend: Users view (system_admin only)

`views/Users.tsx` on the Pass-2 primitives:
- DataTable: username, name, department, role, status (active/disabled/
  locked badges), must-change flag, last login. Filters on role/status.
- "Add user" modal: identity Typeahead (existing `?q=` endpoint), role
  select, generated-or-entered password with copy button + "shown once"
  discipline (reveal-modal pattern already in ApiKeys view).
- Per-row actions: change role (modal select), deactivate/reactivate,
  unlock (shown only when locked), reset password (modal, reveal-once).
- Route + nav link gated on role === system_admin (nav hides; router
  403s — belt and braces, API remains authority).

## D3 — Theme system: light + dark, token-consistent

- `:root` = dark values (current, default). `:root[data-theme="light"]`
  overrides the same 17 tokens. No component CSS changes — everything
  already consumes tokens only (Pass-2 made this true).
- Toggle in topbar userbox: sun/moon button, persists to
  localStorage `iag.theme`, applies before first paint (inline script in
  index.html reads localStorage + sets data-theme to avoid flash).
  Default = dark (current behavior preserved for fresh installs).
- New tokens added where components currently hardcode:
  `--ok/--warn/--bad` stay; add `--accent-soft` (accent at low alpha for
  fills: nav active, selected rows, modal focus ring bg) and
  `--info` (blue, for informational/neutral-positive accents like
  source-kind badges, connector type chips).
- Light palette: near-white bg (#f5f7f9 family), panel white, borders
  #d3dae2, text #1a2129 (AAA), muted #4d5866 (AA+). Accent tokens
  re-derived: light mode needs darker fills for AA on white —
  `--accent` #1d7a55, `--accent-strong` #17805c (unchanged, passes on
  white too), hover/active ramp darkened. All pairs validated via
  scripts/contrast_check.py; light theme gets its own section in the
  script (both themes must pass AA, text/muted AAA where dark does).
- `prefers-color-scheme` respected ONLY as first-visit default when no
  localStorage value exists (then it's sticky per explicit choice).

## D4 — Accent dispersion (consistent color across pages)

Discipline: color comes from tokens, applied by role — not per-page
hand-tuning. The point is "same decision, every page":

- Nav active link: accent-soft fill + accent text (currently gray).
- Page identity: every view's Card title row gets a 3px accent left bar
  (single CSS rule on .card h2::before — one rule, whole app).
- Stat cards (Dashboard): value colored by meaning where one exists
  (pending=warn, violations=bad, healthy=ok, plain=text); label stays
  muted. Consistent mapping = the consistency the user asked for.
- Table header sort indicator + active filter chips: accent.
- Badge tones extended, not replaced: ok/warn/bad/neutral gain a new
  `info` tone (blue) for source-kind/connector-type/SCIM status; role
  badges in Users view get tone per role (system_admin=bad-family?
  NO — authority≠danger; system_admin=accent, cert_admin=info,
  reviewer=neutral, auditor=warn, report_viewer=neutral).
- Buttons: primary (accent-strong) stays; secondary/ghost buttons
  (Cancel, Export links) get a defined ghost style: transparent bg,
  border var(--border), text var(--text), hover panel-2 — currently
  they're inconsistent per view.
- Focus rings: --accent everywhere (already true post-Pass-2; verify).

Non-goal: per-view palettes, gradients, charts restyling beyond token
inheritance (risk trend lines keep their tone mapping).

## D5 — Deliverables/verification

- Backend: router + tests (suite grows; all green).
- Frontend: Users view, theme toggle, D4 rules, tsc + vite build clean.
- contrast_check.py: light + dark matrices, all AA (text/muted AAA).
- Deploy gate: compose build + up, bundle hash changes, walkthrough as
  e2e_admin (system_admin) incl. Users view create/role/deactivate and
  theme toggle persistence across reload.
- Version 0.2.1 (new feature → minor: 0.3.0? PATCH vs MINOR debate:
  user-facing features = MINOR per SemVer → **0.3.0**) + CHANGELOG.

## Decision points for ratification

- D-a: No user DELETE (deactivate only). OK?
- D-b: Self-guards: can't change own role / deactivate self, CAN unlock
  self. OK?
- D-c: Password set by admin (typed or generated), no email invite flow.
  OK? (SMTP is currently disabled in this stack anyway.)
- D-d: Light mode default for new users = OS preference, else dark;
  explicit choice sticky. OK?
- D-e: Version 0.3.0. OK?
