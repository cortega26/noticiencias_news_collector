# Plan 128: Backend hygiene (fetch ownership, env threading, signal-preserving errors, dead code)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/utils/full_text.py news_collector/logic/workflows/pipeline_e2e.py news_collector/serving/api.py news_collector/scoring/cognitive_scorer.py news_collector/utils/refinery_helper.py news_collector/utils/logger.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

Six small hygiene defects, each a LAW violation with a mechanical fix:
HTTP transport living in `utils/` where policy modules can't stay
network-free; workflow code mutating `os.environ` (order-dependent,
parallel-unsafe, leakable on exceptions); a display-only DB lookup that
renders blank audit states instead of an error banner (editors approve
believing no audit ran); a naive wall-clock log line amid UTC-aware code;
a zero-importer helper misleading discovery; and an overgrown logger whose
home is a judgment call. None changes behavior for legitimate paths; all
make the next change safer. Move-only + logging-only + deletion, fully
test-covered.

## Current state

Facts (all verified 2026-10-11):

```python
# utils/full_text.py:1-30 — transport in utils (LAW-B8/B4 breach)
import requests
from bs4 import BeautifulSoup
...
def fetch_full_article(url, session=None):
    browser_headers = {"User-Agent": "Mozilla/5.0 ... Chrome/91.0..."}
    validate_url_safety(url)   # SSRF gate present (CRIT-01) — preserve it in the move
    response = session.get(url, timeout=15, ...) or requests.get(url, timeout=15, ...)
```

```python
# logic/workflows/pipeline_e2e.py:693,716,791,804 — env mutation in workflow (LAW-B4)
os.environ["NOTICIENCIAS_SMOKE"] = "1"
...
os.environ["NOTICIENCIAS_SMOKE"] = previous_smoke   # save/restore leaks on exceptions between
# file is 1,021 lines (second-largest workflow)
```

```python
# serving/api.py:581-602 — silent empty fallback (LAW-B7 breach)
def _quality_audit_states(session, article_ids):
    """... Never raises — audit visibility must not break the review page."""
    ...
    try:
        rows = (session.query(...).all())
    except Exception:
        return {}   # DB failure renders as blank states
```

```python
# scoring/cognitive_scorer.py:46 — naive log timestamp vs repo UTC convention
print(f"{datetime.now().strftime('%H:%M:%S')} | DEBUG: CognitiveScorer INITIALIZED ...")
# same file :273,708 use datetime.now(timezone.utc); convention: utils/datetime_utils.py
```

```python
# utils/refinery_helper.py:1-18 — has_no_activity, ZERO importers repo-wide
# (grep for `refinery_helper` = 0 hits outside the file itself — verify again at Step 0)
```

```python
# utils/logger.py:1-547 — 547-line loguru/redaction subsystem (_SECRET_PATTERN at :32-34,
# config via config.settings at :25) living under utils/ while docs/ARCHITECTURE.md
# gives observability/ its own package. Judgment call, not a violation with teeth.
```

Repo conventions: LAW-B4 (env at bootstrap boundaries), LAW-B7 (narrow
catches, log with context, never `except Exception: pass`-equivalents),
LAW-B8 (narrow utils), LAW-B9 (no new abstractions — all fixes here are
moves/deletions, no new layers).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Boundaries | `make test-boundaries`  | declared   | pass                |

## Scope

**In scope** (the only files you should modify):

- `news_collector/utils/full_text.py` → move to `news_collector/collectors/full_text.py`
  (keep a compat re-export ONLY if callers outside collectors exist — check first)
- `news_collector/logic/workflows/pipeline_e2e.py` (explicit `smoke: bool`
  threading; CLI entry reads env once) + the CLI entry file(s) that set it
- `news_collector/serving/api.py` (`_quality_audit_states` narrow catch +
  unavailable flag ONLY — no other serving changes)
- `news_collector/scoring/cognitive_scorer.py` (one-line timestamp)
- `news_collector/utils/refinery_helper.py` (delete + its test if one exists)
- `news_collector/utils/logger.py` (move to `observability/` with compat
  re-export, OR record "stays by decision" — either is an acceptable outcome)
- `tests/` for the behavior-pinning cases

**Out of scope** (do NOT touch, even though they look related):

