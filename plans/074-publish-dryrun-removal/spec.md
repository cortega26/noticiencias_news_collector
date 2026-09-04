# Plan 074 — Remove dishonest publish `dry_run` flag

## Finding

`POST /v1/admin/publish` accepts `dry_run`, threads it through
`PublicationRunWorkflow.start/_dispatch/_run` into `run_refinery()` —
but NOTHING downstream consults it on the publish path (verified:
zero matches in engine, PR orchestrator, target writer, publisher).
A "dry-run publish" executes a full real publish (branch + push + PR).
Nobody sends `true` (UI never passes it; no script/CLI does), so removal
changes no real behavior — it removes a promise of safety that doesn't
exist. (Collect dry-run is real and untouched.)

## Design

Delete the publish-only flag end to end:

1. `contracts/admin.py`: drop `dry_run` from `AdminPublishRequest`.
2. `serving/api.py` (`admin_publish`): stop forwarding it.
3. `publication_run_workflow.py`: drop `dry_run` from `start`,
   `_dispatch`, `_run` + `run_metadata`. (`run_refinery()` keeps its own
   param — shared with real collect dry-runs.)
4. `apps/admin/src/lib/api.ts` (`startPublish`): drop `dryRun?` option
   and the `dry_run` body key.
5. Regenerate `.contract-snapshots/admin_openapi.snapshot.json`.
6. Update tests asserting the flag on this path
   (`test_publication_run_workflow.py`, `api.test.ts`).

Non-goals: implementing a real publish dry-run (rejected — new
orchestrator semantics + maintenance for a mode nobody asked to use;
revisit if editors ever need preview mode); touching collect dry-run.

## Verification

- `grep` post-change: no publish-path `dry_run` outside history/docs.
- `make lint && make type && make test && make test-contracts &&
  make test-boundaries`; admin `check + test + build`.
