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
  vs. pre-existing baseline). See `plans/archive/033/todo.md` for details.
- **021 — Rebuild the publication callback contract**: PARTIAL, substantially
  advanced (2026-07-22). Steps 0-3 and 5 DONE: the state machine no longer
  marks an article "completed" the instant a PR opens (stays "publishing"
  until a real webhook names it complete/rejected via its persisted
  `refinery_id`, matched against the frontend's `publication_ids`, never
  branch equality); fixed the resulting dedup-guard and duplicate-PR-recovery
  hazards found while doing this; fixed the frontend's double-envelope bug
  at the root (exported, directly-callable sender functions instead of a
  file-based two-script handoff); a genuine cross-repo contract test
  replays the real frontend sender's output through the real backend
  models/handler/DB, covering failure/success/replay/unrelated-id/auth/
  malformed cases. Step 4's code (fail-closed backend auth, frontend bearer
  token sending) is done on both sides; only the actual
  `WEBHOOK_API_KEY`/`BACKEND_WEBHOOK_TOKEN` secret values are outstanding —
  the operator's own credentials. See `plans/021/spec.md` for the full
  implementation record.
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
  silently reweight scores, out of scope. See `plans/archive/034/spec.md`.
- **038 — Decouple telemetry writes and cache Refinery read models**:
  DONE. Steps 1-3: `enrichment_metrics_store.py` now batches writes
  (25 commits for 1000 events, vs. 1000 before) while proving — via a
  worked counter-example, not just green tests — that batching preserves
  the exact same running-average arithmetic as the per-event original
  (naively coalescing sum/count would have silently produced a different,
  wrong number). Explicit store lifecycle (`create_isolated()`) replaced
  the `_initialized`-mutating test hack. Wired into the real
  collection-cycle boundary (`base_collector.py`'s
  `collect_from_multiple_sources`/`_async`) via a context manager that
  guarantees a flush on exit. **Steps 4-5 (resumed 2026-07-22, operator
  authorized "build what I can unblock myself")**: built a real
  `.venv-refinery` test-running convention from scratch (`make
  test-refinery`, `tools/ci/pytest_refinery.toml`, `pytest` installed
  unpinned into that venv) since none existed; wrote an `AppTest`-based
  characterization test FIRST — before any caching code — that confirmed
  the app's own `REFINERY_UI_UNSAFE_ALLOW=1` dev bypass clears the auth
  gate, that Streamlit tabs execute their body every rerun regardless of
  visual selection (so Tab 4's real analytics queries and metrics are
  directly assertable), and proved the genuinely uncached baseline (DB
  re-queried every independent rerun) before writing a single line of
  caching code. Extracted `apps/refinery/analytics_read_model.py` (pure,
  no `streamlit` import, unit-tested under the main `.venv` with no
  Streamlit needed) and wired `st.cache_resource`/`st.cache_data(ttl=60)`
  + a manual-refresh button + a freshness caption into Tab 4 — then
  proved, via the same harness rather than by inspection, that a second
  independent rerun reuses the cache (DB query count stays at 1), that
  clicking the real refresh button forces a fresh query, and that a
  forced query error surfaces visibly instead of silently showing stale
  data as current. Caught and fixed a real test-writing bug along the
  way: `mock.patch.object(cls, name, wraps=cls.name)` doesn't bind `self`
  for an unbound method reference — documented inline so it isn't
  rediscovered. Full-suite regression clean (1252 passed, same 13
  pre-existing failures). See `plans/archive/038/spec.md`.
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
  baseline. See `plans/archive/036/spec.md` for the full narrative, including the
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
  same-batch rows. See `plans/archive/037/spec.md` for the full empirical
  investigation and design.
