# Spec: Plan 040 — Account for every collector-dispatch outcome

## Goals

Per `plans/040-account-for-dispatcher-failures.md` (authoritative for
scope/STOP conditions): every requested source must be represented
exactly once in success/failure accounting, dispatcher-level exceptions
must retain source/collector identity, summary fields must be always
present and mathematically consistent, and health/telemetry must receive
group/source failures without ever replacing the collection result.

## Discovered prior state (before this spec was written)

An earlier part of this same session already committed
`f64466c "fix(dispatcher): attribute failed tasks with source identity"`
against this plan, but `plans/README.md` was never updated (still showed
TODO) and no `plans/040/spec.md`/`todo.md` existed — a tracking gap this
spec closes. That commit did real, correct work:
- `task_metadata` dict carries `collector_type`/`source_ids` alongside
  each gathered task, zipped back up by index after `asyncio.gather`.
- A whole-group exception now increments `errors_encountered` and
  `sources_processed` by the group's source count and creates one
  `source_details[sid] = {"success": False, "error": ..., "collector_type": ...}`
  entry per affected source, instead of silently vanishing.
- 2 new tests (`test_dispatcher_failed_task_attributed_with_source_identity`,
  `test_dispatcher_partial_failure_mixed_results`) replaced the plan's
  placeholder `pass` test.

This closes part of Step 1 and part of Step 2. **Not done**, confirmed by
re-reading `news_collector/collectors/dispatcher.py` end to end against
each of the plan's own Verify lines:

- **Step 1 (behavior matrix)**: still missing malformed-result, missing-
  collector, unknown-configured-type, empty-input, and all-success cases
  that exercise the real merge path (the one "all success" test mocks the
  whole method away).
- **Step 2 (task identity)**: per-source failure entries use a free-text
  `"error"` key, not a stable reason code, and no sanitized exception
  class. The log call omits `session_id`/`trace_id` entirely, so trace
  correlation is lost for dispatcher-level failures.
- **Step 3 (summary invariants)**: `sources_requested`, `sources_succeeded`,
  `sources_failed` do not exist. `success_rate_percent` is only added
  `if sources_processed > 0`, so it is absent on empty/all-dropped input
  — violating the plan's own Verify line ("all fields exist on every
  outcome"). Two real gaps found by direct code reading:
  1. `collector = self.collectors.get(ctype); if not collector: continue`
     (`dispatcher.py:153-155`, current numbering) — when a collector
     type failed to initialize (e.g. `headless` without playwright), its
     entire source group vanishes: not counted anywhere, no
     `source_details` entry, no error. This is precisely the "missing
     collector" case the plan names.
  2. `if not isinstance(res, dict): continue` (`dispatcher.py:209`) — a
     non-exception, non-dict result (a malformed return from a child
     collector) is silently dropped the same way.
