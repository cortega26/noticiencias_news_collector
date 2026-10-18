# Plan 148: Stop paying for data the response never uses

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- news_collector/serving/api.py news_collector/collectors/rss_collector.py news_collector/collectors/base_collector.py news_collector/storage/article_repository.py news_collector/logic/workflows/source_catalog_workflow.py tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Three read-path wastes, each independently verifiable and small:

1. **`GET /v1/articles/{id}/related` hydrates full article rows to return four
   fields.** It queries the whole ORM entity (`content` Text,
   `article_metadata` JSON, `keywords`, `authors`, …) with `limit(20)` and keeps
   only id/title/source/url/final_score. On the production-shaped DB the average
   `content` is ~5.7 KB (max ~120 KB) and `article_metadata` ~2.4 KB (max
   ~192 KB), so a request reads ~114 KB–2.4 MB off disk and instantiates it,
   none of which is serialized. The same file already established the projection
   discipline for list endpoints (`_build_article_payload`'s docstring:
   "no full ORM hydration", `api.py:390-395`).
2. **Admin read endpoints re-read and re-parse static files on every request.**
   `GET /v1/admin/config` → `load_config()` (re-reads `config.toml` + `.env`,
   deep-copies defaults, re-validates the full pydantic model);
   `GET /v1/admin/prompts` → `yaml.safe_load` of the 45 KB `prompts.yaml`;
   `GET /v1/admin/sources` → re-read + parse of the 31 KB `sources.yaml`;
   `GET /v1/admin/sources/health` → `json.load` of the 78 KB export. Each is a
   page-load cost for files that only change when an operator saves them.
3. **The RSS cycle performs the URL-existence lookup twice per source.** The
   collector computes `existing_urls` over all feed entries to filter duplicates,
   then `_filter_and_save_articles` recomputes `articles_exist` for the admitted
   candidates. That is one redundant canonicalization + chunked `IN` query per
   source per cycle, on the same DB the collection is writing to (plan 092
   batched the per-item lookups; this is the residue between the two call sites).

## Current state

- `news_collector/serving/api.py:1292-1304`:

```python
            related = (
                session.query(Article)
                .filter(
                    Article.cluster_id == article.cluster_id,
                    Article.id != article_id,
                )
                .order_by(
                    func.coalesce(Article.final_score, 0.0).desc(),
                    Article.id.desc(),
                )
                .limit(20)
                .all()
            )
```

  reduced at `:1305-1316` to `RelatedArticleResponse` (`:281-287`).
- `api.py:1613-1617` (`GET /v1/admin/config` → `load_config()`);
  `:2212-2226` (`GET /v1/admin/prompts` → `yaml.safe_load`);
  `:2080` → `logic/workflows/source_catalog_workflow.py:241-251` (sources.yaml);
  `:1579-1598` (`GET /v1/admin/sources/health` → `json.load` of
  `ADMIN_SOURCE_HEALTH_PATH`).
- `news_collector/collectors/rss_collector.py:839-841`:

```python
        existing_urls = self.db_manager.articles_exist(
            [cand["url"] for cand in candidates]
        )
```

  …then the candidate loop filters by `(canonicalize_url(cand["url"]) or cand["url"]) in existing_urls`
  (`:862`), and `collect_from_source` calls the base collector's save path, which
  recomputes the same set at `news_collector/collectors/base_collector.py:998-1008`.
- `news_collector/storage/article_repository.py:256-279` — `articles_exist`
  canonicalizes every URL and issues chunked (`CHUNK_SIZE=500`) `IN` queries.

## Commands you will need

| Purpose          | Command                                                       | Provenance | Expected on success            |
|------------------|---------------------------------------------------------------|------------|--------------------------------|
| Install/baseline | `make bootstrap`                                              | declared   | exit 0                         |
| Lint             | `make lint`                                                   | declared   | exit 0                         |
| Types + coverage | `make type`                                                   | declared   | exit 0                         |
| Unit suite       | `make test`                                                   | declared   | all pass                       |
| Perf suite       | `make perf`                                                   | declared   | pass/skip per plan 097 rules   |
| Focused tests    | `.venv/bin/pytest tests/test_serving_api.py tests/unit/collectors -q --no-cov` | declared | all pass        |
| Ledger           | `make plans-ledger-check`                                     | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared`.

## Scope

**In scope**:

- `news_collector/serving/api.py` — the related endpoint's projection + a small
  mtime/size-keyed cache for the three static reads
- `news_collector/logic/workflows/source_catalog_workflow.py` — only if the cache
  belongs there instead
- `news_collector/collectors/rss_collector.py` and `collectors/base_collector.py`
  — pass the already-computed set through
- `tests/` — statement-shape and cache tests

**Out of scope** (do NOT touch):

- Ranking/pagination semantics of any endpoint (ordering and limits stay
  byte-identical).
- `storage/article_repository.py`'s `articles_exist` implementation.
- The serving `dashboard_health`/triage paths.
- Adding a caching framework or dependency (LAW-B9): a module-level dict with an
  mtime+size key is the whole mechanism.

## Git workflow

- Branch: `advisor/148-read-path-wins`
- One commit per item; conventional commits, e.g.
  `perf(serving): project only the fields /related returns (plan 148)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, `make test`. Red baseline → STOP.

