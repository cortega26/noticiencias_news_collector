# Plan 190 tasks

- [x] Inspect current lifecycle, image guards and editor artifact contract.
- [x] Add failing behavioral regressions before implementation.
- [x] Separate prepared editorial draft from AstroPost assembly.
- [x] Persist checkpoints and migrate publication waiting state.
- [x] Integrate engine/pipeline/batch outcomes and durable resumption.
- [x] Reconcile ready assets and update API/admin contracts and waiting UX.
- [x] Record image provenance and generate/review/stage asset 3822.
- [x] Run focused tests, mandatory gates and independent reviews.
- [x] Exercise DB-copy canary, frontend publication candidate and responsive UI.
- [x] Update active docs, inventory and plan ledger; publish reviewable PR.

Release approval remains separate: migrate/deploy compatible backend/admin,
correlate the live 3822 attempt, and approve editorial content before merging
the frontend canary PR. See [validation evidence](tests/results.md).

- [x] Resolve dependency-review advisory by upgrading Pillow and the compatible
  legacy Refinery lock, then verify final CI on [backend PR #382](https://github.com/cortega26/noticiencias_news_collector/pull/382).
