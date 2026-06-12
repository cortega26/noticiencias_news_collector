# Plan 005: Add a composite index on `score_logs(article_id, calculated_at)` for the serving query

> **Executor instructions**: Follow step by step; run every verification command
> and confirm the result before moving on. Honor STOP conditions. Update this
> plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- news_collector/storage/models.py news_collector/serving/api.py`
> If either changed, re-confirm the "Current state" excerpts before editing; on
> a structural mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

Every request to `GET /v1/articles` builds a subquery that scans the entire `score_logs` table, grouping by `article_id` and taking `max(calculated_at)` to find each article's latest score, then joins back to `score_logs` on the `(article_id, calculated_at)` pair. `score_logs` grows by one row per article per scoring run (articles are re-scored periodically), so it accumulates without bound. There is **no index** on `(article_id, calculated_at)`, so the group-by and the join both degrade as the table grows — the read endpoint gets slower over time for no functional reason. A composite index makes the "latest score per article" lookup index-supported.

## Current state

`ScoreLog` ORM model has **no `__table_args__`** (so no custom indexes):

```python
# news_collector/storage/models.py:435-476
class ScoreLog(Base):
    __tablename__ = "score_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    score_version = Column(String(10), nullable=False)
    calculated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    final_score = Column(Float, nullable=False)
    ...
    def __repr__(self): ...
```

The query that needs the index:

```python
# news_collector/serving/api.py:287-312  (list_ranked_articles)
latest_log_subquery = (
    session.query(
        ScoreLog.article_id.label("article_id"),
        func.max(ScoreLog.calculated_at).label("latest_calculated"),
    )
    .group_by(ScoreLog.article_id)
    .subquery()
)
score_log_alias = aliased(ScoreLog)
query = (
    session.query(Article, score_log_alias)
    .outerjoin(latest_log_subquery, latest_log_subquery.c.article_id == Article.id)
    .outerjoin(
        score_log_alias,
        and_(
            score_log_alias.article_id == Article.id,
            score_log_alias.calculated_at == latest_log_subquery.c.latest_calculated,
        ),
    )
)
```

Exemplar for adding an index (same file): `Article.__table_args__` at `models.py:221-251` uses `Index("idx_...", "col_a", "col_b")`. `EngagementMetric` at `models.py:352-354` is a cleaner small example:

```python
__table_args__ = (
    Index("idx_article_measured", "article_id", "measured_at"),
    Index("idx_engagement_date", "total_social_engagement", "measured_at"),
)
```

Migrations live in `alembic/versions/`. The **current head** is `a54ba7f7dabb` (verify with `make migrate` chain / `.venv/bin/alembic heads`). Migrations are written idempotently using `inspect()` — see `alembic/versions/a3f1b2c4d5e6_add_content_mode_to_articles.py` as the pattern (it checks existing columns before adding). The DB is SQLite by default (`config.toml [database]`).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Find current head | `.venv/bin/alembic heads` (or read `alembic/versions/`) | `a54ba7f7dabb` (head) |
| Apply migrations | `make migrate` | exit 0, upgrades to new head |
| Migration tests | `.venv/bin/pytest tests/test_database_migrations.py -q` | all pass |
| Serving tests | `.venv/bin/pytest tests/test_serving_api.py -q` | all pass |
| Lint / type | `make lint && make type` | exit 0 |

## Scope

**In scope:**
- `news_collector/storage/models.py` — add `__table_args__` with the index to `ScoreLog`
- `alembic/versions/<new>_add_score_logs_latest_index.py` (create)

**Out of scope:**
- `news_collector/serving/api.py` — the query is correct; only the index is missing. Do not rewrite the query.
- Any other model's indexes.

## Git workflow

- Branch: `advisor/005-scorelog-index`
- One commit; `perf(storage): …` style.
- Do NOT push or open a PR.

## Steps

### Step 1: Add the composite index to the ORM model

In `ScoreLog` (`models.py:435`), add a `__table_args__` after the columns:

```python
    __table_args__ = (
        Index("idx_score_logs_article_latest", "article_id", "calculated_at"),
    )
