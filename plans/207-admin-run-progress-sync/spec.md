# Plan 207: Admin run progress follows backend activity

## Goal

Make the `/triage` progress displays for durable collection runs and single or
batch publication runs report the phase and backend step currently executing
for the same persisted `workflow_runs` row.

## Acceptance criteria

- Collection status exposes a typed phase/step progress value and the run's
  lease heartbeat. The displayed phases follow the actual orchestration:
  initialization, collection, validation, scoring, final selection/report,
  and export. Dry runs do not display an export phase.
- Publication status exposes the typed active phase and backend step while
  preserving its completed-stage history and batch item position. Its existing
  six overview phases remain; a new item starts with fresh progress.
- Progress update time and worker heartbeat remain distinguishable in the UI.
  Publication's countdown remains a rough estimate based on historical
  whole-run durations. Collection displays elapsed time and heartbeat only.
- Queued, waiting-for-image, and terminal runs do not appear to be executing an
  active stage. Status remains tied to the requested run ID.
- Progress callback or persistence failures are logged and never change a
  collection or publication result.
- No database migration or publication-content behavior change is introduced.

## Design

- Add a typed admin progress contract containing a stable phase key, phase
  position/count, active step key, step state, and update timestamp. Extend the
  collection and publication status responses additively; expose collection's
  already-persisted heartbeat timestamp.
- Persist the latest progress snapshot in the existing JSON
  `workflow_runs.run_metadata.progress` value. Keep publication's `stages`,
  `item_index`, and `item_count` fields intact.
- Add optional progress callbacks at the collection orchestration boundaries
  and publication workflow step boundaries. Callbacks are observational,
  best-effort updates; existing workflow transitions and external effects stay
  authoritative.
- Keep presentation labels in the admin app. The frontend uses the server's
  phase position and active-step key rather than inferring the current phase
  from a subset of completed markers.
- Update `docs/PIPELINE_CONTRACTS.md` and `docs/PRODUCT_FLOW.md`, then regenerate
  the committed admin OpenAPI artifact and TypeScript schema from the backend
  Pydantic models.

## Verification

- Add regression coverage first for persisted phase/step transitions, progress
  failure isolation, dry-run export omission, batch-item resets, and status
  response/UI behavior for queued, running, waiting, and terminal states.
- Run `make lint`, `make type`, `make test`, `make test-contracts`,
  `make test-boundaries`, `make admin-contracts-check`, `make admin-test`,
  `make admin-build`, and `make admin-lint`.
- Run bounded local collection and publication workflows against an isolated
  database with external publishing effects contained. Verify the admin at
  375px and 1280px.
