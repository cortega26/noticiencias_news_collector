# Spec: Cross-Repo Pipeline Hardening, Source Reliability, and LatAm Relevance

Status: Active
Scope:
- `news_collector/logic/workflows/`
- `news_collector/system/`
- `news_collector/diagnostics.py`
- `news_collector/enrichment/`
- `news_collector/scoring/`
- `.github/workflows/`
- `tests/`

Authority:
- `docs/AGENTS.md`
- `docs/PRODUCT_FLOW.md`
- `docs/PIPELINE_CONTRACTS.md`
- `../noticiencias/AGENTS.md`

## 1. Goals

This initiative hardens the real backend-to-frontend publication loop, improves source reliability visibility, and strengthens deterministic relevance selection for a Spanish-speaking Latin American general-interest science audience.

The implementation must deliver four linked outcomes:

1. A backend-owned publication smoke path that validates a generated publication artifact against the real frontend gates, not just schema parity.
2. A stable, machine-readable source-health artifact with explicit operational state and failure taxonomy.
3. Stronger deterministic relevance/ranking safeguards so low-value institutional noise is down-ranked even when LLM behavior is degraded or absent.
4. Deterministic PR-safe regression coverage plus opt-in live-source checks for Scrapling and source reliability.

## 2. Baseline Facts To Preserve

- Frontend contract parity currently passes locally via `npm run check:contract-sync`.
- The configured source catalog currently contains 43 English-language sources.
- Scrapling-related strategies are currently used by 8 sources:
  - `deepmind_blog`
  - `harvard_gazette`
  - `microsoft_research`
  - `openai_blog`
  - `phys_org`
  - `sciencedaily_top`
  - `uw_madison_news`
  - `uw_news`
- Current zero-save/high-risk cohort from local health artifacts:
  - `phys_org`
  - `deepmind_blog`
  - `harvard_gazette`
  - `uw_news`
  - `uw_madison_news`
  - `medicalxpress`
  - `techxplore`
  - `openai_blog`
  - `reddit_science`
- Current partial-yield cohort:
  - `sciencedaily_top`
  - `michigan_news`
  - `microsoft_research`

## 3. Non-Goals

- No coordinated frontend schema expansion unless a blocker is found that cannot be solved through workflow/test hardening.
- No redesign of the overall pipeline topology.
- No migration of the frontend publication authority out of `../noticiencias`.
- No live-network assertions in normal PR CI.

## 4. Current Gaps

### 4.1 Publication smoke is too narrow

The backend publication smoke workflow currently generates a fixture post and runs only the frontend `validate:content` gate. That proves schema compatibility but does not prove:

- lint compatibility
- build compatibility
- dist sanity
- frontend audit compatibility
- manifest/sidecar compatibility

### 4.2 Source health is exported through inconsistent shapes

The current codebase has two different source-health paths:

- `news_collector/system/reporting.py` writes a flat `source_health.json` mapping
- `news_collector/diagnostics.py` exports a wrapped `generated_at/sources` structure

This makes the artifact shape unstable and prevents reliable downstream automation.

### 4.3 Source failure modes are under-specified

Current health output captures only coarse success/save information. It does not consistently distinguish:

- feed fetch failure
- article fetch blocked
- content too short
- JS-render requirement
- anti-bot / Cloudflare
- extraction/parser mismatch
- editorial relevance rejection
- downstream publication rejection

### 4.4 Deterministic relevance exists but is not yet a first-class regression contract

The repo already contains LatAm-oriented heuristics in scoring, but there is not yet a single regression-focused golden/replay suite that proves:

- LatAm/public-interest stories outrank campus/institutional filler
- low-yield source expansion does not degrade editorial quality
- deterministic ranking remains aligned with the intended audience

## 5. Implementation Plan

### 5.1 Replace planning artifacts

Files:
- `spec.md`
- `todo.md`

Changes:
- Replace the prior pre-scorer/critic task spec with this cross-repo hardening spec.
- Replace the todo list with phased tasks for:
  - cross-repo publication validation
  - source reliability and Scrapling audit
  - deterministic relevance/ranking safeguards
  - e2e and observability

### 5.2 Add a typed publication validation contract and runner

Files:
- new contract module under `news_collector/contracts/`
- new backend script/helper for frontend publication validation
- `.github/workflows/publication-smoke.yml`
- tests under `tests/e2e_cross_repo/`

