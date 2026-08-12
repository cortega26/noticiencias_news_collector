# Spec: Plan 050 — Enforce a 30-day candidate recency gate

## Goals

1. An article whose reference date is >= `candidate_max_age_days` (30) is
   **not a candidate** — it must not appear in the curation panel export,
   the final selection, or reporting top-articles.
2. The recency score reaches `0.0` exactly at `candidate_max_age_days`
   (30 days), and is `0.00` already at `29d:23h:59m` — no `0.05` floor and
   no residual floor from the old exponential tail.
3. The cutoff is configurable via `[scoring] candidate_max_age_days`
   (default 30) and shared by scoring and by every candidate-building query.

Acceptance criteria:
- `get_articles_by_score(max_age_days=30)` returns no article whose
  `coalesce(published_date, collected_date)` is older than 30 days.
- A fresh article (published today) still appears.
- `_calculate_recency_score` returns `0.0` for anything whose reference
  date is `>= 30 days` old and `~0.00` (rounds to `0.0`) at
  `29d:23h:59m`.
- Existing monotonic-decay tests still pass.

## Implementation details

### A. Config schema — `noticiencias/config_schema.py`

Add to `ScoringConfig` (after `rescore_days_back`):

```python
candidate_max_age_days: PositiveInt = Field(
    default=30,
    description=(
        "Maximum age in days an article's reference date may have to "
        "remain a candidate. Applied by the candidate/exporter/selection "
        "queries and by the recency decay function."
    ),
)
```

### B. Runtime config — `config.toml`

Under `[scoring]`:

```toml
candidate_max_age_days = 30
```

### C. Recency decay — `news_collector/scoring/basic_scorer.py` `_calculate_recency_score`

Keep reference-date selection and the first three branches (<=1h, <=24h,
<=168h). Replace the `else` branch (and the `return max(0.05, …)`) so the
tail decays to exactly `0.0` at `max_age_hours = candidate_max_age_days *
24`:

```python
age_hours = (now - reference_date).total_seconds() / 3600

if age_hours <= 1:
    score = 1.0
elif age_hours <= 24:
    score = 0.9 + 0.1 * math.exp(-(age_hours - 1) / 8)
elif age_hours <= 168:
    score = 0.7 * math.exp(-(age_hours - 24) / 48)
elif age_hours <= max_age_hours:
    # Linear tail: 0.7 at 168h -> 0.0 exactly at max_age_hours.
    tail = (max_age_hours - age_hours) / (max_age_hours - 168)
    score = 0.7 * tail
else:
    score = 0.0

return max(0.0, min(1.0, score * penalty))
```

Read `candidate_max_age_days` from `get_runtime_config().scoring_config`
(already imported) with fallback `30`.

Note: leaving the 0.05 clamp would defeat goal 2; it is removed.

### D. Candidate query — `news_collector/storage/article_repository.py`

Extend `get_articles_by_score` signature with
`max_age_days: Optional[int] = None`. When set:

```python
from sqlalchemy import func  # import exists? add if needed

if max_age_days is not None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    query = query.filter(
        func.coalesce(Article.published_date, Article.collected_date) >= cutoff
    )
```

Mirror the same optional param on the `DatabaseManager` wrapper
(`news_collector/storage/database.py`) and forward it.

### E. Callers

Pass `max_age_days=get_runtime_config().scoring_config["candidate_max_age_days"]`:
- `news_collector/system/reporting.py`:
  - `export_latest_articles` (DB path)
  - `get_top_articles` (non-category path)
- `news_collector/system/__init__.py` `_execute_final_selection` (normal path)
- `scripts/run_collector.py` non-dry-run export branch (line ~570)

Do NOT change `_execute_final_selection` dry-run simulation or the DB
fallback in `admin_panel.py`.

### F. Test fakes

- `tests/unit/test_system_dry_run_collection.py` `_FakeSelectionDatabase.get_articles_by_score`
  must accept `max_age_days` kwarg (default), since `_execute_final_selection`
  will now pass it.

## Files changed

- `noticiencias/config_schema.py`
- `config.toml`
- `news_collector/scoring/basic_scorer.py`
- `news_collector/storage/article_repository.py`
- `news_collector/storage/database.py`
- `news_collector/system/reporting.py`
- `news_collector/system/__init__.py`
- `scripts/run_collector.py`
- `tests/unit/scoring/test_basic_scorer.py`
- `tests/unit/test_system_dry_run_collection.py`
- new test file for the query filter (e.g. `tests/unit/storage/test_article_repository_age_gate.py`)

## Verification

```bash
make lint
make type
make test
make test-refinery    # if refinery code touched
make config-docs-check  # if present (config schema change)
```

- New recency curve unit tests (0.0 at 30d, ~0.00 at 29d23h59m, no floor).
- New repository age-gate test using an in-memory DB.
- e2e smoke (manual): regenerate export and confirm 0 rows with
  `coalesce date` older than 30 days.
- `git diff --stat` shows only intended files (plan files + above).
