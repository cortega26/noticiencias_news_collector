# Phase 1 — Model-based lifecycle regression tests

Prerequisite: Phase 0. Risk: High (workflow evidence). Default: test-only.

## Read first and copy patterns

Read both workflow classes, their unit test files, Plan 078, and the Hypothesis
stateful example linked in Phase 0. Copy the repository's real SQLite manager
setup and no-op `_dispatch` approach. Copy Hypothesis's machine-owned resource
lifecycle; do not wrap the existing function-scoped mutable fixture in `@given`.

## File scope

- **New:** `tests/property/test_workflow_lifecycle_stateful.py`.
- Existing two workflow unit test files: only add missing focused boundary
  regressions or a minimized failure discovered by the machine.
- This phase's checklist and evidence. No production edits by default.

Hypothesis is already in the test extra and `requirements-security.lock`; no
new test framework or runtime dependency is required. Import it normally in the
new required suite; a missing install must fail, not silently skip the suite.

## Design

Use one test-local machine exercising **both** workflows against one isolated
SQLite database. It has a concrete second consumer and verifies isolation
between run types; it is not a production abstraction. Do not create a generic
workflow framework or change the production inheritance structure.

Each generated example owns its `TemporaryDirectory`, `DatabaseManager`, schema,
clock and `pytest.MonkeyPatch()` instance. `teardown()` closes the manager,
undoes patches and removes temporary resources even on failure. Initialization
failure must clean already-created resources. Use the existing
`Base.metadata.create_all(manager.engine)` fixture pattern; this is not a
migration test or a substitute for existing migration tests.

Patch the `datetime` binding in each workflow module with a small test-local
subclass whose `now(tz)` returns the controlled UTC time. Start from a fixed
aware timestamp. Do not patch Python's global datetime or add a clock dependency
to production solely for this suite. Normalize SQLite's naive UTC timestamps
only when comparing observations. Set test lease to 60 seconds; leave production
lease and heartbeat cadence unchanged. Replace both `_dispatch` methods with
recording no-ops; no background heartbeat or collection/editor work may execute.

Maintain a separate model of each created row's state, start time, heartbeat and
request metadata. Compute expected outcomes from the table below **before**
calling the implementation. Never call `recover_expired_leases()` or inspect its
SQL predicate to decide the expected answer.

| Action | Expected behavior |
| --- | --- |
| Start collection/publication | First recover only stale running rows of that type. If queued/running remains, return `already_running` with its ID; otherwise create exactly one queued row and record one dispatch. Publication uses exactly one valid input, e.g. `article_id=42`. |
| Begin queued run | Invoke `_transition(id, from_status="queued", to_status="running")` to stand in for dispatch. Only matching queued rows change. This is the only supported queued-to-running seam. |
| Heartbeat own run | True and clock timestamp only when running; otherwise False and no row changes. |
| Complete / fail own run | Only running becomes succeeded/failed; terminal timestamp set. Request metadata preserved. Use each class's actual signature; only publication `fail` accepts an optional summary. |
| Advance clock | Choose integer second increments including 0, 1, 59, 60, 61 and 120. Time change alone does not recover anything. |
| Recover during service | `include_queued=False`: only running rows older than cutoff become interrupted. Missing heartbeat uses start time. |
| Simulate boot of one workflow | Recreate that workflow with the same DB, reinstall its no-op dispatch, call default recovery. Queued rows of that type become interrupted; running rows still use expiry. All simulated owners are stopped; this does not claim multi-process boot safety. |
| Repeat terminal operation | Heartbeat/complete/fail cannot resurrect or overwrite a terminal row. |

Keep explicit run IDs grouped by owner. Do not pass collection IDs into
publication `complete`/`heartbeat` and then assume these methods validate
ownership: current ID-based methods do not contain a run-type predicate.
The scoped-isolation contract here concerns `start`, recovery and status lookup.
Do not misuse `_transition` to invent arbitrary terminal-to-running transitions.

## Acceptance and failure probes

- **W1 — Single active row:** after every action, database and model agree; at
  most one active row per type; one collection and one publication may coexist.
- **W2 — Expiry:** `heartbeat_at < now - lease` is stale; equality is fresh.
  NULL heartbeat uses the same strict comparison on `started_at`. Add explicit
  59/60/61-second examples so discovery does not depend on random generation.
- **W3 — Queued safety:** a second live `start()` never reaps a queued row, even
  if old. Simulated boot recovers queued rows. Fresh NULL-heartbeat running rows
  survive both recovery modes; old ones do not.
- **W4 — Terminal stability:** repeated operations and repeated recovery preserve
  completed/failed/interrupted rows and request metadata; recovered ID lists
  contain only rows actually transitioned. Both run types remain isolated.
- **W5 — Test isolation and sensitivity:** no real threads/network, no production
  DB/cache/log writes, and no patches leak to subsequent tests. In an isolated
  temporary copy or reviewed temporary diff, change one expiry comparison or
  queued-recovery setting and show the new suite fails; restore exactly that
  change. Never reset someone else's work. Preserve a minimized ordinary
  regression for any newly discovered defect.

Start with `max_examples=20`, `stateful_step_count=20`, `deadline=None`,
`derandomize=True`, `database=None` on the exported `TestCase`. This is a bounded
CI profile, not a statistical guarantee. The repository's pytest timeout still
applies. If measured suite time exceeds 10 seconds, set a **test-local** timeout
of 60 seconds with timing evidence; do not alter the global timeout. If it exceeds
60 seconds, reduce repeated setup/query work or split the cases and remeasure.
Do not suppress Hypothesis health checks to accommodate shared mutable fixtures.

Existing HTTP/concurrency tests remain mandatory. This machine verifies
sequential operation histories, not all thread interleavings, stale-owner fencing,
or exactly-once external publication.

## Verification

```bash
.venv/bin/python -m pytest tests/property/test_workflow_lifecycle_stateful.py tests/unit/logic/workflows/test_collection_run_workflow.py tests/unit/logic/workflows/test_publication_run_workflow.py --no-cov -q
.venv/bin/python -m pytest tests/test_serving_admin_api.py --no-cov -q
make lint
make type
make test
make test-boundaries
```

Record W1–W5 evidence in `tests/phase-1-results.md` under this plan. A production
defect requires updating this spec, adding a minimal regression/fix and running
the union of affected gates. Do not silently bless a failing implementation.

Rollback: remove this isolated test addition only if the test itself is invalid;
do not change the runtime to satisfy a mistaken model.
