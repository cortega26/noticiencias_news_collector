# Plan 184: Retire the two UI layers and the template freeze (060 Phase 9, item 5)

> Docs/governance + script removal; run every verification; stop on STOP.
> **Drift check (frontend)**: `git diff --stat 5404b84f..origin/main -- AGENTS.md docs/ARCHITECTURE.md docs/adr scripts/freeze-template.js package.json tests/quick-wins-regression.test.ts scripts/check-doc-drift.js`

## Status

- **Priority**: P2 (060 Phase 9 item 5)
- **Effort**: S
- **Risk**: LOW (no runtime UI change; docs/scripts/tests)
- **Depends on**: 179–183 (zero live template consumers)
- **Category**: frontend governance
- **Planned at**: frontend `5404b84f`, backend `03192c3e`, 2026-10-20

## Why this matters

Plan 183 emptied `src/components/template/**` and `src/layouts/template/**`
(no live imports) and proved behaviour-neutral: 313/313 HTML hashes identical,
metadata identical, 17 Playwright screenshots pixel-identical. ADR-0002's
two-layer law and the freeze guard are now dead governance. Phase 9 item 5:
supersede the law, update the active docs, and remove the layer/guard
deliberately.

## Steps

1. **ADR-0014** (`docs/adr/0014-retire-two-ui-layers.md`): Accepted, date
   2026-10-20, supersedes ADR-0002. Context (0002, the freeze, plans 179–183
   with the proof), decision (single supported structure: `ds` primitives,
   `common` site fragments, `layouts` chrome; no template paths; remove the
   freeze; keep ds route-agnostic/typed), consequences (no dual taxonomy; the
   reachability checker replaces the guard; future AstroWind changes go
   directly to ds/common; historical records remain), alternatives.
2. **ADR-0002**: status → `Superseded by ADR-0014 (2026-10-20)`; keep the
   historical decision text.
3. **AGENTS.md**: the retired-layer paragraph and LAW-F2's template bullet now
   cite ADR-0014 as the decision (not "until the ADR lands"); the reject list
   says "importing from the retired template paths" (the ds→template rule is
   historical).
4. **docs/ARCHITECTURE.md**: the `common/` section cites ADR-0014 and states
   the single supported structure; no other active doc claims a live template
   layer.
5. **Remove the guard**: delete `scripts/freeze-template.js`; remove
   `check:freeze` from `package.json` and from `validate:content`; remove the
   template search-dir hints from `scripts/check-doc-drift.js`.
6. **Tombstone regression**: update the `quick-wins` test that asserted
   `ds` never imports template to assert that no file under `src/` imports
   `components/template/` or `layouts/template/`, and that neither directory
   exists. Keep the rest of the test file.
7. Remove the now-empty directories (`rmdir src/components/template
   src/layouts/template`; git does not track empty dirs).
8. Gates: `npm run lint` (checker + doc-drift + prettier + eslint),
   `npx astro check`, `npm run build` (299 pages), `npm run test:audit`
   (≥987), `npm run test:dist`, `npm run format:check`,
   `npm run validate:content` (without the freeze step). No visual pass needed
   (docs/scripts only), state that explicitly.
9. Commit, push, open **one** PR, wait for checks, merge. Do not leave it open.
10. `plans/060/todo.md`: mark item 5 done; the Phase 9 section is then
    complete. `plans/README.md` row 184 updated by the reviewer.

## Done criteria

- [ ] ADR-0014 accepted and ADR-0002 marked superseded
- [ ] AGENTS/ARCHITECTURE cite 0014; no active doc claims the layer is live
- [ ] Freeze script/scripts/CI step removed; template dirs gone
- [ ] Tombstone regression asserts no source imports/dirs
- [ ] lint/check/build/987+ tests/test:dist/validate:content green
- [ ] One PR merged; 060 item 5 done; ledger row 184 updated

## STOP conditions

- A live import of the template paths remains (report; 183 incomplete).
- Removing the freeze breaks a CI or pre-commit hook that cannot be updated
  safely (report; do not leave a broken reference).
- An active doc's authority chain conflicts with ADR-0014 (report the docs).
- Any runtime UI change is needed (it is not).
