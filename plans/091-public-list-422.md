# Plan 091: Return 422 (not 500) for invalid public article-list queries

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/serving/api.py tests/test_serving_api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`GET /v1/articles?page_size=0`, `page_size=1000`, or `date_to < date_from`
today surfaces as a 500: `get_params` builds `ArticleListParams(...)` inside a
dependency, and the Pydantic `ValidationError` escapes FastAPI's 422 path
(which only applies to inline `Query` validation, as the admin routes use).
Client errors counted as server errors pollute error budgets and mislead API
consumers. After this plan, out-of-range public query params return 422 with a
stable envelope, matching the admin endpoints' existing behavior.

## Current state

The relevant files, each with one line on its role:

- `news_collector/serving/api.py` — `ArticleListParams` (lines 136-144+), `get_params` dependency (lines 721-736), admin inline-`Query` exemplar (~line 989: `Query(20, ge=1, le=50)`)
- `tests/test_serving_api.py` — stable-pagination tests (lines 154-172, extend)

Excerpts of the code as it exists today:

`news_collector/serving/api.py:143` — the model HAS bounds:

```python
page_size: int = Field(default=20, ge=1, le=50, alias="page_size")
```

`news_collector/serving/api.py:721-736` — but the dependency bypasses FastAPI's
422 mapping:

```python
def get_params(
    source: Optional[List[str]] = Query(None, alias="source"),
    topic: Optional[List[str]] = Query(None, alias="topic"),
    date_from: Optional[Any] = Query(None, alias="date_from"),
    date_to: Optional[Any] = Query(None, alias="date_to"),
    page_size: int = Query(20, alias="page_size"),
    cursor: Optional[str] = Query(None, alias="cursor"),
) -> ArticleListParams:
    return ArticleListParams(
        source=source,
        ...
    )
```

Repo conventions that apply here:

- Serving validates inputs explicitly (AGENTS.md §3.6); the admin routes' inline
  `Query(ge/le)` is the house pattern — copy it, don't invent a handler.
- LAW-B7: boundary validation failures raise explicit errors, never leak as 500s.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/serving/api.py` (`get_params` + `ArticleListParams` date-range validation only)
- `tests/test_serving_api.py` (new cases only)

**Out of scope** (do NOT touch, even though they look related):

- Admin endpoints — already correct; regression coverage only.
- Cursor validation (`nan`/`inf`) — separate unvetted item, do not bundle.
- Response envelope shapes — 422s use FastAPI's default detail envelope; do not customize it.

## Git workflow

- Branch: `advisor/091-public-list-422`
- Conventional commits, e.g. `fix(serving): return 422 for invalid public list queries`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.
Also reproduce the bug first: via TestClient, `GET /v1/articles?page_size=0`
and `?page_size=1000` — record the actual status codes (expected: 500 today).

**Verify**: reproduction shows non-422 codes on the unmodified checkout.

### Step 1: Read the date-range validator, then fix both layers

1. Read `ArticleListParams` fully (lines 136-200): find the date-range check
   (~lines 178-183 per audit) and confirm which exception type it raises.
2. Minimal fix in `get_params`:
   - `page_size: int = Query(20, ge=1, le=50, alias="page_size")` (mirrors the admin exemplar at ~line 989).
   - Wrap the `ArticleListParams(...)` construction in `try/except ValidationError`
     (import from pydantic) and `raise HTTPException(status_code=422, detail=str(exc))`
     — this covers date-range and any future model-level rule in one place.
   - `from pydantic import ValidationError` — note the module already lazy-loads pydantic via `get_pydantic_module()` (lines 126-133); use that same accessor for `ValidationError`, do not add a top-level pydantic import that breaks the compat shim.

**Verify**: reproduction from Step 0 now returns 422 for all cases; valid requests unchanged. `make lint` → exit 0.

### Step 2: Add parametrized tests

In `tests/test_serving_api.py`:

```python
@pytest.mark.parametrize("page_size", [0, -1, 51, 1000])
def test_public_list_rejects_out_of_range_page_size(client, page_size):
    resp = client.get("/v1/articles", params={"page_size": page_size})
    assert resp.status_code == 422
```

plus `date_to < date_from` → 422, and one valid-boundary case (`page_size=50` → 200)
to pin the edge. Model the client fixture on neighboring tests in the file.

**Verify**: `.venv/bin/python -m pytest tests/test_serving_api.py -q` → all pass including new tests.

### Step 3: Run the full gates

**Verify**: `make lint && make type && make test` → all exit 0.

## Test plan

- New parametrized 422 cases (page_size 0/-1/51/1000, inverted dates) + valid-edge 200 case.
- Existing pagination tests (lines 154-172) and perf structural gate stay green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test` all exit 0
- [ ] `GET /v1/articles?page_size=0`, `=1000`, and inverted dates all return 422 (pinned by tests)
- [ ] No new top-level pydantic import bypassing `get_pydantic_module()`
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step 0 reproduction does NOT show 500s (behavior already changed — report actuals).
- The date-range validator lives somewhere other than `ArticleListParams` and catching `ValidationError` doesn't cover it.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If new query params gain model-level rules, they inherit the 422 mapping for free via the `get_params` wrapper — keep it.
- Reviewers: confirm the 422 detail doesn't leak internals (pydantic messages are field-scoped; acceptable per current error policy, unlike the 500-path stack traces).
- **Deferred:** cursor `nan`/`inf` rejection — needs an SQLite semantics check first.
