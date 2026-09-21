# Spec — Curation Desk revamp (apps/admin): sober ES UI, action hierarchy, comprehension

Operator decision: Spanish UI, desktop-only. No backend/API changes. No new
pages, deps, or component library. Design system (global.css palette, Fraunces/
Manrope/JetBrains Mono) stays; only decorative layers go.

## Phase 0 — kill list

- Remove ✨ from 4 publish buttons (triage x3, article x1); ⚙ nav glyph ->
  text-consistent glyph; remove jargon (Refine/export shortlist/publication
  run -> Publicar/lista/envío); publish CTA wording -> "Publicar".
- Remove ambient radial glows + noise overlay (flat sober).
- Fix latent bug: `.btn-primary` used without `.btn` base (no padding/
  radius) — compose base into variants in global.css.

## Phase 1 — hierarchy (one primary per context)

- Detail panel 7 buttons -> Publish (primary) + View split (ghost) + overflow
  for Reprocess + Reject as quiet danger link w/ confirm + Audit segmented
  [Pass|Fail]. Hotkeys j/k/p/r/a/f/o unchanged.
- Queue cards: drop per-card publish buttons; reason surfaces in detail panel
  ("Por qué no se puede publicar").
- Header: dry-run checkbox -> toggle inside collect-status line, visible only
  during a run.

## Phase 2 — comprehension

- Score + threshold caption (above/below publish line, derived from
  publishable flag + min threshold already in envelope).
- why_ranked expandable (+N more).
- Filter pills: operator labels (A publicar · Bandeja · Publicando ·
  Descartados · Publicados), values unchanged (API contract), counts per pill.
- One status region + one toast style; delete redundant boxes.
- Teaching empty states.

## Phase 3 — language / access / entry

- Full Spanish UI (hardcoded, single operator; English technical nouns only
  where the API/backend names them: run id, PR, slug).
- `/` redirects to `/triage` (drop splash).
- Desktop-only: min-width notice instead of broken narrow layout.
- A11y: focus-visible on cards, Esc clears selection, live-region status.

## Verification

- `make admin-test` (vitest), `make admin-build` (astro build = syntax gate),
  `astro check` (types), backend `make lint` scope for apps/admin if covered.
- Screenshots 1280px (+375px notice check) before/after per PR.
- 3 PRs (P0 -> P1 -> P2), P3 rides with P2 or its own; each independently
  revertible. No UI test harness exists for .astro — build+check are the gate.
