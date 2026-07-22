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
  `plans/034/spec.md`.

## Plan 038 — Decouple telemetry writes and cache Refinery read models (PARTIAL)

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
- [ ] Steps 4-5 (Refinery Streamlit caching): not attempted — needs a
      read-model extraction from `admin_panel.py` first; see
      `plans/038/spec.md` "Why Steps 4-5 were not attempted".
- [x] Full regression gates clean (1179 passed, same 13 pre-existing
      failures, same pre-existing lint/type baseline — two new mypy errors
      this plan's own changes caused were fixed, not left). Committed,
      `plans/README.md` updated to PARTIAL.

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
      See `plans/036/spec.md` for the full narrative.
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

## Reassess after each completion

- [x] 033/021/023/046/034/038/036/037 have each landed
      (DONE/PARTIAL/PARTIAL/PARTIAL/DONE/PARTIAL/DONE/DONE). Newly-startable
      set per `plans/README.md`'s dependency column: **048** (depended only
      on 033, now DONE). 031/032 unblock after 023 but belong in the
      frontend repo (see below). 041/043 need the full 021+023+... set,
      which isn't there yet (021/023 are only PARTIAL). 047 needs 021+023
      fully done — not yet. 049 needs 021+022+028+041 — not yet.
- [ ] Frontend plans (031, 032, 035, 039, 044) belong in the Astro repo
      (`noticiencias`), not here — flag when reached instead of implementing
      from this working directory.
- [ ] Spike plans (047, 048, 049) end in an ADR/decision doc, not shipped
      code — don't over-build.
- [ ] Every ~20 iterations: fresh subagent review of spec.md + implementation
      for gaps; loop on feedback.
