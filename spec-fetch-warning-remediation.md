# Spec: honor discovery-only sources + clarify empty-feed logging

Status: in progress · 2026-09-29
Scope: `news_collector/enrichment/router.py`,
`news_collector/config/sources.yaml`, `news_collector/collectors/rss_collector.py`,
`tests/unit/enrichment/test_router.py`

## Goal

Stop the burst article-page fetches that produce the 403/429 fetch warnings for
the summary-only sources that currently route `http` enrichment anyway, and
stop the `collector.feed.empty` event from reading like a fetch failure when it
actually means "the feed had no new eligible items".

Acceptance criteria:

1. `enrichment_strategy: discovery_only` is handled explicitly by
   `EnrichmentRouter.route_enrichment`: no article-page fetch (HTTP, headless,
   scholarly, or scrapling) and reason `discovery_only`. The strategy is already
   accepted by the source schema whitelist (`config/sources.py:236-242`).
2. `fetch_mode: rss_only` stays decoupled from enrichment routing — it does not
   by itself gate any strategy. This preserves the existing contract pinned by
   `tests/integration/test_headless_funnel.py::test_rss_only_does_not_block_headless_enrichment`;
   fetching is controlled by `enrichment_strategy` only.
3. The sources that were fetching article pages despite `content_mode:
   summary_only` are switched to `discovery_only`: `medicalxpress`,
   `techxplore`, `michigan_news`, `scitechdaily` (rss_only + http) and
   `caltech_news` (summary_only + default http).
4. The post-filter event is renamed `collector.feed.empty` →
   `collector.feed.no_new_items` and is emitted only when the parsed feed had
   entries that were all filtered out (recency window / dedup). A genuinely
   entry-less feed keeps the existing `collector.feed.empty_entries` event and
   does not also emit `no_new_items`.
5. Tests cover: discovery_only skip, rss_only does not gate the configured
   strategy, and summary_only alone does not skip.
6. `make lint`, targeted pytest, `make test`, and the plans ledger validator
   pass; `make inventory-check` is clean.

## Current state (evidence, 2026-09-29)

- `config/sources.py:236-242` accepts `scholarly`, `http`, `headless_fallback`,
  `scrapling_stealth`, `scrapling_http`, `discovery_only`; only `discovery_only`
  had no dispatch branch in `router.py`, so it fell through to
  `unsupported_strategy`. It is now explicit.
- Five summary-only sources carried `http`/default strategy and still fetched
  article pages. Log evidence across the archived runs: `medicalxpress` 73×403,
  `techxplore` 73×403, `michigan_news` 57×403 (+ feed-level 429s), `caltech_news`
  42 connection failures; live single requests return 200 for most of them, so
  the failures are burst-triggered and the declared intent (summary only) was
  not being honored.
- `collector.feed.empty` is emitted after the recency/dedup filter removes all
  candidates (`rss_collector.py`), which is why slow feeds such as
  `the_gradient` appear as "empty" although their feeds are populated.

## Implementation

- `news_collector/enrichment/router.py`: dispatch branch returning
  `{"success": False, "reason": "discovery_only", "strategy_used": "none"}`.
  `fetch_mode` is not consulted, preserving the decoupling contract.
- `news_collector/config/sources.yaml`: five sources switched to
  `enrichment_strategy: discovery_only`; schema comment documents `fetch_mode`
  semantics and the `discovery_only` strategy.
- `news_collector/collectors/rss_collector.py`: rename the extraction-filter
  event to `collector.feed.no_new_items` and gate it on the parsed feed having
  entries, so the truly-empty case stays covered by
  `collector.feed.empty_entries` only.
- Tests in `tests/unit/enrichment/test_router.py`.
- Out of scope: changing `fetch_mode` semantics; per-host pacing (plan 116);
  any editorial policy change.

## Verification

| Check | Command | Expected |
|---|---|---|
| Targeted tests | `.venv/bin/python -m pytest tests/unit/enrichment/test_router.py tests/integration/test_headless_funnel.py -q` | all pass |
| Lint | `make lint` | exit 0 |
| Unit suite | `make test` | exit 0 |
| Plans ledger | `python3 scripts/validate_plans_ledger.py` | `OK` |
| Inventory | `make inventory-check` | clean |

## Record (implementation)

- Router: explicit `discovery_only` branch added; no `fetch_mode` coupling.
- Config: `medicalxpress`, `techxplore`, `michigan_news`, `scitechdaily`,
  `caltech_news` → `enrichment_strategy: discovery_only`.
- Event: `collector.feed.empty` → `collector.feed.no_new_items`, gated on
  non-empty parsed entries.
- First attempt had added a `fetch_mode: rss_only` short-circuit in the router;
  the full suite caught `test_rss_only_does_not_block_headless_enrichment`
  failing, so it was reverted in favour of the strategy-based fix. This is the
  deliberate decoupling contract; do not re-introduce the coupling.
- Gate note: `make lint`, `make test` (3436 passed), plans ledger, and
  inventory-check are green. `make type` (full suite with coverage) locally
  times out `tests/e2e_pipeline/...::test_pipeline_e2e_bundle_root_is_repeatable`
  at the 300s pytest mark; without coverage the same test passes in 297.9s on
  this machine, and CI on main is green for it. Environmental, not a logic
  regression; CI remains the merge gate.
- Coverage ratchet: touching `router.py` requires ≥90% line coverage on changed
  modules, and the module sat at 78.65% in CI. Backfilled
  `tests/unit/enrichment/test_router.py` with 17 additional cases (strategy
  locks, adaptive hint, headless failure modes, scrapling http/stealth paths,
  missing URL, scholarly failure) → router now 96.40% under `make test`.