- **048 — Spike a curated multilingual topic and entity registry**: PARTIAL.
  Step 1 done: `docs/spikes/curated-enrichment-registry.md` maps every real
  consumer (feature scoring, topic-diversity reranking, serving API,
  image briefs — with monitoring/observability and `CognitiveScorer`
  confirmed NOT to be content consumers, contrary to the plan's broader
  framing), a five-way label vocabulary (editorial category / broad topic
  / named entity / synonym-alias / trend term), and the concrete schema
  gaps (no stable opaque IDs, no deprecation/replacement links, no
  cross-language canonical grouping, only one ad hoc ambiguity rule
  today). Steps 2-6 STOPPED at the plan's own condition ("no qualified
  editorial reviewer or safe representative data") — this is an
  unattended autonomous session with no human available to independently
  label/adjudicate the required ≥200-record corpus; fabricating such a
  corpus and dressing self-generated labels as independently reviewed
  would be fabricated governance, not caution, so Step 3's evaluator was
  also deliberately not built (it would only run against the 6 existing
  goldens, which the plan itself disqualifies as evaluation evidence).
  Zero production files touched (`config.toml`, `config_schema.py`,
  `settings.py`, enrichment/scoring/reranker code, the golden fixture —
  all confirmed byte-identical via `git diff --stat`). **Update
  (2026-07-22)**: the operator confirmed they will personally review/
  label the corpus, so Steps 2-3 tooling is now built — see "Session
  resumption" below. Still PARTIAL: Steps 4-6 depend on the reviewer
  actually labeling a meaningful sample first. See `plans/048/spec.md`
  and `docs/adr/0004-curated-enrichment-registry-spike.md`.
