# Metrics Storage Audit

**Date:** 2026-02-16
**Status:** ⚠️ CRITICAL RISKS IDENTIFIED

## 1. Storage Location

- **Hardcoded Path:** `encrichment_metrics_store.py` defines `DB_PATH = "data/enrichment_metrics.db"`.
- **Configuration:** No dynamic configuration found in `settings.py` or default environment variables.

## 2. Writers

- **Primary Writer:** `EnrichmentMetricsStore.record_attempt` and `record_success/cost`.
- **Callers:** `EnrichmentStrategyRouter` (in `router.py`), `ProxyManager`, `HeadlessEnricher`.
- **Context:** Writers do not distinguish between `dry-run`, `test`, or `production`.
- **Dry-Run Leakage:** `run_collector.py` executing with `--dry-run` still initializes the system and potentially triggers `router.route_enrichment`, which records attempts.
  - _Mitigation Check:_ `router.py` records attempt _before_ determining success. If dry-run stops execution, `attempts` are logged but `success` might not be, skewing yield downwards.

## 3. Readers

- **Primary Reader:** `StrategyOptimizer` reads from the same singleton `enrichment_metrics`.
- **Optimization Logic:** Uses _all_ data in the DB regardless of origin.

## 4. Contamination Risks

- **High Risk:** Tests running against the same DB will pollute metrics.
- **High Risk:** Dry-runs (simulations) record attempts, artificially inflating "failure" rates (if they don't complete) or polluting success rates (if mocked).
- **High Risk:** Developers running locally mix with "production" data if syncing DBs.

## 5. Required Actions

1. **Isolate Environments:** `data/metrics/{env}/enrichment_metrics.db`.
2. **Context Awareness:** Inject `RunContext` into Writers to select correct DB.
3. **Migration:** Archive current DB as `legacy` or split if possible.
