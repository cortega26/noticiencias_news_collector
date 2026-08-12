# Plan 040: Account for every collector-dispatch outcome

> **Executor instructions**: Preserve partial success, but never lose the collector type/source group associated with a task failure. Update plan 040 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/collectors/dispatcher.py news_collector/system news_collector/contracts/system.py tests/unit/collectors/test_dispatcher.py tests/unit/system`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/034-centralize-article-admission.md
- **Category**: bug
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

Dispatcher task exceptions are logged, but the task list loses collector/source identity and failed groups contribute nothing to `sources_processed` or `errors_encountered`. The final summary can therefore report zero work or an inflated success rate after real source failures. Partial collection needs explicit, attributable failure results.

## Current state

- `news_collector/collectors/dispatcher.py:136-170` groups sources and appends bare awaitables.
- Lines 172-188 gather exceptions and log only the exception object; the group/type/source IDs are no longer available.
- Lines 175-203 initialize counters and add only successful result summaries, so failed groups disappear.
- Lines 205-213 calculate success rate from an undercounted `sources_processed` value and may omit the field entirely when it is zero.
- `tests/unit/collectors/test_dispatcher.py:36-45` contains a placeholder async test with `pass` and no merge/failure assertions.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Dispatcher tests | `.venv/bin/python -m pytest tests/unit/collectors/test_dispatcher.py -q` | complete success/failure matrix passes; no placeholder test |
| System tests | `.venv/bin/python -m pytest tests/unit/system -q` | downstream summary/report tests pass |
| Static checks | `make lint && make typecheck` | exit 0 |
| Full tests | `make test` | exit 0 |

## Scope

**In scope**: typed task metadata/result, missing/unknown collector handling, exception attribution, summary counts/rates, health/metrics emission, and dispatcher/system tests.

**Out of scope**: retry strategy, collector implementation fixes, fail-fast whole-cycle behavior, admission rules, or changing collector result payloads outside an additive failure-details field.

## Git workflow

- Branch: `advisor/040-dispatcher-failure-accounting`.
- Commit example: `fix(collectors): account for failed dispatch groups`.

## Steps

### Step 1: Replace the placeholder with a behavior matrix

Build dispatcher instances without real collector construction and inject async/sync fakes. Cover all-success, one exception plus success, malformed result, missing collector, unknown configured type, empty input, and all-failed. Assert exact per-source details and totals.

**Verify**: the new tests expose current undercount/missing identity before implementation; no test body contains `pass`.

### Step 2: Carry task identity through gather

Create a small typed dispatch item/result containing collector type, sorted source IDs, and awaitable/outcome. Zip metadata with gathered outcomes deterministically. For exceptions, emit one structured failure detail per affected source with stable reason code and sanitized exception class/message; log collector type, source IDs, session, and trace.

**Verify**: a failing HTML group is attributed to exactly its source IDs and does not contaminate successful RSS details.

### Step 3: Make summary invariants total

Define `sources_requested`, `sources_processed`, `sources_succeeded`, `sources_failed`, `articles_found`, `articles_saved`, `errors_encountered`, and `success_rate_percent` for every return, including empty/all-failed. Count each requested source exactly once. Treat malformed results/missing collectors as failures.

**Verify**: table tests assert `requested == succeeded + failed`, rate is 0-100, and all fields exist on every outcome.

### Step 4: Connect health and telemetry

Report group/source failures to the injected health tracker/metrics interface through its existing methods. Telemetry failure must be logged but must not replace the collection result. Keep full exceptions out of end-user payloads.

**Verify**: mock health tracker receives one event per failed source with trace/session correlation; telemetry exception leaves correct dispatcher summary.

## Test plan

- Async and thread-wrapped collector success/failure/malformed results.
- Mixed group attribution and deterministic merging.
- Missing/unknown type policy and empty inputs.
- Summary invariant property/table tests and health tracker failures.

## Done criteria

- [ ] Every requested source is represented exactly once in success/failure accounting.
- [ ] Exceptions retain collector/source/session/trace identity.
- [ ] Summary fields and success rate are always present and mathematically consistent.
- [ ] Placeholder dispatcher test is replaced by real coverage.
- [ ] Full backend checks pass.

## STOP conditions

- Stop if downstream contracts forbid additive failure detail; keep details internal and update only existing counters pending contract review.
- Stop if unknown collector fallback is an externally promised behavior; test/document it rather than silently changing to rejection.
- Stop if plan 034 changes collector boundary outputs; rebase the test fixtures first.

## Maintenance notes

New collector types need a dispatcher matrix case. Partial success is acceptable only when failed sources remain visible and counted.
