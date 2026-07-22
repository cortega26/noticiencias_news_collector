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
   **Review correction**: the first implementation conflated two
   different things under this one fallback check (`ctype not in
   self.collectors`) — a genuinely unknown type string (the case this
   decision is about) and a *known* type (`headless`, `reddit`, etc.)
   whose collector simply failed to initialize. Both silently rerouted
   to `rss`, which meant the new `collector_unavailable` attribution
   (decision 3) could only ever fire in the total-wipeout case (every
   collector missing, including `rss` itself) — not the realistic
   motivating scenario this spec's own "Discovered prior state" section
   names (`headless` missing while `rss` still works). Fixed by adding
   `_KNOWN_COLLECTOR_TYPES` (the exact set `create_collector()`
   recognizes) so only a *genuinely unrecognized* string falls back to
   `rss`; a known-but-uninitialized type now stays grouped under its own
   name and correctly reaches `collector_unavailable`.
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
6. **Reconciliation against the requested set** (revised after review —
   this decision originally called the case below an explicit non-goal;
   the review correctly flagged that as contradicting Done Criterion #1,
   "every requested source represented exactly once," which the plan
   states as a hard requirement, not an optional extension). If a child
   collector's own returned dict is *valid* but its `source_details`
   sub-map omits an entry for one of the sources assigned to it (a bug
   *inside* that collector, not a dispatch-level failure), the omitted
   source used to vanish silently — not counted succeeded, not counted
   failed, absent from `source_details` — breaking
   `succeeded + failed == requested`. Fixed with a reconciliation pass
   after the merge loop: any `sources_config` key still missing from
   `final_results["source_details"]` is backfilled as a failure (reason
   `child_source_missing`) via the same `_attribute_dispatch_failure`
   helper. The mirror direction (a child reporting a foreign/extra sid
   never requested) is filtered out at merge time with a logged warning,
   so `source_details` — and therefore `succeeded`/`failed` — always
   reconciles exactly against `sources_config`, in both directions.
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

## Follow-up fixes from the ~20-iteration subagent review

A fresh subagent reviewed this plan's spec and implementation against
the real code (not just the spec's own narrative) and found two real
bugs, both confirmed by empirical reproduction, not just re-reading
prose:

1. **`collector_unavailable` was effectively dead code for its own
   motivating scenario.** The grouping loop's `if ctype not in
   self.collectors: ctype = "rss"` fired for *any* unavailable type —
   so a known type like `headless` failing to initialize (while `rss`
   still worked) silently rerouted to `rss` instead of ever reaching the
   `collector_unavailable` branch; that branch could only trigger in the
   rare total-wipeout case (every collector including `rss` missing).
   Reviewer reproduced this directly with `dispatcher.collectors.pop("headless")`
   while `rss` stayed present. **Fixed**: added `_KNOWN_COLLECTOR_TYPES`
   (the exact set `create_collector()` recognizes) so the silent
   rss-fallback only applies to a genuinely unrecognized type string; a
   known-but-uninitialized type now stays grouped under its own name and
   correctly reaches `collector_unavailable`. New test:
   `test_dispatcher_known_type_uninitialized_collector_not_rerouted_to_rss`
   (confirmed failing against the pre-fix code, then passing).
2. **The "structural invariant" claim was false** when a child
   collector's own valid-dict result omitted one of its assigned
   sources from its own `source_details` sub-map — that source vanished
   with no entry anywhere, silently breaking `succeeded + failed ==
   requested`. This directly contradicted design decision 6, which had
   called the scenario an explicit non-goal, while Done Criterion 1
   ("every requested source represented exactly once") required exactly
   this. **Fixed**: added a reconciliation pass after the merge loop
   that backfills any `sources_config` key still missing from
   `source_details` as a failure (reason `child_source_missing`), plus
   the mirror fix — a child reporting a foreign/unrequested sid is now
   filtered out (with a logged warning) instead of inflating the counts.
   New tests: `test_dispatcher_child_source_details_omission_is_backfilled_as_failure`,
   `test_dispatcher_foreign_source_id_from_child_is_dropped_not_counted`
   (both confirmed failing against the pre-fix code, then passing).

Everything else the reviewer checked — the `SourceHealthTracker` call
signatures/argument order, the `error`/`error_message` key-mismatch fix,
no double-attribution/cross-group collision risk, downstream-consumer
compatibility (`reporter.py`, `pipeline_e2e.py`, `scoring/coordinator.py`
all read via `.get(key, default)`), and the rest of the test matrix —
was independently confirmed correct, not just trusted from the spec's
own prose.

- [x] Re-ran `pytest tests/unit/collectors/test_dispatcher.py tests/unit/system tests/unit/collectors -q`
      → 127 passed (was 102).
- [x] Re-ran the full-suite regression with the memory-watchdog
      discipline → 1236 passed (was 1233), same 13 pre-existing
      failures, no new ones, 26.98s.
- [x] `make lint`/`black`/mypy clean after the follow-up.