```

Confirm `Index` is already imported at the top of `models.py` (it is, given existing usage). The ordering `(article_id, calculated_at)` supports both the `group_by(article_id)` + `max(calculated_at)` and the join predicate.

**Verify:** `grep -n "idx_score_logs_article_latest" news_collector/storage/models.py` → 1 match.

### Step 2: Create the Alembic migration

Confirm the current head (`.venv/bin/alembic heads` → expect `a54ba7f7dabb`). Create `alembic/versions/<newhex>_add_score_logs_latest_index.py` with `down_revision` set to the confirmed head. Make it idempotent like the existing migrations:

```python
"""add score_logs latest index

Revision ID: <newhex>
Revises: a54ba7f7dabb
Create Date: 2026-06-12 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import inspect

revision: str = "<newhex>"
down_revision: Union[str, Sequence[str], None] = "a54ba7f7dabb"
branch_labels = None
depends_on = None

INDEX_NAME = "idx_score_logs_article_latest"

def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("score_logs")}
    if INDEX_NAME not in existing:
        op.create_index(INDEX_NAME, "score_logs", ["article_id", "calculated_at"])

def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("score_logs")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="score_logs")
```

Generate `<newhex>` to match the repo's style (12-hex like `a54ba7f7dabb`). **Do not** use `--autogenerate` blindly; write the migration explicitly as above so it only touches this index.

**Verify:** `.venv/bin/alembic heads` now shows your new revision as the single head, chained to `a54ba7f7dabb`.

### Step 3: Apply and test

**Verify:**
- `make migrate` → exit 0, applies the new migration.
- `.venv/bin/pytest tests/test_database_migrations.py tests/test_serving_api.py -q` → all pass.
- Index exists: `.venv/bin/python -c "import sqlalchemy as sa; from sqlalchemy import inspect, create_engine; e=create_engine('sqlite:///'+__import__('news_collector.config.settings',fromlist=['get_config']).get_config().database.path); print('idx_score_logs_article_latest' in {i['name'] for i in inspect(e).get_indexes('score_logs')})"` → `True`. (If this one-liner is awkward in your environment, instead assert presence via a small check in `tests/test_database_migrations.py`.)

## Test plan

- Extend `tests/test_database_migrations.py` (or add a focused test) asserting that after upgrade, `inspect(engine).get_indexes("score_logs")` contains `idx_score_logs_article_latest`. Model after the existing migration tests in that file.
- Verification: `make test` stays green.

## Done criteria

ALL must hold:

- [ ] `ScoreLog.__table_args__` includes `Index("idx_score_logs_article_latest", "article_id", "calculated_at")`
- [ ] A new Alembic migration exists, chained to the prior head, idempotent, with working `upgrade`/`downgrade`
- [ ] `make migrate` exits 0; `.venv/bin/alembic heads` shows a single head (the new one)
- [ ] A test asserts the index exists post-migration and passes
- [ ] `make test` exits 0; `make lint && make type` exit 0
- [ ] Only `models.py`, the new migration file, and (optionally) the migration test modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `.venv/bin/alembic heads` shows multiple heads before you start (the migration tree has an unmerged branch) — report it; merging heads is out of scope.
- The serving query in `api.py` has been rewritten and no longer groups on `score_logs` (drift) — the index may no longer be the right fix.
- `make migrate` fails on an unrelated pre-existing migration.

## Maintenance notes

- If the serving layer later switches to storing the latest score denormalized on `Article` (e.g. `final_score` already exists on `Article`), this subquery+index may become unnecessary — revisit then.
- A reviewer should confirm the migration is idempotent (safe to run on a DB that already has the index) and that `down_revision` matches the real prior head.
