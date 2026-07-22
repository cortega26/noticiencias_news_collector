# Spec: Implement the remaining plans in plans/README.md

## Goals

- Work through the 18 remaining TODO/PARTIAL plans (021, 023, 031–041, 043–049) in
  dependency order, not plan-number order.
- Each plan's own file (`plans/NNN-*.md`) is the authoritative spec for that plan's
  scope, design decisions, and STOP conditions — this document only tracks
  cross-plan sequencing and the invariants that apply to all of them. Do not
  duplicate a plan's content here.
- Finish one plan fully (implementation + its own verification + regression
  gates) before starting the next, unless a plan is explicitly a spike/ADR
  (047–049) that ends in a decision document rather than shipped code.
- Never mark a plan DONE in `plans/README.md` while any of its own Done
  Criteria are unmet.

## Cross-plan invariants (apply to every plan below)

- Repo boundary: this working directory is the Python backend
  (`noticiencias_news_collector`). Plans 031, 032, 035, 039, 044 touch the
  Astro frontend repo (`noticiencias`) instead — implement those from that
  repo's working directory, not from here.
- Local commits only. One commit per completed plan (or per safely-separable
  phase of a large plan). No `git push`, no opening frontend PRs, no
  publishing — those need explicit operator sign-off (publication is
  PR-only per `docs/AGENTS.md`).
- Regression gates before any commit: `make test` (or the narrower
  plan-specific test target when the full suite is impractically slow to
  iterate on) plus `make lint && make type` for touched Python; the plan's
  own "Verification" section always wins if it specifies something more
  targeted.
- `except Exception: pass` is banned (per `docs/AGENTS.md`); policy modules
  (scoring, validation, taxonomy, editorial) stay network-free; I/O stays at
  the edges.
- After finishing a plan: update its row in `plans/README.md` (status +
  one-line note), update this file's "Sequencing state" section, commit.

## Dependency-driven order (superseding plans/README.md's numeric listing)

Per the dependency column in `plans/README.md`, the plans immediately
startable (all deps archived/done) were 033, 021, 023, 046; with 033 (and
034) done, 036/037/048 additionally became startable. Re-derive the next
startable set from `plans/README.md` after each plan completes — do not
hardcode a full ordering up front, since finishing one plan changes what's
unblocked.

## Sequencing state

(Updated as work proceeds — see `todo.md` for the live checklist.)

- **033 — Make configuration refresh live**: DONE. Finished Phase 2 (all 21
  consumers migrated), Phase 3 (Refinery `save_toml_config` truthful
  return contract), Phase 4 (audit/lint/type/test gates, zero regressions
  vs. pre-existing baseline). See `plans/033/todo.md` for details.
- **021 — Rebuild the publication callback contract**: PARTIAL. Only Step 0
  (a refinery_id identity fix required by the plan's own STOP condition,
  not an original step) is done. Steps 1-5 are one coordinated
  backend+frontend change (landing backend matching logic before the
  frontend populates `publication_ids` would strand every real callback —
  a regression, not progress) plus an operator-secret boundary for auth.
  See `plans/021/spec.md` for the full recon and a dedup-guard hazard the
  next implementer must fix first.
