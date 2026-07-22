# Todo: Implement the remaining plans (see spec.md)

Previous pass (plans 001–016) is complete and archived under `plans/archive/`;
this file now tracks the current pass over the 18 remaining plans.

## Plan 033 — Make configuration refresh live (DONE)

- [x] Phase 1: `RuntimeConfigSnapshot`, `get_runtime_config()`,
      `refresh_runtime_config()` atomic rebuild + tests (`tests/unit/config/`,
      23 passing).
- [x] Phase 2.1–2.5: migrate base/html/reddit/rss collectors + rate_limit_utils.
- [x] Phase 2.6–2.21: migrate remaining consumers (scoring x4, storage x3,
      infrastructure x2, enrichment, system x3, utils/logger, contracts,
      logic/workflows). Also fixed two decorator-baked tenacity retry
      policies (requests_client.py, http_client.py) that would otherwise
      have stayed stale despite the migration, and 2 stale test mocks that
      patched the old by-value config names.
- [x] Phase 3: Refinery truthfulness — `save_toml_config()` now validates
      (both pydantic shape and business rules) before writing to disk,
      returns `{success, version, changed_keys, restart_required_keys}`,
      and every "Guardar" button in admin_panel.py surfaces that truthfully
      via a shared `render_save_result()` helper.
- [x] Phase 4: import audit clean (only intentionally-live ALL_SOURCES
      remains), black/ruff/mypy show zero new findings vs. pre-existing
      baseline, full test run (`pytest tests --ignore=tests/e2e_pipeline`)
      matches the 13 pre-existing failures exactly with 29 more tests
      passing (new coverage), `plans/README.md` updated to DONE.
- [x] Commit plan 033 (f14862b, d5faba4 fix-up after subagent review caught
      a return-type regression).

## Plan 021 — Rebuild the publication callback contract (PARTIAL)

- [x] Recon: confirmed Steps 1-5 need coordinated backend+frontend work
      (see `plans/021/spec.md`) — landing backend-only would strand real
      callbacks, a regression not progress.
- [x] Step 0 (not an original plan step, required by its own STOP
      condition): fixed refinery_id identity resolution in
      `refinery_engine.py` (`_resolve_article_identity`).
- [x] Committed (3e3408e), `plans/README.md` updated to PARTIAL with full
      handoff including a dedup-guard hazard for whoever does Step 2.

## Plan 023 — Connect and harden the report pipeline (PARTIAL)

- [x] All 5 steps implemented + tested in the frontend repo (contract
      mapping, honest form behavior, request bounds, durable-sink
      tracking, KV rate limiting/idempotency, CI gates).
- [x] Committed in both repos (frontend dbb12db, backend index b8d84e0).
- [ ] Remaining: operator provisions R2 bucket + RATE_LIMIT_KV namespace,
      then flips `config.yaml`'s endpoint — see
      `../noticiencias/docs/report-pipeline-setup.md`.

## Plan 046 — Prove and automate production migrations (PARTIAL)

- [x] Alembic-first SQLite test coverage: every legacy revision + empty DB →
      head, downgrade→re-upgrade roundtrips (for revisions with a complete
      downgrade), model/schema parity, single linear history
      (`tests/test_database_migrations.py`, 18 tests).
- [x] Read-only revision guard: `news_collector/storage/migration_guard.py` +
      `scripts/check_migration_revision.py`, 6 tests, verified to never
      mutate schema in any branch.
- [x] Corrected stale docs/comments: `database.py` docstring,
      `scripts/migrate.py` comment, full rewrite of
      `docs/database_deployment.md` (contradictions + garbled text fixed).
- [x] Step 1 STOP: no discoverable production deployment topology anywhere
      in the repo — reported, not invented.
- [x] Second STOP found empirically: PostgreSQL is not usable yet (no driver
      in any lockfile, dead `docker-compose.yml` env vars for
      `refinery`/`collector`, host-absolute paths in committed
      `config.toml`) — documented as its own follow-up, not patched around.
- [x] Committed, `plans/README.md` updated to PARTIAL with full handoff.
- [x] Follow-up (caught by ~20-iteration subagent review): unified
      `alembic/env.py`'s own third, independently-drifted URL-builder onto
      `build_database_url()` — its postgresql branch interpolated
      user/password into an unescaped f-string, unlike `URL.create()`.
      Verified the fix (percent-encoding a password with `@:/%`) without
      needing psycopg2. Committed separately (4c66ec1).

