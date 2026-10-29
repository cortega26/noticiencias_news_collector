# Plan 207 test map

Regression tests will live beside the existing workflow, API, and admin
progress tests:

- Collection workflow: phase/step updates at real orchestration boundaries,
  dry-run export omission, heartbeat exposure, and progress-write failure
  isolation.
- Publication workflow: active step and phase position, completed-stage
  compatibility, item reset for batch runs, and advisory callback failures.
- Admin API/OpenAPI: additive typed fields, exact run-ID lookup, and no live
  progress/heartbeat/estimate while waiting for an image.
- Admin progress UI: server-reported phase position and active-step label,
  separate heartbeat and progress timestamps, rough publication ETA, and
  collection elapsed time without ETA.

No test calls a real provider or pushes a publication. The local workflow
verification uses an isolated database and contained external adapters.
