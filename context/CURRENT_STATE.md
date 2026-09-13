# Current state — navigation summary

Status: Derived. Checked 2026-09-04; source code may evolve after this snapshot.

Read `docs/SOURCE_OF_TRUTH.md` for authority, `docs/AGENTS.md` for change rules,
and `docs/PIPELINE_CONTRACTS.md` for boundary and lifecycle behavior.
`context/INVARIANTS.md` and module notes summarize those sources; they do not
create independent architectural law. `context/MODULE_INDEX.md` is a selected
navigation index, not a complete call graph or signature registry.

Current entrypoints are the collector CLI, FastAPI serving and the Astro
admin at `apps/admin/` (`make admin`). Streamlit remains a legacy fallback.
SQLite is the selected database. Collection and publication lifecycle rows
persist in `workflow_runs`; expired running leases can recover at dispatch.
Execution itself still uses process-local threads, without durable step replay.

Plan status lives in `plans/README.md`. Plan 080 describes proposed stateful
tests, generated admin response types and an offline prompt evaluation pilot;
it is not evidence that those features are implemented.
