# TODO — live publication progress (admin GUI)

- [x] Contract: `AdminPublishProgress` + `progress`/`heartbeat_at`/
      `typical_seconds` on `AdminPublishStatus`
- [x] `RefineryEngine.stage_listener` + `_notify_stage` (non-fatal) + tests
- [x] `publication_pipeline`: listener wiring in single and batch paths +
      `on_item_start` + tests
- [x] `publication_run_workflow`: progress persistence, per-item reset,
      `_typical_seconds` median (batch excluded), status result fields + tests
- [x] `serving/api.py`: map result → `AdminPublishStatus`
- [x] `apps/admin/src/lib/publishProgress.ts` pure helpers + 10 vitest cases
- [x] `triage.astro`: live panel (phases, elapsed/ETA, stall flag, 1 s ticker)
- [x] Regenerate `openapi.json` + `api.d.ts`
- [x] Focused green: 37 backend tests, 10 frontend tests, ruff/black clean,
      `make admin-contracts-check` green
- [x] Inventory refresh + check (spec/todo + 3 new source/test files)
- [x] Full gates: `make lint`, `make type` (3508 passed, ratchet 93.14% vs
      91.25%), `make test` (3495 passed), `make test-boundaries` (3),
      `make test-contracts` (171), `make admin-test` (45)
- [ ] Live smoke: publish with `SERVING_RELOAD=0` and watch the panel (operator)
- [ ] Commit + PR
