# Plan 033: Make runtime configuration refresh observable by all consumers

## Goals

1. **One runtime configuration authority** — a single `get_runtime_config()` accessor returns an immutable, versioned snapshot. No consumer reads mutable config via stale by-value imports.
2. **Atomic, validated refresh** — `refresh_runtime_config()` builds a complete new snapshot, runs ALL validations, and swaps one reference atomically. Failed validation leaves the old snapshot untouched (rollback-safe).
3. **All consumers migrated** — collectors, scoring, enrichment, storage, HTTP, logging, monitoring all obtain one snapshot per operation/cycle.
4. **Refinery truthfulness** — save returns applied version, applied-live fields, and restart-required fields; never lies about success.
5. **Long-lived resource safety** — resources that cannot be safely rebuilt (db engines, connection pools) report `restart_required` rather than silently mutating.

## Implementation Details

### Architecture

```
┌───────────────────────────────────────────────────────────┐
│ RuntimeConfigSnapshot (frozen dataclass)                  │
│ - version: int                                            │
│ - data_dir, logs_dir, dlq_dir: Path                      │
│ - environment, debug, is_production, is_staging: str/bool │
│ - llm_system_available: bool                              │
│ - database_config, collection_config, ... : dict          │
│ - restart_required_keys: frozenset[str]                   │
│ - build_timestamp: datetime                               │
└───────────────────────────────────────────────────────────┘
                           ▲
          get_runtime_config() ── returns current snapshot
                           │
          refresh_runtime_config() ── builds new snapshot,
                                       validates, atomically swaps
                           │
          _CURRENT_SNAPSHOT: RuntimeConfigSnapshot | None
          _CONFIG_VERSION: int (monotonic counter)
```

### Consumer migration pattern

**Before** (stale):
```python
from news_collector.config.settings import COLLECTION_CONFIG

class SomeCollector:
    def collect(self):
        timeout = COLLECTION_CONFIG["request_timeout"]  # stale since import time
```

**After** (live):
```python
from news_collector.config.settings import get_runtime_config

class SomeCollector:
    def collect(self):
        cfg = get_runtime_config()  # fresh snapshot each operation
        timeout = cfg.collection_config["request_timeout"]
```

### Key design decisions

1. **Dict values in snapshot are deep-copied** — consumers can't mutate the snapshot's data.
2. **_module_attr_map** shims (the `__getattr__` on the module) remain for backward compatibility but log a deprecation warning on first access per process lifetime.
3. **RUNTIME dataclass** remains as internal mutable store; `refresh_runtime_config()` updates it AND builds a new snapshot.
4. **restart_required_keys** tracks settings whose changes require a process restart (e.g., database driver/URL changes).
5. **Version is monotonic** — increments on every successful refresh. Operators can compare.

### Files to modify

| File | Change |
|------|--------|
| `news_collector/config/settings.py` | Add `RuntimeConfigSnapshot`, `get_runtime_config()`, refactor `refresh_runtime_config()` |
| `news_collector/config/runtime.py` | No changes needed (stays as internal mutable store) |
| `news_collector/collectors/base_collector.py` | Migrate to `get_runtime_config()` |
| `news_collector/collectors/rss_collector.py` | Migrate |
| `news_collector/collectors/html_collector.py` | Migrate |
| `news_collector/collectors/reddit_collector.py` | Migrate |
| `news_collector/collectors/rate_limit_utils.py` | Migrate |
| `news_collector/scoring/basic_scorer.py` | Migrate |
| `news_collector/scoring/feature_scorer.py` | Migrate |
| `news_collector/scoring/__init__.py` | Migrate |
| `news_collector/scoring/coordinator.py` | Migrate |
| `news_collector/storage/database.py` | Migrate (report restart_required for driver/URL changes) |
| `news_collector/storage/article_repository.py` | Migrate |
| `news_collector/storage/source_repository.py` | Migrate |
| `news_collector/infrastructure/requests_client.py` | Migrate |
| `news_collector/infrastructure/http_client.py` | Migrate |
| `news_collector/enrichment/pipeline.py` | Migrate |
| `news_collector/system/__init__.py` | Migrate |
| `news_collector/system/activity_monitor.py` | Migrate |
| `news_collector/system/reporting.py` | Migrate |
| `news_collector/utils/logger.py` | Migrate |
| `news_collector/contracts/collector.py` | Migrate |
| `apps/refinery/admin_panel.py` | Wire truthful semantics |
| `apps/refinery/main.py` | Migrate |

## Verification

### Unit tests (tests/unit/config/)

1. **`test_runtime_snapshot.py`** — Tests for `RuntimeConfigSnapshot`:
   - Snapshot is frozen (cannot setattr)
   - Snapshot dicts are deep-copied (modifying return value doesn't affect internal state)
   - Version is monotonic across refreshes
   - `build_timestamp` is set
   - `restart_required_keys` is a frozenset

2. **`test_live_refresh.py`** — Tests for `get_runtime_config()` and `refresh_runtime_config()`:
   - `get_runtime_config()` returns same version between refreshes
   - `refresh_runtime_config()` increments version
   - Failed build/validation leaves old snapshot (rollback)
   - Concurrent readers see consistent snapshot during refresh
   - Mock config changes are reflected in next `get_runtime_config()` call

3. **`test_consumer_migration.py`** — Tests that every consumer category reads live config:
   - Collector: value changed via refresh → next collection uses new value
   - Scorer: weight changed via refresh → next score uses new weight
   - HTTP client: timeout changed via refresh → next request uses new timeout
   - Re-verify after rolling back

### Integration tests

4. **`test_refinery_apply.py`** — Tests that Refinery save/refresh is truthful:
   - Valid save returns success with version
   - Invalid config returns validation error
   - Restart-required changes are reported
   - Concurrent reader during save sees old version until refresh completes

### Audit commands

```bash
# Must show ZERO mutable config imports by value (only get_runtime_config() calls)
rg -n "from news_collector\.config\.settings import.*[A-Z_]{3,}" news_collector apps || true
# Only unused/immutable constants + get_runtime_config/RUNTIME imports should remain
```

## Done Criteria

- [ ] No production module retains a mutable configuration dict imported by value
- [ ] Refresh is atomic, versioned, and rollback-safe
- [ ] Live vs restart-required settings are explicit to operators
- [ ] All targeted tests pass (`make test`)
- [ ] Import audit returns zero mutable by-value imports
- [ ] Static checks pass (`make lint && make typecheck`)