## Plan 034 — Centralize article admission (DONE)

- [x] Step 1: characterized current behavior first — confirmed by reading
      the code that the old policy was dead (zero real callers) before
      writing fixtures against it (`tests/unit/collectors/test_admission.py`,
      9 tests).
- [x] Step 2: typed `evaluate_admission()` +  `AdmissionDecision`/
      `AdmissionReason` (`news_collector/collectors/admission.py`) — pure,
      structural-only (title/content length), URL scheme left to
      `CollectorArticleModel`'s existing `AnyHttpUrl` type.
- [x] Step 3: wired into `BaseCollector._filter_and_save_articles` once;
      deleted the dead method and RSS's weaker override; 4 integration tests
      prove rejected articles cause zero duplicate-lookup/zero-insert calls
      (`tests/unit/collectors/test_admission_boundary.py`).
- [x] Step 4: per-reason health-tracker counters added; deliberately did
      NOT unify `basic_scorer`'s clickbait list with config's
      `penalty_keywords` — the two lists partially overlap (not fully
      diverge, as an earlier draft incorrectly claimed; corrected after
      subagent review) but each still has exclusive terms, so unifying
      would silently reweight scores (out of scope). Documented both as
      intentionally separate.
- [x] Full regression gates clean (1176 passed, same 13 pre-existing
      failures, same pre-existing lint/type baseline). Committed,
      `plans/README.md` updated to DONE.
- Noted, not fixed (out of scope): `canonicalize_url()` silently coerces
  non-http(s) URL schemes to https instead of rejecting them; `penalty_keywords`
  config is now fully unconsumed pending a deliberate future decision. See
  `plans/archive/034/spec.md`.

## Plan 038 — Decouple telemetry writes and cache Refinery read models (DONE)

- [x] Step 1: interleaving equivalence test locks in exact current
      arithmetic before refactor; `scripts/benchmark_metrics.py` proves
      ≤25 commits for 1000 events (was 1000) with byte-identical aggregates.
- [x] Step 2: `EnrichmentMetricsStore.create_isolated()` replaces the
      `_initialized`-mutating test hack; 20+ existing callers of the
      module-level singleton needed zero changes.
