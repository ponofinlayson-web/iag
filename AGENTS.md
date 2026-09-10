# AGENTS.md — operating rules for agents working in this repo

You are a fresh agent session. This file is durable rules and hard-won
knowledge. It does not change session to session. For current project
state read, in order: `HANDOFF.md` (continuation point + ratified user
decisions), then `.openhands/memory/MEMORY.md` (session history, newest
first; host-local, gitignored — absent on a fresh clone), then
`REQUIREMENTS.md` + `ARCHITECTURE.md` (frozen contracts —
do not re-litigate them; ratified changes are recorded in HANDOFF.md).

## What this repo is

IAG — self-hosted identity & access governance (clean-room v2; the v1
codebase `D:\IAM-Simplified` / equivalent is read-only reference only,
copy NO code from it). Private. Publishes a public docs site via a
separate repo (see "docs-forge" below).

- GitHub: `ponofinlayson-web/iag` (private). Default branch `main`.
- License MIT (2026-09). CI on ubuntu: backend `uv sync --frozen` then
  `uv run pytest tests/ -x -q` with `IAG_ENV=test`.

## Commands (verified working)

- Backend: work from `backend/`. Venv is `backend/.venv` (root `.venv`
  does NOT exist). `uv sync --frozen`, then `uv run pytest -q`
  (conftest handles IAG_ENV; no export needed locally).
- Frontend: `frontend/`, `npm run build` = `tsc -b && vite build`.
  `npm run dev` for the Vite dev server.
- Full stack: `docker compose up -d --build` → port 8090. Compose
  project name `iag`. **This is the production stack — treat as live;
  ask the user before `down -v` or anything destructive.**
- Docs/validation stack: `compose.test.yaml` overlay, project
  `iag-test`, port 8091. Use this for anything experimental.
- Backend tests are the gate: 290 passing as of v0.3.0; never merge
  with regressions.

## API shapes that have bitten agents (do not rediscover)

- `GET /api/sources` — no trailing slash, returns dict with `items`.
- Connector update: `PUT` body is `{config, sync_interval_minutes}`;
  absent config keys are preserved, blank clears (P3 semantics, 2026-08).
- E2E residue users (e.g. `t5_browser`, `p6_browser`) exist in dev DBs;
  acceptable, do not "clean" them without asking.

## docs-forge (validated docs pipeline)

`scripts/docs-forge/` — engine (`forge.py`) + profile
(`profiles/iag.json`). Flow: capture (screenshots against the isolated
8091 stack) → evidence → export (MDX refresh) → publish. Run with a
Python that has Playwright installed.

Design rules (paid for 2026-08-26; forge.py's docstring points here):

- Agents/LLMs never invent numbers: evidence text is captured verbatim
  from tool output. No handwritten stats in docs.
- Screenshot manifests fail on blank frames (< min_bytes) and
  byte-identical frames — a duplicate screenshot is a build failure.
- Mintlify: `docs.json` uses the navigation OBJECT form, theme `mint`;
  assets go at the SITE ROOT (`public/` is NOT served); the dev server
  caches its manifest — restart it after nav changes.
- Secrets live in env files referenced by the profile (`.env` key
  `IAG_BOOTSTRAP_ADMIN_PASSWORD` for the isolated stack login), never
  in the repo. `.env` is gitignored; keep it that way.
- Relative paths in a profile resolve against its `root`, not CWD.
- The original live stack (containers `iag-db`, `iag-nginx`,
  `iag-app-1..3`, `iag-glauth` on 8090) must never be touched by forge
  runs — the profile encodes this; do not bypass it.

Publishing: `forge.py publish` copies the site into a local clone of
`iag-docs` (profile `publish.repo`), commits, and pushes to
`github.com/ponofinlayson-web/iag-docs` → live at
`docs.iam-simplified.com` (Mintlify). `iag-docs` is PUBLIC: no host
notes, internal process, or secrets there, ever. Its "Workers Builds"
GitHub-App check shows a permanent red X — cosmetic (deploys are
Mintlify-side, not git-connected); ignore it.

## Host notes (repo developed on Windows until 2026-09; now Linux)

Things that were ritual on the Windows host and are NOT needed on
Linux: CRLF normalization/`fix_eol.py` byte-checks before commits
(`.gitattributes` still enforces `*.sh`/`*.env` LF — keep it), the
`pwsh`-vs-`powershell` distinction, PowerShell JSON mangling workarounds
(request-body files). Drop the rituals, keep the guardrails.

Things that follow the agent harness regardless of host — still apply:

- The command layer can STRIP BLANK LINES from multiline command text.
  Countermeasure: write long/multiline payloads to a file, byte-verify
  (`repr` / `git cat-file`), then use the file (`git commit -F`).
- Display output flattens multiline text (e.g. git log bodies look
  fused). Verify raw bytes, not the rendered terminal, before claiming
  corruption.
- Browser automation cannot operate native `<select>` elements —
  exercise select values via API, verify UI in-browser.

## Credentials & auth

- Git pushes/PRs: use `gh` CLI (needs `gh auth login`; scopes `repo`,
  `workflow`). The env `GITHUB_PERSONAL_ACCESS_TOKEN` on the old host
  was contents-write-only (no PR API) — if a token lacks rights, use gh.
- Mintlify/Cloudflare secrets are host-injected env vars, not repo
  content. Re-provision on a new host; never commit values.

## Working style (user preferences, ratified)

- Verify before asserting; label inference: [V] verified, [H] hypothesis,
  [X] unknown. Never fabricate SHAs, counts, or file states.
- Ask before pushing to `main`, force-pushing, or deleting anything.
  Branch + PR is the default for anything beyond a session's agreed
  direct commits.
- Commits carry `Co-authored-by: openhands <openhands@all-hands.dev>`
  when agent-authored.
- At session close: update `HANDOFF.md` (move finished work out of
  NEXT, record new decisions/ratifications) and append a session entry
  to `.openhands/memory/MEMORY.md`, then commit.
- Tone: plain-spoken, honest about fragility; flag subtle wins.
