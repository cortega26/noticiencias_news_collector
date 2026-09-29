# Todo: fetch-warning remediation (rss_only + feed log clarity)

- [x] Triage the fetch warnings/errors across the stored logs (2026-09-29)
- [x] Write spec + todo (this pair)
- [x] Honor `fetch_mode: rss_only` in `EnrichmentRouter.route_enrichment`
- [x] Rename `collector.feed.empty` → `collector.feed.no_new_items` and gate it on non-empty parsed entries
- [x] Document `fetch_mode: rss_only` in the `sources.yaml` schema comment
- [x] Add router tests: rss_only skip (http), rss_only skip under a strategy lock, normal source unchanged, summary_only alone unchanged
- [x] Create plan 116 (per-host enrichment pacing) + plans ledger row
- [ ] Run targeted pytest, `make lint`, plans ledger, `make test`, inventory check/refresh
- [ ] Commit, push, open PR, merge, clean

## Discovered during triage (not in this change)

- `the_verge` returned an HTML response twice; feed is healthy on live probe — monitoring only.
- `fetch_mode: rss_only` is documented and tested as decoupled from enrichment
  routing (`tests/integration/test_headless_funnel.py`); the first fix attempt
  coupled them and was reverted. Fetching is controlled by
  `enrichment_strategy` only.
- `caltech_news` (summary_only, no explicit strategy) is included in the
  discovery_only switch.