- [x] Step 3: buffered/flushed writes, replaying events through the same
      pure per-event arithmetic (not a coalesced sum/count, which a
      pre-implementation check found would silently produce a *different*,
      wrong average — see spec.md's worked counter-example). Rollback on
      flush failure never drops or corrupts the buffer. Guaranteed flush
      wired into `base_collector.py`'s real collection-cycle boundary,
      after confirming `scripts/run_collector.py` (the actual entrypoint)
      never calls the existing `System.shutdown()` hook.
- [x] Full regression gates clean (1179 passed, same 13 pre-existing
      failures, same pre-existing lint/type baseline — two new mypy errors
      this plan's own changes caused were fixed, not left). Committed,
      `plans/README.md` updated to PARTIAL (at the time).

### Steps 4-5 (resumed 2026-07-22, operator-authorized "build what I can unblock myself")

- [x] Built the missing `.venv-refinery` test-running convention from
      scratch: `pytest` installed unpinned (mirrors the main venv's
      ruff/mypy/black/isort pattern — outside the hash-pinned
      `requirements-refinery.lock`), new `make test-refinery` target, new
      `tools/ci/pytest_refinery.toml` (`testpaths = ["tests_refinery"]`,
      deliberately outside the main suite's `testpaths = ["tests"]` so
      `make test` never tries to collect it — the main `.venv` has no
      `streamlit` at all).
- [x] Wrote the `AppTest` characterization test FIRST, before any caching
      code existed, per the plan's own harness-first discipline. Confirmed
      empirically: `REFINERY_UI_UNSAFE_ALLOW=1` (the app's own existing
      dev/test bypass) clears the auth gate; Streamlit tabs execute every
      rerun regardless of visual selection, so Tab 4's real metrics
      (`Total Artículos (30d)`, `Score Promedio`, `Fuentes Activas`) are
      directly assertable; proved the genuinely uncached baseline (DB
      re-queried on every independent rerun) before writing a line of
      caching code.
- [x] Caught a real test-writing bug: `mock.patch.object(cls, name,
      wraps=cls.name)` doesn't bind `self` for an unbound method
      reference (`MagicMock` isn't a descriptor) — call_count still
      increments even though the wrapped call raises internally, which
      would make a naive assertion pass while the real code path never
      actually ran. Fixed with a plain function wrapper (a real
      descriptor); documented inline so it isn't rediscovered.
- [x] Extracted `apps/refinery/analytics_read_model.py`
      (`build_analytics_read_model`) — pure, zero `streamlit` import,
      behavior-preserving (same 4 queries, same derivation formulas as
      the original inline Tab 4 code). 4 unit tests under the main
      `.venv`, no Streamlit needed
      (`tests/decompose_refinery/test_analytics_read_model.py`).
- [x] Wired `st.cache_resource` (DB resource, safe given
      `DatabaseManager`'s existing `check_same_thread=False`) +
      `st.cache_data(ttl=60)` (read model) into Tab 4, plus a manual
      refresh button (`.clear()`) and a freshness caption. Rendering
      logic (metrics/charts/fallback messages/outer try-except)
      otherwise untouched — a deliberately behavior-preserving edit.
- [x] Proved the caching actually works via the harness, not by
      inspection: `test_second_rerun_reuses_cache_and_does_not_requery`
      (2 independent AppTest runs, DB query count stays at exactly 1),
      `test_manual_refresh_button_forces_a_fresh_query` (clicks the real
      button, not a direct `.clear()` call), `test_a_visible_query_error_does_not_show_stale_data_as_current`
      (forces a query exception, confirms it surfaces visibly instead of
      masking with a stale cached value — directly answering Step 5's own
      concern). 6 tests total in `tests_refinery/`, all green via `make
      test-refinery`.
- [x] Full main-suite regression (memory-watchdog discipline): 1252
      passed, same 13 pre-existing failures, no new ones. `black`/`ruff`
      clean; `mypy` clean on the new module.
- [x] `plans/README.md` updated PARTIAL → DONE — all 5 Done Criteria now
      genuinely met.

## Plan 036 — Bound scoring memory, prompts, and concurrency (DONE)

- [x] Step 1: `page_size`/`max_prompt_items`/`max_prompt_chars`/
      `cycle_item_budget` added to `ScoringConfig`, all rejecting
      zero/negative/excessive values; `workers` gained an `le=64` guard and
      became genuinely used (was a dead-code expression before).
- [x] Step 2: `ArticleCursor`/`ArticlePage` + `get_pending_articles_page`/
      `get_completed_articles_for_rescoring_page` — additive, keyset
      `(collected_date, id)` ordering with a tuple-comparison continuation
      predicate (a naive single-column cursor was proven, via a falsifier
      test, to skip every row after a tie). No schema index/migration
      needed — sort works fine without one; noted as a perf follow-up only.
- [x] Step 3: `ScoringCoordinator.execute()` rewritten to page one source
      at a time, cross-source `seen_ids` dedup, per-page persist,
      persistence-failure surfaced as `success: False` +
      `stop_reason: "persistence_failed"` + a resumable `failed_cursor` —
      never unconditional success. Extracted `_run_source`/`_process_page`/
      `_CycleState`/`_PageResult` to keep cyclomatic complexity under the
      ruff C901 threshold.
- [x] Step 4: confirmed via direct code-reading (STOP condition 3) that
      `CognitiveScorer`'s prompt has no cross-article ranking/comparison
      and its response is parsed purely per-`item_index` — chunking is
      semantically safe. Chunked `articles_to_process` by item-count/
      estimated-char bounds preserving order; one chunk's total failure
      falls back to heuristic for only that chunk. Coordinator's fallback
      path replaced unbounded `asyncio.gather` with a semaphore bounded by
      the (now-live) `workers`/`scoring_workers` config.
- [x] Step 5: workload telemetry (`duration_sec`, `pages_processed`,
      `max_fallback_inflight_observed`, `committed`, `failed`,
      `stop_reason`, plus the scorer's own `llm_calls`/`chunks_processed`/
      `cache_hits`/`prompt_chars_sent` when exposed) — no article content.
      `scripts/benchmark_scoring.py`: 1000 synthetic articles (incl.
      timestamp ties), asserts page-size and fallback-concurrency bounds
      hold; exit 0/PASS.
- [x] A full-suite regression run (not just the targeted scoring tests)
      caught a real infinite-loop regression: 3 tests elsewhere
      (`test_scoring_isolation.py` x2, `test_d1_pipeline_boundaries.py` x1)
      mocked the old unpaged DB methods, so the coordinator's new
      `get_pending_articles_page` call returned an unconfigured
      `MagicMock` that was never falsy/`None` — an infinite loop that grew
      `unittest.mock`'s internal state without bound (saw ~97GB RSS before
      killing it). Confirmed via `git stash` A/B that this was caused by
      this plan's changes (baseline clean at 39s; plan-036 changes
      reproduced the same growth+hang at the same ~81% point both times).
      Fixed all 3 fixtures plus a related `AsyncMock`-scorer issue with the
      new `get_cycle_telemetry` hasattr check. Full suite re-run: 38s,
      1217 passed, same 13 pre-existing failures, no hang, normal memory.
      See `plans/archive/036/spec.md` for the full narrative.
- [x] Full regression gates clean; committed, `plans/README.md` updated to
      DONE.

## Plan 037 — Make bulk article persistence set-based (DONE)

- [x] Recon + advisor consult (HIGH risk, L effort): read
      `save_articles_bulk`/`_assign_cluster`/`articles_exist`/`save_article`/
      `_revalidate_cluster`; confirmed `SessionLocal` is `autoflush=False`.
- [x] Two empirical oracle probes before any code change: (1) current bulk
      code does NOT join two near-duplicate articles submitted in the same
      batch (autoflush artifact — different cluster_ids, dup_conf=0.0
      both); (2) `save_article()` called twice (the true "sequential"
      oracle) DOES join them, back-mutating the matched candidate's
      confidence to a shared, non-zero value. Conclusion (confirmed with a
      second advisor consult): building the in-memory same-batch candidate
      map is the task Step 4 asks for, not a semantics change to avoid —
      the plan's own Done Criteria targets single/bulk equivalence against
      the single-save oracle, not against current (gapped) bulk behavior.
- [x] Step 1: characterization fixtures — SELECT-count instrumentation
      (baseline 561 for 100 articles) and the load-bearing single-save-vs-
      batch cluster parity test, confirmed failing against pre-refactor
      code first.
- [x] Step 2: `_prepare_bulk_row()`/`_dedupe_prepared_rows()` — normalize
      once, in-batch dedup extended to content hash (not just URL, a real
      gap Step 2 explicitly asks to close).
- [x] Step 3: `_chunked_in_lookup()`/`_filter_existing_articles()` — chunked
      `IN` prefetch reusing `articles_exist()`'s pattern.
- [x] Step 4: `_resolve_cluster_for_candidates()` (shared by single-item
      and batched paths — no drift risk), `_fetch_batch_cluster_candidates()`
      (one prefetch per bulk call across the union of needed prefixes),
      `_ClusterBatchContext` (lazy fallback, synthetic tie-break ids,
      same-batch cluster-merge propagation).
- [x] Step 5: existing atomic flush/commit/rollback structure preserved
      untouched (already re-raises, no `PendingRollbackError` risk);
      `scripts/benchmark_bulk_persistence.py` added.
- [x] SELECT count: 561 → 4 for a 100-article batch. All parity/regression
      tests green (106 storage/collector tests, full suite 1225 passed,
      same 13 pre-existing failures, no hang, normal memory — verified
      with the same memory watchdog discipline plan 036 established).
      Fixed one pre-existing test (`test_db_chunking.py`) whose fixture
      relied on the very in-batch-dedup gap Step 2 closes. Committed,
      `plans/README.md` updated to DONE.

## Plan 048 — Spike a curated multilingual topic and entity registry (PARTIAL)

- [x] Recon via subagent: `config.toml`'s `pattern_v1` block,
      `config_schema.py`'s topic/entity schema, `settings.py`'s
      normalization, `ConfigurableNLPStack` behavior end to end, and every
      real consumer — confirmed only 4 (feature scoring, topic-diversity
      reranking, serving API, image briefs); `CognitiveScorer` and
      monitoring/observability are NOT content consumers, contradicting
      the plan's own broader "monitoring" framing.
- [x] Step 1: wrote `docs/spikes/curated-enrichment-registry.md` — the
      plan's own literal Step-1 Verify target. Five-way label vocabulary,
      full consumer table, stable-ID/deprecation/cross-language-equivalence
      gap analysis, allowed-entity-label examples/non-examples per
      language, the one existing ambiguity rule (`case_sensitive` on
      `TECH`/"IA"), multi-topic 5-cap semantics, and what `general`
      actually means (residual fallback, not a curated topic).
- [x] Steps 2-6: STOPPED at the plan's own condition — "no qualified
      editorial reviewer or safe representative data" — this session has
      neither. Explicitly rejected fabricating a ≥200-record
      "two-reviewer-adjudicated" corpus with self-generated labels dressed
      as independent review (fabricated governance, not caution). Also
      did not build the Step 3 evaluator scaffold: it would only be
      runnable against the 6 existing golden examples, which the plan's
      own Step 3 Verify line disqualifies as sufficient evidence.
- [x] Wrote `docs/adr/0004-curated-enrichment-registry-spike.md`: STOP
      decision, context, consequences, 4 alternatives considered, and
      concrete next steps for whoever resumes with a real reviewer and
      corpus.
- [x] `git diff --stat` confirmed zero changes to `config.toml`,
      `config_schema.py`, `settings.py`, enrichment/scoring/reranker code,
      or the golden fixture — production behavior untouched, satisfying
      the plan's own Done Criterion. `plans/README.md` updated to
      PARTIAL, `plans/048/spec.md` + `todo.md` written.

### Follow-up (2026-07-22): operator committed to self-review

- [x] User asked (via AskUserQuestion) whether they could review the
      corpus themselves — answered yes. Documented honestly that this is
      one reviewer, not the plan's own two-independent-reviewer ask (see
      the labeling guide's "Single-reviewer limitation" section) — no
      silent downgrade of the plan's actual requirement.
- [x] Built `tests/data/enrichment_eval.jsonl`: 44-record stratified
      synthetic seed (4 languages × 6 topics + general + every
      adversarial case type named in the plan). `model_draft_topics`/
      `model_draft_entities` hold my own unreviewed guess, kept strictly
      separate from `gold_topics`/`gold_entities` (null until reviewed)
      — no fabricated gold labels.
- [x] Wrote `docs/spikes/enrichment-corpus-labeling-guide.md`: process,
      schema, corpus-growth instructions, single-reviewer limitation, and
      a real finding (below).
- [x] Built `scripts/validate_enrichment_corpus.py` (Step 2's Verify
      criterion) — 7 tests incl. negative cases (duplicate id,
      dev/heldout overlap, bad language, reviewed-with-null-gold,
      email-like text) each proving the rejection fires.
- [x] Built `scripts/evaluate_enrichment_registry.py` (Step 3) — micro/
      macro P/R/F1 for topics+entities, per-language slices,
      general/multi-label rates, latency, top FP/FN clusters,
      corpus/model-version hashes. Only scores `review_status="reviewed"`
      records; `sufficient_evidence` structurally false below 200
      reviewed. `--compare` errors rather than fabricating a comparison
      (Step 4 not built).
- [x] Real finding while self-testing: golden_articles.json's `science`
      tag depends on `content` text this corpus schema deliberately
      excludes (title+summary only) — not a bug, fixed the sanity-check
      test to isolate the scoring arithmetic instead of asserting parity
      it can't reach, documented in the labeling guide.
- [x] 12 tests total, all green
      (`tests/unit/enrichment/test_enrichment_registry_tooling.py`);
      `black`/`ruff` clean; end-to-end smoke test of both scripts passed.
- [x] Updated `plans/048/spec.md`, `plans/048/todo.md`,
      `docs/adr/0004-curated-enrichment-registry-spike.md` (in-place
      update, not a new ADR number — same decision record, updated
      status), `plans/README.md`.
- [ ] Reviewer labels records over time; Steps 4-6 remain not attempted,
      gated on a real reviewed corpus of meaningful size.

## Plan 040 — Account for every collector-dispatch outcome (DONE)

- [x] **Correction to the prior "natural stopping point" conclusion
      below**: an advisor consult after landing 048 caught that plan 040
      (P1, deps = 034 only, DONE) had been skipped over entirely — its
      only dependency was satisfied and it outranks the P2 spike just
      finished. Re-derived the startable set directly from
      `plans/README.md` instead of trusting the earlier enumeration, per
      the advisor's own instruction not to trust a terminus conclusion
      until re-checked against the README.
- [x] Ran the plan's own drift check
      (`git diff --stat e43bd30..HEAD -- news_collector/collectors/dispatcher.py ...`)
      before touching anything — discovered real prior work already
      existed on disk (commit `f64466c`, this same session, before the
      context-compaction boundary) that never made it into
      `plans/README.md` or any `plans/040/*` file. Read the current
      `dispatcher.py`/`test_dispatcher.py` end to end to establish
      exactly what was already done vs. what Steps 3-4 still needed —
      see `plans/archive/040/spec.md`'s "Discovered prior state" for the
      step-by-step gap analysis.
- [x] Recon via subagent: `SourceHealthTracker`'s real method signatures,
      confirmed no separate dispatcher-level metrics interface exists
      (`MetricsReporter` is reached indirectly through `source_details`),
      found a real pre-existing `error`/`error_message` key-mismatch bug
      (dispatcher wrote `"error"`, `observability.py` already read
      `"error_message"` — every dispatcher-attributed failure was
      silently reporting `"unknown"` to metrics), confirmed the unknown-
      collector-type fallback is untested/undocumented/dead in
      production (not externally promised, so the STOP condition's
      "test/document it rather than silently changing to rejection"
      applies: kept the fallback, added a test that locks it in, did not
      switch it to rejection).
- [x] Wrote 7 new tests (malformed result, missing collector — even the
      rss fallback target itself absent, unknown-type fallback lock-in,
      empty input, all-success through the real merge path, health-
      tracker call assertions, health-tracker-exception-safety) —
      confirmed all 8 new/changed assertions failed against the pre-fix
      code first, then implemented `_attribute_dispatch_failure()` (one
      shared helper instead of duplicating the exception/missing-
      collector/malformed-result branches three times) plus rewrote
      `collect_from_multiple_sources_async`'s merge loop: `sources_requested`
      computed up front; missing-collector and malformed-result groups no
      longer silently `continue`-skipped, both now attributed as failures;
      `sources_succeeded`/`sources_failed` derived in one final pass over
      merged `source_details` (structural invariant, not accumulated
      per-branch); `success_rate_percent` always present (`0.0` on empty
      input); `error_message`/`error_class`/`reason` fields added, fixing
      the key-mismatch bug; `SourceHealthTracker.record_attempt`/
      `record_failure` now called for every dispatch-level failure,
      guarded so a telemetry exception never changes the returned
      summary; `session_id`/`trace_id` added to the structured log calls.
- [x] `make lint`/mypy clean (fixed 2 new mypy errors from variable-name
      reuse across the function, `black` reformat applied); full-suite
      regression with the memory-watchdog discipline (per the plan-036
      lesson): 1233 passed, same 13 pre-existing failures as this
      session's established baseline, no new failures, 24.95s, no hang.
      `plans/README.md` updated TODO → DONE (all 4 steps and Done
      Criteria genuinely met — unlike 048, this plan required no STOP).
- [x] **~20-iteration subagent review found 2 real bugs**, both confirmed
      by empirical reproduction rather than trusting the spec's prose:
      (1) known-but-uninitialized collector types (e.g. `headless` gone
      while `rss` still worked) were silently rerouted to the
      unknown-type rss-fallback instead of ever reaching the new
      `collector_unavailable` branch — the "collector unavailable"
      handling was dead code for its own stated motivating scenario;
      (2) a child collector under-reporting its own assigned sources in
      an otherwise-valid result could silently break the
      `succeeded + failed == requested` invariant, directly contradicting
      Done Criterion 1, which design decision 6 had incorrectly called an
      explicit non-goal. Fixed both (`_KNOWN_COLLECTOR_TYPES` distinction
      in the grouping loop; a post-merge reconciliation pass against
      `sources_config` in both directions — under- and over-reporting),
      added 3 new tests (each confirmed failing against the pre-fix code
      first), re-ran full suite clean: 1236 passed, same 13 pre-existing
      failures, no new ones.

## Reassess after each completion

- [x] 033/021/023/046/034/038/036/037/048/040 have each landed
      (DONE/PARTIAL/PARTIAL/PARTIAL/DONE/PARTIAL/DONE/DONE/PARTIAL/DONE).
      With 040 now also DONE: 031/032/035/039/044 still belong in the
      frontend repo; 041/043/047/049 all transitively depend on 021
      and/or 023, which are PARTIAL pending a coordinated backend+frontend
      change and operator secrets this session cannot supply (see their
      own entries above) — none of them newly unblocked by 040 or 048
      landing (040 was a leaf bug-fix, 048 a leaf spike; neither
      appears as a dependency of any other remaining row in
      `plans/README.md` — re-checked directly against the table, not
      assumed).
- [x] **Re-examined 038 before accepting any stopping-point conclusion**:
      its only dependency (033) is DONE and its remaining Steps 4-5
      looked, at first glance, like unblocked backend-only work (unlike
      021/023, which explicitly need operator secrets or frontend
      coordination) — worth checking rather than assuming still stuck,
      the same discipline that had just surfaced 040. Confirmed
      empirically (not assumed): a real Streamlit test harness
      (`streamlit.testing.v1.AppTest`) is importable, but only in the
      separate `.venv-refinery` env, with **no existing test-running
      convention wired for it anywhere in this repo** (no pytest config,
      no Makefile target, nothing in `make test`/`make prepush`), and the
      target UI section (`admin_panel.py` Tab 4, 3042 LOC total, zero
      characterization tests) sits behind an auth gate. Verifying
      `st.cache_resource`/`st.cache_data` behavior here would mean
      building new test infrastructure from scratch, not just writing
      caching code — and shipping unverified caching would mislabel
      Step 4/5's own Verify criteria (cache-hit reuse, TTL expiry,
      invalidation, no-stale-as-current) as met. Decided (at the time):
      038 stays PARTIAL; documented the precise next slice in
      `plans/archive/038/spec.md`. No code was changed by this
      re-examination — decision made before writing any cache/extraction
      code, exactly to avoid the "looks like progress, isn't" trap of
      prepping for deferred, unverifiable work. (038 was later resumed
      and completed — see its own section above.)
- [x] **Natural stopping point reached (re-confirmed twice: once after
      the 040 correction, once after re-examining 038).** The governing
      rule going forward: a plan is startable only if its remaining work
      is both (a) not blocked on external input and (b) verifiable from
      this working directory with what's actually available — not just
      "the dependency row says DONE." Every remaining TODO/PARTIAL plan
      in `plans/README.md` now fails (a), (b), or is out-of-repo:
      021/023/041/043/045/046/047/049 blocked on operator secrets, human
      reviewers, production topology/data, or unmet transitive deps;
      031/032/035/039/044 belong in the frontend repo; 048 intentionally
      STOPPED at its own corpus/reviewer gate; 038 fails verifiability as
      just established. Per this session's own directive ("do not ask
      for clarification on anything you can resolve by reading the spec
      and running tests"), these are correctly left PARTIAL rather than
      force-advanced. No further plan is autonomously startable from this
      working directory; do not manufacture busywork to keep the loop
      running.
- [ ] Frontend plans (031, 032, 035, 039, 044) belong in the Astro repo
      (`noticiencias`), not here — flag when reached instead of implementing
      from this working directory.
- [x] Spike plans (047, 048, 049) end in an ADR/decision doc, not shipped
      code — don't over-build. 048 is the first of these actually
      attempted this session; it landed as Step-1-only + STOP ADR per this
      principle.
- [ ] Every ~20 iterations: fresh subagent review of spec.md + implementation
      for gaps; loop on feedback.

## Session resumption (2026-07-22): "unblock the remaining items"

- [x] User asked directly whether the remaining plans could be unblocked.
      Asked back (AskUserQuestion, not assumed) since several blockers
      were genuinely the user's call: build-it-myself work vs. operator
      secrets vs. a human reviewer commitment.
- [x] Answers: (1) build what's genuinely unblockable without operator
      input — 038's test harness, frontend-repo plans, 021's cross-repo
      work; (2) operator will supply 023's Cloudflare provisioning
      themselves (guided, not done in chat — secrets stay out of the
      conversation); (3) operator will personally review plan 048's
      corpus, async.
- [x] 046: asked directly — no production deployment exists yet. Confirms
      the prior STOP, doesn't change it. Recorded in `plans/046/spec.md`.
- [x] 048: Steps 2-3 tooling built (see the follow-up section above under
      Plan 048).
- [x] 023: re-verified `docs/report-pipeline-setup.md` (written in an
      earlier pass) is still accurate against the current frontend repo
      state — no new code needed, just confirmed and handed back to the
      operator to execute (R2 bucket, KV namespace, Cloudflare secrets
      are their account, their credentials, not something to paste into
      chat).
- [ ] 038, frontend baseline + plan 031, and 021 (gated finale) — in
      progress, see their own sections as they land.
