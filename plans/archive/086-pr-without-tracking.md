# Plan 086: Fail closed before creating PRs for title-fallback (non-DB) articles

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/logic/workflows/pr_orchestrator.py news_collector/logic/workflows/refinery_engine.py tests/unit/logic/workflows/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

When an article has no DB id, `RefineryEngine` falls back to the article title
as its identity, and `pr_orchestrator` then **creates a real GitHub PR** before
discovering `int(article_id)` raises `ValueError` — at which point it merely
logs and skips `mark_article_published`. The result is a live PR with no
`publishing` row: webhook callbacks can never correlate it, `is_in_flight`
stays false, and a retry opens a duplicate PR. After this plan, non-numeric
identities are rejected before any git side effect, or tracked end-to-end —
never published-then-orphaned.

## Current state

The relevant files, each with one line on its role:

- `news_collector/logic/workflows/pr_orchestrator.py` — creates the PR, then tries to record DB state (lines 98-121)
- `news_collector/logic/workflows/refinery_engine.py` — `_resolve_article_identity`, title fallback with loud warning (lines 90-105)
- `news_collector/storage/article_repository.py` — `mark_article_published` (DB tracking the PR path skips)

Excerpts of the code as it exists today:

`news_collector/logic/workflows/pr_orchestrator.py:98-119` — the side effect
precedes the numeric check:

```python
pr_url = git.create_pull_request(
    repo_url=repo_url,
    branch_name=branch_name,
    title=f"News: {output_filename.replace('.md', '')}",
    body=pr_body,
)

if pr_url:
    logger.info("Pull Request created successfully: {}", pr_url)
    try:
        numeric_id = int(article_id)
        # article_id here is the same value refinery_engine's
        # _resolve_article_identity() writes into the committed
        # post's `refinery_id` frontmatter field ...
        self._db.mark_article_published(numeric_id, pr_url, article_id)
    except ValueError:
        logger.warning(
            "Could not mark non-numeric ID {} in main DB. Skipping state update.",
            article_id,
        )
```

`news_collector/logic/workflows/refinery_engine.py:97-105` — the fallback is
knowingly uncorrelated:

```python
article_pk = article.get("id")
if article_pk not in (None, ""):
    return str(article_pk)
logger.warning(
    "Article has no DB id; falling back to title for refinery_id "
    f"(title={article.get('title')!r}). This article won't correlate "
    "reliably with frontend publication callbacks."
)
return str(article.get("title", "unknown"))
```

Repo conventions that apply here:

- LAW-B5: publication identity must be deterministic and idempotent; a PR with
  no persisted correlation key breaks retry idempotency (duplicate PRs).
- LAW-B6: batch/single workflows must fail explicitly — a warning log after an
  irreversible side effect is not explicit failure handling.
- Error handling (LAW-B7): validate at the boundary before I/O, don't catch
  after it.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/logic/workflows/pr_orchestrator.py`
- `news_collector/logic/workflows/refinery_engine.py` (only if the chosen approach needs the identity boundary moved; prefer orchestrator-only)
- `tests/unit/logic/workflows/` (new/updated tests for the orchestrator)

**Out of scope** (do NOT touch, even though they look related):

- `news_collector/storage/*` — no schema/migration work in this plan.
- Webhook correlation logic — it works correctly for tracked PRs; not under review.
- The title-fallback identity itself — removing it is a larger decision; this plan only stops it from producing untracked PRs.

## Git workflow

- Branch: `advisor/086-pr-without-tracking`
- Commit per step; conventional commits, e.g. `fix(publish): fail closed on non-numeric article id before PR creation`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Map every caller that can pass a non-numeric id

Grep for callers of the orchestrator method containing the `create_pull_request`
call (start in `pr_orchestrator.py`, follow into `refinery_engine.py`):

- `grep -rn "create_pull_request\|mark_article_published" news_collector/ | grep -v test`
- For each caller, determine: can `article_id` be a title string here (via
  `_resolve_article_identity` fallback), or is it always a DB pk?
- Check `tests/unit/logic/workflows/test_refinery_engine.py` and any
  orchestrator tests for non-numeric-id cases asserting a PR *is* created.

**Verify**: you can list every production path reaching `create_pull_request`
with a possibly-non-numeric id, with file:line for each. If a live supported
flow (non-test) *depends* on creating PRs for title-fallback articles, that is
a STOP condition — report it instead of breaking the flow (the fix then becomes
persisting an alternate correlation key end-to-end, a bigger design change).

### Step 2: Fail closed before the git side effect

In `pr_orchestrator.py`, at the top of the publish method (before any branch/file
work, and strictly before `git.create_pull_request`):

```python
try:
    numeric_id = int(article_id)
except (TypeError, ValueError) as exc:
    raise <existing workflow error type for invalid identity> from exc
```

- Use the module's existing error type for invalid publication input (do not invent a new exception class; check what the method already raises for bad inputs and reuse it).
- Remove the now-dead `try/except ValueError` around `mark_article_published` (it becomes unreachable); keep the explanatory comment about the refinery_id correlation.
- Keep logging: an error-level log naming the article id, since this is now a hard failure.

**Verify**: `make lint` → exit 0; `grep -n "Could not mark non-numeric" news_collector/logic/workflows/pr_orchestrator.py` → no matches.

### Step 3: Add regression tests

In `tests/unit/logic/workflows/` (new file `test_pr_orchestrator_identity.py`
or the existing orchestrator test file if one fits — check first):

1. Fake `git` (object with `create_pull_request` recording calls) + fake `_db`: call with `article_id="Some Title"` → assert `create_pull_request` was **never called** and the invalid-identity error is raised.
2. Same setup with `article_id="123"` → PR created and `mark_article_published(123, pr_url, "123")` called (pins the happy path against over-correction).

**Verify**: `.venv/bin/python -m pytest tests/unit/logic/workflows/ -q` → all pass, including the 2 new tests.

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries` → all exit 0.

## Test plan

- New tests: non-numeric id → no PR side effect + explicit error; numeric id → PR + DB mark (guards the fix against breaking the normal path).
- Existing suites `tests/unit/logic/workflows/test_refinery_engine.py`,
  `test_publication_run_workflow.py`, `test_collection_run_workflow.py` must stay green (they exercise adjacent identity paths).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` all exit 0
- [ ] New identity tests exist and pass
- [ ] `grep -rn "Skipping state update" news_collector/` → no matches (dead path removed)
- [ ] No `create_pull_request` call is reachable with a non-numeric id (reviewer confirms via Step 1 caller list)
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step 1 finds a live, non-test flow depending on title-fallback PR creation.
- The method's existing error taxonomy has no suitable error type and adding one would cross package boundaries (report the options instead of inventing an exception).
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require storage-schema or webhook changes.

## Maintenance notes

- If title-fallback publishing is ever made legitimate, it needs a persisted alternate correlation key (`refinery_id` string column or equivalent) wired through `mark_article_published`, the frontmatter writer, and `webhook_handler` matching — that is a follow-up design, not a tweak.
- Reviewers: scrutinize that the fail-closed check sits before ALL side effects (branch creation, file writes), not just before `create_pull_request`.
- **Deferred:** end-to-end string-`refinery_id` correlation support — unblocked by nothing technical, needs a product decision that untracked PRs should exist at all.