**Verify**: every command matches its expected result.

### Step 1: Project the related-articles query

1. Replace `session.query(Article)` with an explicit column selection
   (`Article.id`, `Article.title`, `Article.source_id`, `Article.source_name`,
   `Article.url`, `Article.final_score`) keeping the exact filter/order/limit.
   Follow the projection style the file already uses for list endpoints.
2. Keep the response model and its field defaults unchanged.

**Verify**: `.venv/bin/pytest tests/test_serving_api.py -q --no-cov` → all pass;
add a statement-shape test (below) proving `content` is not selected, modelled on
`tests/perf/test_serving_api_perf.py`.

### Step 2: Cache the three static admin reads

3. Add one small module-level helper (local to `serving/api.py` or a tiny
   module beside it) that caches a parsed file keyed by
   `(path, st_mtime_ns, st_size)` and returns the cached object when unchanged.
   Use it for: `prompts.yaml`, `sources.yaml`, and the source-health export JSON.
4. For `GET /v1/admin/config`, prefer the smallest correct change: cache
   `load_config()`'s result keyed on `config.toml` + `.env` mtimes **only if**
   `load_config` is deterministic and side-effect-free enough to reuse (read
   `noticiencias/config_manager.py:478-533` first). If its result is mutable
   shared state (callers can mutate the returned config), return a deep copy or
   skip this sub-item and say so — do not hand out shared mutable state.
5. Invalidate by key comparison only — no background threads, no TTLs, no new
   dependency.

**Verify**: `make test` → green; a new test proving two consecutive GETs read the
file once (e.g. monkeypatch `Path.read_text` with a counter, or assert on a
cache-hit marker you add to the helper) and that an operator save is visible on
the next GET.

### Step 3: Hoist the duplicate existence lookup

6. Have `_extract_articles_from_feed` (or the caller) hand the already-computed
   `existing_urls` set to the save/filter path (`_filter_and_save_articles`)
   through an explicit parameter, keeping the current fallback behaviour when the
   parameter is absent (the base collector may be used by other collectors —
   check `grep -rn "_filter_and_save_articles" news_collector/` first).
7. Preserve the exact membership semantics: canonicalized-URL comparison
   (`canonicalize_url(u) or u`), which both sites rely on today.

**Verify**: `.venv/bin/pytest tests/unit/collectors -q --no-cov` → all pass; a new
boundary test asserting `articles_exist` is called exactly once per RSS source
cycle.

## Test plan

- `tests/test_serving_api.py` (or a new focused file): related-endpoint response
  shape unchanged (ids, order, fields) + statement-shape assertion that
  `content`/`article_metadata` are not selected (model after
  `tests/perf/test_serving_api_perf.py`'s statement counting).
- Admin cache: read-once test + visible-after-save test (write a temp config/
  prompts file through the existing tmp_path fixtures).
- Collector: single-call test for `articles_exist` per cycle.

**Verify**: `make test && make perf` → green, plus the new tests.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make perf` exit 0
- [ ] Statement-shape test proves the related query selects no large columns
- [ ] Cache test proves a second GET does not re-read the file, and a save is visible
- [ ] Collector test proves one existence lookup per source cycle
- [ ] No response shape, ordering, or pagination change (tests unchanged except additions)
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 148 updated; `make plans-ledger-check` → OK

## STOP conditions

- The excerpts do not match the live code (drift).
- `load_config()` returns shared mutable state and copying it is non-trivial →
  skip that sub-item, keep the other caches, and report.
- The `_filter_and_save_articles` signature is used by collectors whose URL
  semantics differ → do not change the shared signature; pass an optional
  parameter and report.
- Any existing serving test needs its expectations changed → STOP and report
  (it would mean the projection changed behaviour).

## Maintenance notes

- The cache key must include mtime **and** size (mtime granularity on some
  filesystems is coarse). If an operator edits a file without changing size
  within the same mtime tick, the old value persists — acceptable for these
  read-only admin views; say so in the helper's docstring.
- Reviewer should scrutinise: no shared mutable config object leaks to callers,
  and the collector change preserves canonicalized-URL semantics.
- **Deferred:** the batch-hoist of `/v1/admin/*` dashboard aggregates and the SQL
  score histogram (a recorded earlier deferral). Unblocked by a product decision.