Changes:
- Introduce a typed publication validation summary model for machine-readable smoke outputs.
- Add a backend-owned runner that:
  - checks out or reuses a frontend workspace
  - writes a generated fixture post and any required sidecars
  - runs:
    - `npm ci`
    - `npm run lint`
    - `npm run validate:content`
    - `npm run build`
    - `npm run test:dist`
    - `npm run test:audit`
  - records a structured result per command
- Persist the summary artifact to disk for local runs and CI artifacts.
- Upgrade `.github/workflows/publication-smoke.yml` to use the full validation runner instead of only `validate:content`.
- Reuse the real frontend checks rather than reimplementing frontend validation logic inside backend code.

Failure classes to encode in the summary:
- `schema_mismatch`
- `sidecar_missing_or_malformed`
- `permalink_collision`
- `taxonomy_contract_violation`
- `frontend_build_failure`
- `frontend_dist_failure`
- `frontend_audit_failure`
- `deploy_smoke_regression`

### 5.3 Normalize source health into one stable contract

Files:
- new source-health contract module under `news_collector/contracts/`
- `news_collector/system/reporting.py`
- `news_collector/diagnostics.py`
- tests for source-health schema and diagnostics

Changes:
- Define a single stable source-health record contract.
- Preserve the existing top-level file location `data/exports/source_health.json`.
- Export a flat `source_id -> record` mapping so current lightweight consumers remain simple.
- Ensure every record always includes:
  - `content_mode`
  - `enrichment_strategy`
  - `feed_ok`
  - `pipeline_ok`
  - `content_ok`
  - `articles_found`
  - `articles_saved`
  - `last_error_message`
  - latency fields
  - strategy-cost fields
  - operational state
  - failure taxonomy
  - ratios used for triage
- Remove the current shape drift between `system.reporting` and `diagnostics`.

Operational states:
- `healthy_full_text`
- `healthy_summary_only`
- `partial_yield_flaky`
- `failing_suppressed_candidate`

Failure taxonomy values:
- `feed_fetch_failure`
- `article_fetch_blocked`
- `content_too_short`
- `js_render_required`
- `anti_bot_block`
- `extraction_parser_mismatch`
- `editorial_relevance_rejection`
- `publication_contract_failure`
- `unknown_failure`

### 5.4 Harden source strategy interpretation and Scrapling audit

Files:
- `news_collector/config/sources.py`
- `news_collector/enrichment/router.py`
- optionally `news_collector/enrichment/strategy_optimizer.py`
- tests for source config and router behavior

Changes:
- Add deterministic review helpers for source strategy consistency.
- Flag contradictory configurations, especially:
  - `summary_only` or `rss_only` sources spending full Scrapling/headless budget without explicit justification
  - sources that should prefer `scrapling_http` but are configured for stealth
- Preserve justified exceptions through explicit source metadata rather than implicit behavior.
- Keep source selection deterministic and reviewable.

### 5.5 Add deterministic LatAm relevance regression coverage

Files:
- new pure helper under `news_collector/scoring/` if needed
- tests under `tests/e2e_cross_repo/` and/or scoring-focused suites
- replay/golden fixtures under `tests/data/`

Changes:
- Formalize a deterministic relevance layer for regression testing.
- Reward:
  - direct Latin American connection
  - broad science/public-interest value
  - meaningful health/climate/space/AI/education/policy impact
- Down-rank:
  - campus administration
  - alumni/internal awards
  - fundraising or donor news
  - narrow institutional PR
  - low-signal product/partnership noise
- Add a replayable golden set that makes the intended editorial preference explicit.

### 5.6 Add a full-pipeline E2E harness from collector replay to frontend handoff

Files:
- new pipeline E2E contract module under `news_collector/contracts/`
- new orchestration helper under `news_collector/logic/workflows/`
- new CLI entrypoint under `scripts/`
- replay scenario fixtures under `tests/fixtures/`
- a dedicated deterministic suite under `tests/e2e_pipeline/`

Changes:
- Introduce a typed `PipelineE2ERunSummary` contract plus stage snapshots for:
  - collection
  - validation
  - scoring
  - selection
  - export
  - approval
  - publication
  - frontend validation
- Build one canonical harness that:
  - runs `NewsCollectorSystem.run_collection_cycle()` against replay fixtures
  - uses a temp DB, temp target repo, and temp diagnostics bundle per run
  - exports real candidates from the DB
  - selects an article for approval using the real export contract
  - runs the real `RefineryEngine`
  - executes the existing frontend validation runner against a target repo
  - persists machine-readable snapshots for each stage