- **023 — Connect and harden the report pipeline**: PARTIAL. All 5 steps
  implemented and tested in the frontend repo (contract, honest form
  behavior, request bounds, durable-sink tracking, KV rate
  limiting/idempotency, CI gates). Production endpoint stays disabled
  pending operator R2/KV provisioning (the plan's own STOP condition). See
  `plans/023/spec.md` and `../noticiencias/docs/report-pipeline-setup.md`.
- **046 — Prove and automate production migrations**: PARTIAL. Alembic-first
  SQLite test coverage (every revision→head, downgrade roundtrips,
  model/schema parity, single linear history) and a read-only revision guard
  (`news_collector/storage/migration_guard.py` +
  `scripts/check_migration_revision.py`) are done and tested. Step 1
  (identify the production migration owner) hits its own STOP condition —
  no discoverable production deployment topology anywhere in the repo. A
  second STOP was found empirically while attempting the PostgreSQL half of
  Steps 2/4/6: PostgreSQL is not usable at all yet (no driver dependency in
  any lockfile, dead env vars in `docker-compose.yml`'s app services, and
  host-absolute paths hardcoded in the committed `config.toml`) — fixing
  those is a dedicated follow-up outside this plan's scope, not a one-line
  patch to force a test green. See `plans/046/spec.md` and
  `docs/database_deployment.md`.
- **034 — Centralize article admission**: DONE. One shared, typed,
  structural admission policy (`news_collector/collectors/admission.py`)
  now runs exactly once, in `BaseCollector._filter_and_save_articles`,
  before duplicate lookup/persistence, for every collector (RSS, HTML,
  Reddit). The previous policy was dead code (zero real callers — only a
  unit test exercised it), and RSS additionally had its own weaker
  extraction-time override; both removed. Kept hard-structural admission
  (title/content length) strictly separate from soft scoring signals
  (clickbait keywords) after confirming the two keyword lists partially
  overlap but each has exclusive terms — unifying them would still
  silently reweight scores, out of scope. See `plans/034/spec.md`.
- **038 — Decouple telemetry writes and cache Refinery read models**:
  PARTIAL. Steps 1-3 done: `enrichment_metrics_store.py` now batches writes
  (25 commits for 1000 events, vs. 1000 before) while proving — via a
  worked counter-example, not just green tests — that batching preserves
  the exact same running-average arithmetic as the per-event original
  (naively coalescing sum/count would have silently produced a different,
  wrong number). Explicit store lifecycle (`create_isolated()`) replaced
  the `_initialized`-mutating test hack. Wired into the real
  collection-cycle boundary (`base_collector.py`'s
  `collect_from_multiple_sources`/`_async`) via a context manager that
  guarantees a flush on exit — confirmed first that the real entrypoint
  (`scripts/run_collector.py`) never calls the existing `System.shutdown()`
  hook, so the default stays a safe, byte-identical batch size of 1 and
  only this boundary opts into real batching. Steps 4-5 (Refinery Streamlit
  caching) not attempted — needs a read-model extraction from the
  ~2951-LOC `admin_panel.py` first; see `plans/038/spec.md`.
- **036 — Bound scoring memory, prompts, and concurrency**: DONE. Explicit
  validated workload bounds (`page_size`, `max_prompt_items`,
  `max_prompt_chars`, `cycle_item_budget` on `ScoringConfig`); new keyset
  `(collected_date, id)` cursor-paged repository methods added alongside
  (not replacing) the existing unpaged ones; `ScoringCoordinator.execute()`
  rewritten to fetch/score/persist one bounded page at a time across both
  sources, with cross-source dedup, persistence-failure-as-cycle-failure
  with a resumable cursor, and a semaphore-bounded fallback (reusing the
  previously dead-code `workers`/`scoring_workers` config slot) instead of
  unbounded `asyncio.gather`; `CognitiveScorer` chunks prompts by item
  count/estimated chars after confirming (by reading the prompt/parsing
  code, not assuming) no cross-article scoring dependency exists; workload
  telemetry plus `scripts/benchmark_scoring.py` proving the bounds hold on
  1000 synthetic articles. A full-suite regression run (not just the
  targeted scoring tests) caught a real infinite-loop regression in 3
  unrelated tests that mocked the old unpaged DB methods — fixed, and the
  full suite now passes with the exact same 13 pre-existing failures as
  baseline. See `plans/036/spec.md` for the full narrative, including the
  STOP-condition-3 semantic-dependency check and the regression's root
  cause/fix.
- **037 — Make bulk article persistence set-based**: DONE. Reduced
  `save_articles_bulk()`'s SELECT count from 561 to 4 for a 100-article
  batch (URL/content-hash exact-dup checks now chunked `IN` queries;
  near-duplicate candidates prefetched once per batch across the union of
  needed simhash prefixes instead of up to 3 queries per article). Two
  empirical probes before any refactor (per an advisor consult) found that
  current bulk code does NOT join two near-duplicate articles submitted in
  the same batch (an `autoflush=False` artifact), while the true
  "sequential" oracle — `save_article()` called twice — does join them and
  back-mutates the matched candidate's confidence. Building the in-memory
  candidate map so same-batch near-duplicates join (the plan's Step 4, as
  literally written) closes this real gap rather than violating the
  STOP-condition against semantic drift. `_resolve_cluster_for_candidates`
  is now shared, unchanged logic between the live single-item path and the
  new batched path, including cluster-merge propagation to not-yet-flushed
  same-batch rows. See `plans/037/spec.md` for the full empirical
  investigation and design.

## Verification

- Per-plan: follow that plan's own "Verification" / "Done Criteria" section
  exactly.
- Whole-workspace: `make prepush` (test-all + quality-gate) before treating
  a wave of plans as safe to leave uncommitted-work-free; run it at natural
  breakpoints (end of a plan), not after every file edit.
- Every ~20 iterations: spawn a fresh subagent to review this spec.md plus
  the current diff/`plans/README.md` state for gaps (scope drift, skipped
  Done Criteria, silently-broken tests) and loop on its feedback.