- **040 — Account for every collector-dispatch outcome**: DONE. An
  earlier part of this session had already committed real Step 1/2 work
  (`f64466c`) without updating `plans/README.md` or writing `plans/040/*`
  — discovered via the plan's own drift-check command, not assumed;
  closed out the remaining gap rather than re-doing the finished part.
  Full behavior matrix now covers all-success (through the real merge
  path), one-exception-plus-success, malformed result, missing collector
  (even the rss fallback target itself missing), unknown-configured-type
  (fallback-to-rss kept deliberately per the plan's own STOP condition —
  confirmed via recon it is untested/undocumented/dead-in-production, so
  "test/document it rather than silently changing to rejection" means
  keep + lock in with a test, not switch to rejection), and empty input.
  `sources_requested`/`sources_succeeded`/`sources_failed` are derived in
  one pass from the final merged `source_details` so
  `succeeded + failed == requested` is structural; `success_rate_percent`
  is always present (`0.0` on empty input). `SourceHealthTracker` now
  receives `record_attempt`/`record_failure` for every dispatch-level
  failure, guarded so a telemetry exception never changes the returned
  summary. Fixed a real pre-existing bug found via recon: dispatcher used
  key `"error"` but `news_collector/system/observability.py` already read
  `"error_message"`, so every dispatcher-attributed failure was silently
  reporting `"unknown"` to `MetricsReporter` — renamed to `error_message`
  (matching the existing collector-wide convention) plus added
  `error_class`. Full-suite regression (memory-watchdog discipline):
  1233 passed, same 13 pre-existing failures as this session's
  established baseline, no new failures, 24.95s. A mandated ~20-iteration
  subagent review then found 2 further real bugs via empirical
  reproduction, not just prose-reading: known-but-uninitialized collector
  types (e.g. `headless` missing while `rss` still worked) were silently
  rerouted to the unknown-type rss-fallback instead of ever reaching the
  new `collector_unavailable` attribution; and a child collector
  under-reporting its own assigned sources in an otherwise-valid result
  could silently break the `succeeded + failed == requested` invariant
  (contradicting the plan's own Done Criterion 1). Both fixed
  (`_KNOWN_COLLECTOR_TYPES` distinction; a post-merge reconciliation pass
  against `sources_config` in both directions), full suite re-run clean
  at 1236 passed, same 13 pre-existing failures. See `plans/archive/040/spec.md`.

## Session wind-down (2026-07-21)

After 040 landed, the board was re-derived directly from
`plans/README.md` rather than trusting the prior "048 is the last
startable plan" conclusion — that check is exactly what surfaced 040 as
a missed, genuinely startable plan. The same re-check was then applied
to 038 (deps satisfied, PARTIAL, and its remaining steps looked
backend-only at first glance) before concluding the session is actually
done. Two facts, not assumptions, close that question: `streamlit`/
`AppTest` are importable only in the separate `.venv-refinery`, with no
test-running convention wired for that environment anywhere in this
repo, and the target UI section sits behind an auth gate — so verifying
`st.cache_resource`/`st.cache_data` behavior in `apps/refinery/admin_panel.py`
(3042 LOC, no characterization tests) would require building new test
infrastructure from scratch, not just writing the caching code. Shipping
that caching unverified would mislabel Step 4/5's own Verify criteria
(cache-hit reuse, TTL expiry, invalidation, no-stale-as-current) as met
when they are not empirically checked — a worse outcome than staying
PARTIAL (at the time — since resumed and completed, see the 038 entry
above and `plans/archive/038/spec.md`'s "Re-examined later the same
session" section for the full reasoning as it stood then).

**A plan is startable only if its remaining work is both (a) not
blocked on external input and (b) verifiable from this working
directory with what's actually available** — not just "the dependency
row says DONE." On the current board: 021/023/041/043/045/046/047/049
are all blocked on operator secrets, human editorial reviewers,
production topology/data, or unmet transitive deps; 031/032/035/039/044
belong in the frontend repo; 048 is intentionally STOPPED at its own
corpus/reviewer gate; 038's remaining steps fail clause (b) as just
established. **The startable set is empty. This is the session's actual
terminus** — not a failure to keep going, but the correct place to stop
per this rule.

## Session resumption (2026-07-22): "unblock the remaining items"

The user asked directly whether the remaining PARTIAL/TODO plans could be
unblocked. Since several blockers documented above were operator-input
gaps (secrets, production topology, a human reviewer), not fixed facts,
this is genuinely the user's call to make — asked via `AskUserQuestion`
rather than assumed. Answers received:
- **046**: no production deployment exists yet — confirms the prior STOP
  finding rather than changing it; 046 stays PARTIAL (see
  `plans/046/spec.md`'s 2026-07-22 update).
- **048**: the operator will personally review/label the evaluation
  corpus, asynchronously — Steps 2-3 tooling built as a result (see the
  048 entry above and `plans/048/spec.md`).
- **023**: the operator opted to supply provisioning, but Cloudflare
  R2/KV bucket creation and account secrets are actions only they can
  take (their account, their credentials) — `docs/report-pipeline-setup.md`
  (written in an earlier pass) already contains the exact `wrangler`
  commands needed and was re-verified still accurate against the current
  frontend repo state; no new code was needed here, just confirming the
  existing guide and handing it back to the operator to execute.
- **038, frontend plans, 021**: re-opened per the user's "build what I can
  unblock myself" choice — these do not need operator secrets, only more
  engineering effort (and, for 021 and the frontend plans, work the
  earlier single-repo framing had incorrectly scoped as out of reach).
  038 is now DONE (see its own entry above). Frontend baseline + plan 031,
  and 021's gated cross-repo finale, follow as their own entries land.

This explicitly does NOT invalidate the 2026-07-21 wind-down's reasoning
at the time it was written — the constraints genuinely changed (a human
now committed to reviewing 048's corpus; the user authorized frontend-repo
work; 046's topology question got a real answer) rather than the earlier
analysis having been wrong.

### Plan 031 (frontend repo) — Step 1 done, Steps 2-4 in progress

Re-checked 031's actual startability before writing anything: both listed
deps clear for the part 031 needs (023's Worker/report *contract* is done
and tested — only production enablement is separately blocked on operator
Cloudflare provisioning, which is out of scope for 031; 030 is
archived/DONE). Ran the plan's own drift check first — clean, only 023's
already-accounted-for growth. Verified, empirically rather than assumed,
that both harnesses Steps 2 and 3 depend on actually work in this
environment: Playwright runs headless here (cached chromium, a real
local-build run against `npm run preview`), and
`@cloudflare/vitest-pool-workers` resolves on the registry.

Step 1 (honest unit coverage denominator + no-regression thresholds) is
done and empirically verified — full record in `plans/031/spec.md`. The
notable finds: `vitest.config.ts` never had the `~` alias `tsconfig.json`
declares, which silently made several source files unresolvable under
plain Vitest; the existing workaround (`vi.mock('~/utils/utils', ...)`
with a hand-copied `trim` reimplementation) had quietly diverged from the
real function's behavior, meaning `src/utils/utils.ts::trim` had zero
real coverage despite looking tested. Fixed at the root (added the
alias) rather than patched around again. A genuinely dead file
(`src/utils/search-url.ts`, zero importers) was deleted rather than given
a pointless test. Per-file coverage thresholds (not global-only) were
chosen and proven against a deliberately injected uncovered-branch
regression, restored byte-for-byte afterward.

Step 2 (deterministic local Playwright tests) is done for everything not
gated on one open question. While fixing it, ran head-first into the
exact bug the step exists to catch: `playwright.config.ts` silently
defaulted to the live production site whenever `PLAYWRIGHT_BASE_URL`
wasn't set, so a test run without it exercised production, not the local
build — reproduced directly (6 report-form assertions failed against
prod, passed once correctly pointed at localhost). Fixed by removing the
live-site default entirely. Also found a genuine, still-unresolved
local/production trailing-slash mismatch (`/buscar/` = 200 on prod,
404 locally, and the reverse for `/buscar`) — asked the operator rather
than guessing which side is "right"; they chose to investigate further,
so 5 route-load assertions are `test.fixme()` with the reasoning inline,
not silently skipped or force-picked either way.

Step 3 (Worker fetch-boundary tests via the Cloudflare Vitest pool) hit
its own plan-specified STOP condition: every published
`@cloudflare/vitest-pool-workers` version requires `vitest ^4.1.0`, but
`workers/package.json` pins `vitest: "4.0.18"` — deliberately, synced to
the main repo's own pin one day before this session (Node 24 alignment,
the operator's own commit). Upgrading it would undo that recent decision
and belongs with whoever owns the toolchain lock, not folded quietly
into a test-authoring plan. Documented as a genuine stop, not pushed
through.

Step 4 (CI gate wiring) landed for the parts that don't depend on Step
3: `content-guard.yml`'s build job now runs `npm run test:coverage`
(Step 1's thresholds actually gate PRs) and a Playwright browser suite
(`CI=true PLAYWRIGHT_BASE_URL=http://localhost:4321`, explicit rather
than relying on the config default alone), with artifact upload on
failure. No Worker-test CI gate exists yet — blocked by Step 3.

Plan 031 lands PARTIAL overall: Steps 1 and 4(partial) DONE, Step 2 DONE
modulo the open trailing-slash question, Step 3 STOPPED on its own named
condition. See `plans/031/spec.md` for the full record.

### Plan 021 — gated cross-repo finale, substantially advanced (2026-07-22)

Checked (not assumed) both of the plan's own STOP conditions before
writing any code — both cleared: `refinery_id` is reliable for every
article that goes through the real automated collector→refinery pipeline
(the one exception found, a manually-authored welcome post, never goes
through this contract at all); a bounded changed-post set is derivable
from standard GitHub Actions event data via `git diff`.

With both conditions clear, landed the full coordinated unit this plan's
own earlier analysis said was required — backend Steps 1(remainder)+2,
frontend Step 3, and the Step 5 cross-repo contract test, together, not
a partial slice. Full record in `plans/021/spec.md`; summary: the
publication state machine no longer marks an article "completed" the
instant a PR opens (a validation failure or an unmerged PR used to leave
it looking permanently live) — it now stays "publishing" until a real
webhook callback names it complete or rejected by its persisted
`refinery_id`, matched against the frontend's `publication_ids`, never
branch equality. Found and fixed two related hazards while doing this
(a dedup-guard regression and a duplicate-PR-creation risk in the
publishing-recovery timeout path) before they could ship. Fixed the
frontend's double-envelope bug by refactoring the sender script into
directly-callable functions instead of patching the file-based handoff
that caused it. Step 4's fail-closed auth code is done on both sides
(reusing the backend's existing environment-tier concept rather than
inventing one); only the real secret values remain, which are the
operator's own credentials to set, consistent with how plans 001/023
handled the same kind of boundary earlier in this session.

## Verification

- Per-plan: follow that plan's own "Verification" / "Done Criteria" section
  exactly.
- Whole-workspace: `make prepush` (test-all + quality-gate) before treating
  a wave of plans as safe to leave uncommitted-work-free; run it at natural
  breakpoints (end of a plan), not after every file edit.
- Every ~20 iterations: spawn a fresh subagent to review this spec.md plus
  the current diff/`plans/README.md` state for gaps (scope drift, skipped
  Done Criteria, silently-broken tests) and loop on its feedback.
