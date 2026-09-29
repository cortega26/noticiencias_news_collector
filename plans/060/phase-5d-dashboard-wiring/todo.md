# Plan 060 / Phase 5d todo — Dashboard health wiring (frontend)

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this
checklist alone. All work happens in `../noticiencias`.

## Step 0 — baseline + drift

- [x] Drift check clean at frontend `14d59f4` (branch created; diff empty).
- [x] Baseline recorded (2026-09-25: the raw `npm run test:audit` has one
      dist-dependent failure on a fresh checkout
      (`article-hero-rendering.test.ts`); after `npm run build` the suite is
      773 passed / 71 files — recorded as the functional baseline).

## Step 1 — generate-metrics health section

- [x] `schema` via snapshot-mode contract check (`spawnSync`, bounded
      detail, unknown when files/spawn fail).
- [x] `hero_images` via `collectHeroImageDiagnostics({ repoRoot })`
      (unknown with no posts, warning with errors).
- [x] `editorial` / `derivatives` promoted to health records (`unknown`
      replaces the old zero-gap `pass` when there are no v2 posts/manifest).
- [x] `lint` from `CHECK_RESULTS_PATH` (`unknown` when unset/unreadable).
- [x] `callbacks` / `publication` / `validation` from `BACKEND_ADMIN_URL` +
      `BACKEND_ADMIN_TOKEN`; network/status/shape failures → `unknown`;
      `evidence: "none"` forces `unknown`; ages intentionally not copied
      (no-churn).
- [x] async `main()` + no-churn preserved.
- [x] tests: 11 in `tests/generate-metrics.test.ts` (unknown paths, hero
      pass/warning/empty, lint artifact, backend success via local HTTP
      fixture, unreachable endpoint, `evidence: none` override).

## Step 2 — dashboard wiring

- [x] `healthChecks` from `metrics.health.*` with `unknown` fallbacks (no
      status inferred from another metric).
- [x] Callbacks, Publicación and Validación (Content Guard) rows added
      (8 checks; `DashboardHealthList` already renders `fail`).

## Step 3 — workflow + committed metrics

- [x] lint evidence step (`continue-on-error`) →
      `$RUNNER_TEMP/check-results.json`; backend secrets passed to the
      generator.
- [x] `npm run generate:metrics` refreshed and committed:
      schema/editorial/hero/lint/derivatives `pass`,
      callbacks/publication/validation `unknown` (secrets not yet
      configured).
- [x] Stale snapshot surfaced by the new check and regenerated:
      `npm run check:contract-sync` (live, strict) was already clean, so
      `npm run sync:contract-snapshot` refreshed the 2026-09-06 snapshot
      (+169 lines) and the snapshot check now passes.

## Step 4 — gates + docs

- [x] Frontend gates (2026-09-25): `npm run lint`,
      `npm run validate:content`, `npm run build`, `npm run test:dist`,
      `npm run test:audit` (780 passed), `npm run check:doc-drift` — all
      green.
- [x] `plans/060/todo.md` Phase 5 item 5 checked with evidence.
- [x] `scripts/validate_plans_ledger.py` OK (backend repo).
