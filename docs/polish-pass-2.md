# UI Polish Pass 2 (post-v0.1.0)

From the user's own walkthrough notes, 2026-08-23. Ordered by how I'd work
through them: shared foundations first (they make the rest cheaper), then
per-view conversions, then the visual layer on top. Items 1–4 are component
work regardless of theme; item 5 is a token retune in one file.

Status key: [ ] todo · [x] done · (V) = verified live

## 1. Foundation: Modal + DataTable primitives in components/ui.tsx

Not on the user's list, but everything else depends on it. Without a shared
primitive, "put the fields in a modal" is N different hand-rolled overlays
and "all tables get filters" is 14 bespoke implementations.

- [x] `Modal` — overlay, dialog card, Esc/backdrop close, focus management
      (focus starts on first field, focus trap inside dialog, restore on
      close).
- [x] `Typeahead` — debounced autocomplete text input built on the same
      lookup API as (2). Props: `lookup(query) -> {id, label}[]`,
      `onSelect(item)`, placeholder. Used by owner-ID field and table
      search.
- [x] `DataTable` — generic table on column definitions:
      `columns: { key, label, render?, sortable? }[]` + `rows`. Wraps a
      plain `<table>` (not a grid library) and owns:
      - per-column filter row (input) or filter dropdown (categorical)
      - sort on header click (local state; multi-sort not needed for v0.1
        scale)
      - column show/hide + drag-to-reorder in a "Columns" popover, with
      `id`/`name` glued far-left, always visible, excluded from hide/reorder
      - client-side search box with autocomplete chips
      - sticky header + sticky first columns on wide tables
 - [x] Per-view column prefs persisted to localStorage (keyed by view)
      so the layout survives reloads.

## 2. Sources: Create as modal + owner autocomplete

- [x] Sources view: replace exposed create-form with a "Create source"
      button opening the `Modal` with the existing fields.
- [x] Owner employee ID: `Typeahead` over real identities. ~~Requires a
      backend addition — `GET /api/identities?q=...` search param (today
      the router only has plain list/detail/CRUD).~~ Verified: `q=`
      already existed; pure frontend change. Invalid/unmatched owner
      IDs must be rejected client-side (if the ID doesn't exist, it
      can't own a source).
- [x] Owner field validation: on submit, unmatched ID = inline error,
      not a silent pass-through.

## 3. Campaigns: Create as modal

- [x] Campaigns view: same conversion as Sources — "Create campaign"
      button + `Modal` with the existing fields (name, mode, description,
      deadline). Fields are fine per user; only the form placement changes.
- [x] Scope editor stays on the campaign detail page (already built in
      the T3 pass).

## 4. SoD Rules: Create as modal + manual run

- [x] SoD Rules view: fields behind a "Create rule" button + `Modal`.
- [x] Manual run: pattern already exists in Risk (`POST /api/risk/runs`
      202 + poll snapshots). Needs a new backend endpoint
      `POST /api/sod/rules/{id}/run` (or `/api/sod/runs`) that evaluates
      the rule live and stores an evaluation snapshot — same audit
      discipline as every other state change.
- [x] Manual run surfaces violations inline (table below the rule or a
      result modal): identity, entitlement pair, severity.
      Violations are already computed per campaign preview; the manual run
      just makes them available on demand outside a campaign.

## 5. Theme: jade green + contrast pass

The "different styling template" reality: there is no template. The entire
theme is `frontend/src/styles.css`, 143 lines, CSS custom properties in
`:root`. This is a token retune, not a swap. Keep the dark base; retune:

- [x] `--accent: #4f8cc9` (steel blue) → jade green (target ~#2fa87c /
      #35b586 family; final call at implementation, validated for WCAG AA
      against the dark panel colors).
- [x] Buttons must look like buttons: solid accent fill, clear borders,
      hover/active states, consistent sizing across views. Today they're
      mostly bare `border: none` pills that read as text links.
- [x] Table grid lines: visible column separators + row borders using
      `--border` (and slightly stronger than the current hover-only
      borders) so rows/columns read as a grid, not floating rows.
- [x] General contrast bump: `--text`/`--muted` on dark panels toward
      AAA where cheap, AA everywhere else; badge tones stay.

Implementation note (item 5): one hue, two depths — `#2fa87c` passes AA
as accent *text* on every surface but fails with white text on it (2.99);
button fills use a darker fill from the same jade family, `#17805c`
(white 4.91), with hover `#127a52` / active `#107049` keeping AA.
Ratios computed in `scripts/contrast_check.py`.

## Verification gates (every item)

- [x] `tsc -b` clean, `vite build` clean, suite 268/268 green (backend
      additions in 2 and 4 touch tests). [274/274 after this pass]
- [ ] Deploy path: `docker compose build iag-migrate iag-app-1 iag-app-2
      iag-app-3 && docker compose up -d`; verify live bundle hash change
      in iag-nginx static volume.
- [ ] Browser walkthrough of every affected view as e2e_admin.
- [x] Version bump to 0.2.0 at the end of the pass (CHANGELOG entry).

## Non-goals

- Server-side pagination/virtualization — dataset scale doesn't need it
  yet; noted for when identity counts get real.
- Drag-and-drop column reordering via a library — native HTML5 DnD on
  the Columns popover is enough at this scale.
- Changing PUT replace-semantics on sources (unchanged from v0.1).