- **Step 4 (health/telemetry)**: `CollectorDispatcher` never calls any
  `health_tracker` method itself — it only forwards the tracker object to
  child collectors (`dispatcher.py:88-96`), which never run their own
  per-source loop for a source that failed at the *dispatch* level
  (group exception before the child's own code executes). No
  `health_tracker.record_*` call happens for exactly the failures this
  plan targets. Separately, a real pre-existing bug: the dispatcher's
  per-source failure dict uses key `"error"`
  (`dispatcher.py:205`), but `news_collector/system/observability.py:99`
  (`record_collection_outcomes`, the function that feeds
  `MetricsReporter.record_error`) reads `result.get("error_message", "unknown")`
  — a key-name mismatch that means **every dispatcher-attributed failure
  today already silently reports `"unknown"` to the metrics system**,
  discarding the real error text. Confirmed via `Explore` recon: the
  existing per-collector convention elsewhere in the codebase (e.g.
  `rss_collector.py:342,355`) already uses `error_message`, so the
  dispatcher was the outlier, not the target.

## Design decisions

1. **Reason codes** (Step 2): three stable strings —
   `"dispatcher_task_exception"` (whole-group `asyncio.gather` exception),
   `"collector_unavailable"` (collector type failed to initialize/was
   never registered), `"malformed_result"` (child collector returned a
   non-dict, non-exception value). All three are dispatcher-level
   failures with no specific collector-internal stage, so they use
   `FailureStage` value `"unknown"` (`news_collector/diagnostics.py:15-22`
   — already a legal, existing value reserved for exactly this: no other
   `FailureStage` fits a failure that happens *before* a collector's own
   fetch/parse/validate/apply-filters/storage stages run).
2. **Sanitized exception fields**: `error_class = type(exc).__name__`,
   `error_message = str(exc)` (matches the existing `error_message` key
   convention other collectors already use and that `observability.py:99`
   already reads — fixes the key-mismatch bug rather than adding a
   second, redundant key). No traceback/repr in `source_details` (stays
   out of end-user payloads per Step 4's own instruction); the full
   exception with traceback continues to go to the structured log call
   only (`logger.opt(exception=res)`), now additionally including
   `session_id`/`trace_id` for correlation.
3. **Missing-collector and malformed-result handling** (Step 3): both are
   now attributed exactly like a dispatch exception — one
   `source_details` entry per affected source_id with `success: False`,
   a reason code, and counted in `sources_failed`/`errors_encountered`.
   Neither goes through `asyncio.gather` (a missing collector never
   produces a task at all; a malformed result already came back from
   `gather`), so both are handled inline via a shared helper
   (`_attribute_dispatch_failure`) instead of duplicating the
   exception-branch logic three times.
4. **Unknown-`collector_type` fallback (STOP condition)**: recon (an
   `Explore` subagent pass) confirmed this fallback is **not** externally
   promised — no test, no doc, no contract exercises or names it; no
   real source config in `news_collector/config/sources.yaml` ever
   supplies an unrecognized type (dead in production); `docs/AGENTS.md`'s
   own LAW-B7 flags "hidden fallback behavior that changes ... semantics"
   as a reject-on-review anti-pattern, which is what an untested silent
   coercion is. Per the plan's own STOP instruction ("test/document it
   rather than silently changing to rejection"), the correct action is
   the first branch of that instruction: **keep the existing fallback
   behavior unchanged, but add an explicit test that locks it in**,
   rather than silently switching to rejection (which would be an
   undiscussed behavior change, not asked for by the plan, and not
   forced by any Done Criterion). This is a deliberate, documented
   choice, not an oversight.
5. **Summary field semantics** (Step 3): `sources_requested = len(sources_config)`
   (computed once, up front). `sources_succeeded`/`sources_failed` are
   *derived from the final merged `source_details` dict* (one pass, `success`
   truthy vs not) rather than accumulated incrementally across three
   different code paths (group-exception, missing-collector, malformed-
   result, successful-merge) — this guarantees
   `sources_succeeded + sources_failed == len(source_details) == sources_requested`
   as a structural invariant rather than an accounting hope. `sources_processed`
   (the pre-existing field name real consumers already read defensively via
   `.get(..., default)` — confirmed via recon: `reporter.py`, `pipeline_e2e.py`,
   `utils/logger.py`) is kept, now always equal to `sources_requested`,
   for backward compatibility rather than removed. `errors_encountered`
   keeps its existing broader meaning (dispatch-level failures **plus**
   any error count a successful group's own result reports for its
   internal sub-processing) since changing that semantic would affect
   existing successful-path consumers for no benefit this plan asks for.
   `success_rate_percent` is now unconditionally present, defaulting to
   `0.0` when `sources_requested == 0` (empty input) rather than being
   omitted.
6. **Explicit non-goal**: if a child collector's own returned dict is a
   *valid* dict but its own `source_details` sub-map omits an entry for
   one of the sources the dispatcher assigned to that group (a bug
   *inside* a child collector, not a dispatch-level failure), the
   dispatcher does not backfill a synthetic entry for it. The plan's
   Step 1 Verify list names "malformed result" (the whole return value
   being unusable) and "missing collector," not "child collector under-
   reports one source within an otherwise-valid result" — treating that
   as in-scope would mean re-validating every child collector's own
   internal contract from the dispatcher, which is a different, larger
   change not asked for here.
7. **Health tracker wiring** (Step 4): guarded by `if self.health_tracker:`
   and wrapped in `try/except Exception` (log the telemetry failure,
   never let it change or abort the collection result — the plan's own
   Step 4 Verify line). For each dispatch-level failure, call
   `record_attempt(source_id)` then `record_failure(source_id, "unknown", reason, details)`
   — mirroring the attempt-then-outcome pattern every other collector
   already follows (confirmed via recon: `rss_collector.py` etc. always
   call `record_attempt` before `record_success`/`record_failure`), so a
   dispatch-level failure doesn't leave `SourceHealthTracker` with a
   failure recorded against a source that was never marked attempted.

## Verification

- [x] New/expanded tests in `tests/unit/collectors/test_dispatcher.py`
      cover: all-success (through the real merge path, not mocked away),
      one-exception-plus-success (existing), malformed result, missing
      collector, unknown configured type (fallback-to-rss, now explicitly
      locked in), empty input, all-failed (existing).
- [x] `sources_succeeded + sources_failed == sources_requested` asserted
      as a table-test invariant across every case above, including
      empty input (0 == 0 + 0).
- [x] `success_rate_percent` present (a `float`, 0-100 inclusive) on
      every case, including empty input (`0.0`).
- [x] A failing HTML group's exception does not contaminate a succeeding
      RSS group's `source_details` (existing
      `test_dispatcher_partial_failure_mixed_results`, kept).
- [x] Mock `health_tracker` receives `record_attempt` + `record_failure`
      calls for dispatch-level failures with `stage="unknown"` and the
      right `reason`; a health-tracker method that itself raises leaves
      the returned collection summary correct (not aborted).
- [x] `error_message` (not `error`) is the key used in `source_details`
      for dispatch-level failures, matching `observability.py`'s existing
      read — closing the metrics key-mismatch bug — plus a new
      `error_class` field.
- [x] `make lint && make type` clean; `pytest tests/unit/collectors/test_dispatcher.py tests/unit/system -q`
      and a full-suite regression run (memory-watchdog discipline, per
      the plan-036 lesson) both green, same pre-existing failures as
      baseline.
