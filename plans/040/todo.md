# Plan 040 TODO

## Pre-work
- [x] Read `plans/040-account-for-dispatcher-failures.md` in full.
- [x] Ran the plan's own drift check
      (`git diff --stat e43bd30..HEAD -- news_collector/collectors/dispatcher.py ...`)
      — discovered prior commit `f64466c` already did real Step 1/2 work
      this session, but `plans/README.md` and `plans/040/*` were never
      updated. Read the current `dispatcher.py` and `test_dispatcher.py`
      in full to establish exactly what's done vs. remaining (see
      spec.md's "Discovered prior state").
- [x] Recon via subagent: `SourceHealthTracker`'s real method signatures
      (`diagnostics.py`), confirmed no separate dispatcher-level metrics
      interface exists (`MetricsReporter` is reached indirectly via
      `source_details` → `observability.py`), found the real
      `error`/`error_message` key-mismatch bug, confirmed the unknown-
      collector-type fallback is untested/undocumented/dead-in-production
      (not externally promised), confirmed no downstream consumer breaks
      if `success_rate_percent`/new fields are always present.

## Step 1: Expand the behavior matrix
- [x] Add: all-success case exercised through the real merge path (not
      mocked away like `test_dispatcher_collect_all`).
- [x] Add: malformed result (child collector returns e.g. `None` or a
      non-dict).
- [x] Add: missing collector (a group's `ctype` has no entry in
      `self.collectors`, e.g. simulating headless-without-playwright).
- [x] Add: unknown configured `collector_type` in a source's own config
      (locks in the existing fallback-to-rss behavior deliberately, per
      the STOP-condition design decision in spec.md).
- [x] Add: empty `sources_config` input.
- [x] Keep existing: one-exception-plus-success, all-failed.
- [x] Table-test invariant across all cases:
      `sources_succeeded + sources_failed == sources_requested`,
      `0 <= success_rate_percent <= 100`, all summary fields present.

## Step 2: Reason codes + sanitized exception fields + trace correlation
- [x] Replace free-text `"error"` key with `"error_message"` (fixes the
      real key-mismatch bug vs. `observability.py:99`) and add
      `"error_class"` (`type(exc).__name__`).
- [x] Add a stable `"reason"` field:
      `dispatcher_task_exception` / `collector_unavailable` /
      `malformed_result`.
- [x] Extend the structured log call to include `session_id`/`trace_id`.

## Step 3: Total summary invariants
- [x] `sources_requested = len(sources_config)`, computed up front.
- [x] Handle missing-collector groups: attribute every source_id in that
      group as a failure (reason `collector_unavailable`) instead of
      `continue`-skipping them.
- [x] Handle malformed (non-dict, non-exception) results: attribute every
      source_id in that task's group as a failure (reason
      `malformed_result`) instead of `continue`-skipping them.
- [x] Derive `sources_succeeded`/`sources_failed` from the final merged
      `source_details` dict in one pass (not accumulated per-branch) so
      the requested/succeeded/failed invariant is structural, not hoped-for.
- [x] `sources_processed` kept (backward compat for existing consumers),
      now always equal to `sources_requested`.
- [x] `success_rate_percent` always present; `0.0` when
      `sources_requested == 0`.

## Step 4: Health tracker + metrics wiring
- [x] For each dispatch-level failure (all 3 reasons), call
      `health_tracker.record_attempt(source_id)` then
      `health_tracker.record_failure(source_id, "unknown", reason, details)`,
      guarded by `if self.health_tracker:` and wrapped so a telemetry
      exception is logged but never changes/aborts the returned summary.
- [x] Confirm (via the `error_message` key fix in Step 2) that
      `news_collector/system/observability.py`'s existing
      `record_collection_outcomes` now correctly forwards the real error
      text to `MetricsReporter.record_error` instead of `"unknown"` —
      no new metrics wiring needed in the dispatcher itself (recon
      confirmed no separate dispatcher-level metrics interface exists).

## Verification
- [x] `pytest tests/unit/collectors/test_dispatcher.py -q` — full matrix
      green, no placeholder tests.
- [x] `pytest tests/unit/system -q` — unaffected.
- [x] `make lint && make type` clean.
- [x] Full-suite regression run with memory watchdog (per the plan-036
      lesson) — same pre-existing failures as baseline, no new ones.
- [x] `plans/README.md` row for 040 updated TODO → DONE (all 4 steps +
      Done Criteria genuinely met, unlike 048's STOP case).
- [x] Root `spec.md`/`todo.md` updated.
- [x] Commit.