- Retry/timeout/transport policy changes in the moved fetch code — move verbatim.
- Pipeline_e2e decomposition (1,021 lines) — env threading only.
- Any other `except Exception` in the repo (report the census in the
  commit message if you take one; don't expand scope).

## Git workflow

- Branch: `advisor/128-backend-hygiene`
- Commit per item (6 small commits).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline + import census

Run `make lint && make type && make test`. Census: `grep -rn "full_text import\|from news_collector.utils.full_text\|refinery_helper" news_collector/ apps/ scripts/ tests/ tools/` — record all importers of both modules (decides re-export need + confirms zero-importer claim).

**Verify**: gates green; importer lists recorded.

### Step 1: Move fetch_full_article to collectors/

Move to `news_collector/collectors/full_text.py` verbatim (winner:
ingestion edge owns fetching; keep the `validate_url_safety` call and the
UA header exactly). Keep pure HTML→text extraction in `utils/` only if a
second consumer needs it (if not, move the whole module). Compat
re-export in `utils/` only if Step-0 census shows external importers.

**Verify**: `make test-boundaries` passes; importer census post-move shows
only the new path (+ shim if kept).

### Step 2: Thread smoke explicitly

`scripts/` entry parses env → typed `smoke: bool` param once; delete all
four `os.environ` writes in `pipeline_e2e.py`; pass the param through the
call chain. Exception paths must not leak the flag (no global to leak —
prove by a test that raises mid-run and asserts env untouched).

**Verify**: e2e tests pass; env-untouched-on-exception test passes.

### Step 3: Surface audit-state outages

Catch `SQLAlchemyError` narrowly (log with `exc_info`), return partial
states + an `audit_states_unavailable: True` flag so the GUI shows a
warning banner instead of silent blanks. Keep the page rendering (the
"must not break the review page" requirement stands — only the silence goes).

**Verify**: test with a broken session asserts flag + partial states (not
`{}`); `make test-boundaries` passes.

### Step 4: One-line timestamp + dead-code deletion

1. `cognitive_scorer.py:46` → `datetime.now(timezone.utc)` (match file convention).
2. Delete `refinery_helper.py` (+ its test if present) after re-confirming
   zero importers.

**Verify**: `grep -rn "refinery_helper" news_collector/ apps/ scripts/ tests/`
empty; `make test` passes.

### Step 5: Logger home decision

Either move to `observability/` with a compat re-export (all importers
updated, `make test` green) or record "stays in utils by decision" with a
one-line comment at the top of `logger.py` so future audits stop
re-flagging it. Both outcomes close the item — pick by churn cost (if
importer count > 30, prefer the comment; record the count).

**Verify**: `make lint && make type && make test` green either way.

## Test plan

- Import-path tests (new location importable; shim works if kept).
- Env-untouched-on-exception test.
- Audit-unavailable flag test (broken session → flag, no `{}`).
- Timestamp: grease test asserting UTC-aware (or no test if the line is
  print-only — then the diff itself is the evidence; say so).
- Verification: `make test` + `make test-boundaries` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `news_collector/collectors/full_text.py` exists; `grep -rn "requests.get\|session.get" news_collector/utils/full_text.py` N/A (file moved or shim-only)
- [ ] `grep -n 'os.environ\["NOTICIENCIAS_SMOKE"\]' news_collector/logic/workflows/pipeline_e2e.py` returns no matches
- [ ] `grep -n "except Exception:" news_collector/serving/api.py` at the audit-states site replaced by narrow catch + flag
- [ ] `refinery_helper.py` deleted (or its zero-importer status disproven and reported)
- [ ] Logger decision recorded (moved OR comment)
- [ ] `make lint && make type && make test && make test-boundaries` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- `refinery_helper` HAS importers (claim disproven — keep the file, report).
- The smoke param threads through an impractical call chain (report depth;
  a context object is acceptable, a framework is not).
- Moving the logger breaks >30 importers (take the comment outcome).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- New network code uses `httpx` unless it needs curl_cffi stealth or a
  real browser (four-client overlap stays by decision — DEP note in the
  index; don't consolidate).
- `os.environ` writes outside `scripts/`/bootstrap are a review rejection
  per LAW-B4.
- **Deferred:** wider `except Exception` census (report-only here) —
  each site needs its own judgment; unblocked by nothing.
