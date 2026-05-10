# Batch 4: System Decomposition — ValidationCoordinator, ScoringCoordinator, SessionReporter

## Goals

Decompose the `NewsCollectorSystem` god object (762 lines, 6+ responsibilities) into three focused coordinator/reporter classes while preserving the public API and all existing behavior.

### Principles

1. **No behavioral change** — extracted code runs the same logic with the same side effects. Pure structural refactoring.
2. **Backward-compatible public API** — `NewsCollectorSystem.initialize()`, `.run_collection_cycle()`, `.export_latest_articles()`, `.shutdown()` remain unchanged.
3. **Each coordinator owns one phase** — validation, scoring, session reporting each get their own class with explicit dependencies, removing hidden coupling to `self`.
4. **One extraction per commit** — each coordinator is independently verifiable.

---

## Extraction 1: ValidationCoordinator

**File:** `news_collector/validation/coordinator.py`

```python
class ValidationCoordinator:
    def __init__(self, db_manager, validator, logger):
        ...

    def execute(
        self, collection_results: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        ...
```

### Source

Extracted from `NewsCollectorSystem._execute_validation` (system/__init__.py:354-455).

### Logic preserved (no behavioral change)

| Behavior | How preserved |
|---|---|
| Dry-run returns `{"success": True, "validated_count": 0, "rejected_count": 0}` | Early return |
| Batch loop: BATCH_SIZE=100, MAX_BATCHES=10_000 | Module-level constants |
| `db_manager.get_pending_articles(limit=BATCH_SIZE)` | Delegated to `self.db_manager` |
| `adapt_to_validation_payload` contract adapter | Same import inside method |
| `validator.validate_batch(...)` | Delegated to `self.validator` |
| Invalid articles → `processing_status: "rejected"`, valid → `processing_status: "validated"` | Same mapping dicts |
| `db_manager.update_validation_status_bulk(all_mappings)` | Delegated to `self.db_manager` |
| Logger event `validation.completed` with total/rejected/valid/batches | Same info dict |
| Return dict: `success`, `validated_count`, `rejected_count`, `details` | Same shape |

### Wiring in NewsCollectorSystem

```python
# Lazy init in _execute_validation:
if self.validation_coordinator is None:
    self.validation_coordinator = ValidationCoordinator(
        self.db_manager, self.validator, self.logger
    )
return self.validation_coordinator.execute(collection_results, dry_run)
```

---

## Extraction 2: ScoringCoordinator

**File:** `news_collector/scoring/coordinator.py`

```python
class ScoringCoordinator:
    def __init__(self, db_manager, scorer, logger, config_override=None):
        ...

    async def execute(
        self, collection_results: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        ...
```

### Source

Extracted from `NewsCollectorSystem._execute_scoring` (system/__init__.py:457-578).

### Logic preserved

| Behavior | How preserved |
|---|---|
| Dry-run delegates to `_simulate_scoring(collection_results)` | Internal method |
| Fetches validated articles via `db_manager.get_pending_articles(status="validated")` | Delegated to `self.db_manager` |
| `scorer.reset_cycle_metrics()` if available | Checked via `hasattr` |
| `adapt_to_scoring_input(article, source_config)` contract adapter | Same import |
| Batch scoring with sequential fallback | Identical try/except chain |
| `asyncio.gather(*tasks, return_exceptions=True)` for sequential fallback | Same |
| `db_manager.update_articles_score_bulk(...)` | Delegated to `self.db_manager` |
| `ALL_SOURCES` lookup for source_config | Same import from config |
| Return dict: `success`, `statistics`, `processed_articles` | Same shape |

### Wiring in NewsCollectorSystem

```python
if self.scoring_coordinator is None:
    self.scoring_coordinator = ScoringCoordinator(
        self.db_manager, self.scorer, self.logger, self.config_override
    )
return await self.scoring_coordinator.execute(collection_results, dry_run)
```

---

## Extraction 3: SessionReporter

**File:** `news_collector/system/reporter.py`

```python
class SessionReporter:
    def __init__(self, system):
        ...

    def generate_report(
        self,
        collection_results: Dict[str, Any],
        scoring_results: Dict[str, Any],
        selection_results: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        ...
```

### Source

Extracted from `NewsCollectorSystem._generate_session_report` (system/__init__.py:627-639) and the `generate_session_report` function in `reporting.py` (lines 128-203).

### Current flow

1. `NewsCollectorSystem._generate_session_report()` calls `reporting.generate_session_report(self, collection_results, scoring_results, selection_results, session_id)`.
2. `reporting.generate_session_report()` builds the report dict and exports source health.

### New flow

1. `NewsCollectorSystem._generate_session_report()` instantiates `SessionReporter(self)` and calls `.generate_report(...)`.
2. `SessionReporter.generate_report()` contains the logic from `reporting.generate_session_report()`.

### Logic preserved

| Behavior | How preserved |
|---|---|
| Computes `end_time`, `duration` from `system.start_time` | Same calculation |
| `session_info` with session_id, system_id, start/end, duration | Same structure |
| collection/scoring/selection results condensed into report | Same dict assembly |
| Performance metrics: articles_per_second, sources_per_minute, success_rate | Same formulas |
| Summary aggregation | Same |
| Source health export to `data/exports/source_health.json` | Same file write |
| Health export errors are non-fatal (logged, not raised) | Same try/except |

---

## Public API Contract (unchanged)

| Method | Signature |
|---|---|
| `NewsCollectorSystem.__init__(...)` | Same |
| `NewsCollectorSystem.initialize()` | Same |
| `NewsCollectorSystem.run_collection_cycle(...)` | Same |
| `NewsCollectorSystem.get_top_articles(...)` | Same |
| `NewsCollectorSystem.export_latest_articles(...)` | Same |
| `NewsCollectorSystem.get_system_statistics()` | Same |
| `NewsCollectorSystem.shutdown()` | Same |
| `create_system(...)` | Same |
| `run_quick_collection(...)` | Same |

`reporting.py` keeps `get_top_articles`, `export_latest_articles`, `get_system_statistics`; only `generate_session_report` is removed (moved to `SessionReporter`).

---

## Verification

### Per-extraction

1. New coordinator/reporter unit tests pass with mocked dependencies.
2. `make test-boundaries` — boundary tests use `_execute_validation` and `_execute_scoring`, verifying delegation.
3. `make test` — full suite, zero regressions.

### Final gate

1. `make test` — all tests pass.
2. `tests/unit/system/test_s1_refactor.py` — safety contracts still hold (initialize, run cycle, shutdown).
3. `git diff` shows only moved/redirected code, no new logic.

### Test files

| File | Coverage |
|---|---|
| `tests/unit/validation/test_validation_coordinator.py` | Dry-run, batch loop, empty DB, max-batch halt, mixed valid/invalid |
| `tests/unit/scoring/test_scoring_coordinator.py` | Dry-run, batch success, batch failure→sequential fallback, empty, all-excluded |
| `tests/unit/system/test_session_reporter.py` | Full data, empty data, health export success, health export failure |

---

## What does NOT change

- `news_collector/system/reporting.py` — keeps `get_top_articles`, `export_latest_articles`, `get_system_statistics`; only removes `generate_session_report`.
- `news_collector/system/pipeline.py` — unchanged.
- `news_collector/system/observability.py` — unchanged.
- `news_collector/system/bootstrap.py` — unchanged.
- `news_collector/system/__init__.py` — keeps all public methods; only replaces `_execute_validation`, `_execute_scoring`, `_generate_session_report` bodies with delegation.
- `news_collector/validation/validator.py` — unchanged.
- `news_collector/scoring/__init__.py` — unchanged.