- The deterministic suite must not rely on remote GitHub or live network sources.
- The harness may stub only the non-deterministic boundaries that are not themselves under test:
  - editorial generation
  - remote PR creation
  - optional dependency install
- The harness must identify and persist a single root failure stage plus the first observable divergence when a scenario fails.

Required deterministic scenarios:
- `happy_path_latam_winner`
- `blocked_source_fallback`
- `low_value_beats_high_value_regression`
- `frontend_rejects_generated_post`
- `stuck_publishing_recovery`
- `duplicate_permalink_collision`

Required diagnostics bundle contents:
- replay/scenario input
- collection report
- post-validation DB snapshot
- scoring and final selection snapshot
- export payload
- approved article payload
- generated markdown/frontmatter
- frontend validation summary
- publication attempt summary
- run summary with root failure stage

### 5.7 Fix save-path drift exposed by replay-driven candidate-only articles

Files:
- `news_collector/collectors/rss_collector.py`
- deterministic tests covering candidate-only persistence behavior

Changes:
- Replace the invalid `processing_status_override="enrichment_failed"` path with a status that is actually allowed by the persistence contract.
- Preserve the original intent:
  - article is discovered and persisted for diagnostics
  - article is not eligible for export/publication
  - failure reason remains machine-readable for the E2E diagnostics bundle
- Add regression coverage proving replay-discovered but non-publishable articles are persisted as non-publishable instead of being dropped silently by a contract mismatch.

## 6. Test Plan

### 6.1 Deterministic PR-safe coverage

Add or update tests for:

1. Full backend-driven frontend smoke run
   - fixture post is generated
   - required sidecars/manifests are materialized
   - all frontend gates are executed
   - structured summary is persisted

2. Source-health contract
   - every record has the stable required fields
   - operational states are derived deterministically
   - failure taxonomy is derived deterministically

3. Source strategy consistency
   - `summary_only` + stealth-without-justification is flagged
   - `scrapling_http` is preferred where a browser is not needed
   - strategy-cost fields are surfaced in the health report

4. Relevance regression
   - LatAm/public-interest science outranks campus/admin filler
   - universal-interest science outranks low-value institutional updates
   - ranking does not regress when candidate sets include weak institutional content

5. Full-pipeline E2E harness
   - replay fixture drives the real collector and DB persistence
   - selection/export/refinery/frontend handoff run end to end
   - every failure persists a diagnostics bundle with one root failure stage
   - recovery, frontend rejection, and duplicate permalink scenarios are covered

### 6.2 Nightly/manual live coverage

Keep live-network tests opt-in or scheduled:

- live source health sweep across the catalog
- live Scrapling comparison for hard sources
- diff reporting for newly broken or collapsing sources

## 7. Verification

### V1. Full frontend smoke runs from the backend

Proof:
- run the new publication validation runner against a temp frontend workspace
- assert success when all frontend gates pass
- assert a structured summary artifact is written

### V2. Publication failure classes are machine-readable

Proof:
- add regression tests that force command failures or malformed sidecars
- assert the resulting summary contains the expected failure class

### V3. `source_health.json` has one stable schema

Proof:
- update diagnostics/reporting tests so both code paths serialize the same flat record shape
- assert required keys, operational state, and failure taxonomy are present

### V4. Contradictory source strategy usage is detectable

Proof:
- add config/router tests covering `summary_only`/`rss_only` Scrapling contradictions and `scrapling_http` preference scenarios

### V5. Deterministic LatAm relevance stays aligned

Proof:
- add replay/golden tests where a LatAm-relevant or broadly important science story must beat campus/internal announcement items

### V6. Required validation commands

Backend:

```bash
pytest tests/e2e_cross_repo -q
pytest tests/e2e_pipeline -q
pytest tests/test_source_health_schema.py tests/unit/test_diagnostics.py tests/unit/enrichment/test_router.py tests/unit/test_strategy_optimizer.py -q
```

Broader repo gates after implementation stabilizes:

```bash
make lint
make type
make test-contracts
make test-boundaries
make quality-gate
```

Frontend commands are executed by the backend smoke runner and must include:

```bash
npm ci
npm run lint
npm run validate:content
npm run build
npm run test:dist
npm run test:audit
```
