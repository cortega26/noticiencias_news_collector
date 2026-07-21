# Plan 002: Make publication-identity recovery date deterministic (remove `datetime.now()` fallback)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If a
> "STOP condition" occurs, stop and report — do not improvise. When done,
> update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- news_collector/logic/workflows/publication_identity.py`
> If the file changed, compare the "Current state" excerpt against the live
> code before editing; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

CLAUDE.md states: *"Publication identity must be deterministic and idempotent — no runtime time/randomness in slugs, filenames, or canonical URLs."* The filesystem-recovery branch of `resolve()` violates this. When an existing post file is found but its slug has **no parseable date prefix**, the code falls back to `datetime.now()` for the canonical date. That means re-resolving the *same* article on a different day produces a *different* `canonical_date` — a non-deterministic identity, which is exactly the idempotency break the rule forbids. (Note: this is **not** a timezone bug — switching the fallback to UTC would still be non-deterministic. The fix is to never derive identity from "now" on the recovery path.)

## Current state

- `news_collector/logic/workflows/publication_identity.py` — owns publication identity resolution. The `resolve()` method has three priorities (docstring at lines 70–74): P1 DB canonical slug, P2 filesystem recovery, P3 creation mode.

The defective line is in the **P2 filesystem-recovery** branch:

```python
# publication_identity.py:88-100 (P2 — FS scan)
existing_file = self._manifest.find_existing_file(posts_dir, article_id)
if existing_file:
    logger.info("♻️ Idempotency: Found existing file {}", existing_file.name)
    fn = existing_file.name
    slug = fn.replace(".md", "")
    canonical_date = self._date_from_slug(slug) or datetime.now().strftime(  # <-- line 94, the bug
        "%Y-%m-%d"
    )
    # Self-heal: write slug into DB
    self.backfill_slug(article_id, slug)
    return PublicationIdentity(
        final_slug=slug,
        ...
    )
```

Key facts:
- The slug here comes from an **existing post filename** that was already published. Its date should come from that filename. If `_date_from_slug(slug)` returns `None`, the filename is malformed and falling back to today's date silently invents a wrong, time-dependent date.
- `_date_from_slug` (lines 256–258) parses a leading `YYYY-MM-DD` from the slug via regex and returns `str | None`.
- For contrast, P1 (DB branch, lines 77–86) already **requires** a parseable date: `if db_slug and canonical_date:` — it only locks identity when the date is present. The P2 branch should be equally strict.
- The P3 creation branch's use of `datetime.now(timezone.utc)` (in `_publication_date`, line 267) is **by design** (creation mode = "publish today") and must NOT be changed.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Single test file | `.venv/bin/pytest tests/<identity test> -q` | all pass |
| Lint | `make lint` | exit 0 |
| Type | `make type` | exit 0 |
| Full fast suite | `make test` | all pass |

(Find the existing identity test first: `find tests -iname '*publication_identity*' -o -iname '*identity*'`.)

## Scope

**In scope:**
- `news_collector/logic/workflows/publication_identity.py` (the P2 branch only)
- the existing publication-identity test file (add a regression test)

**Out of scope:**
- The P3 creation branch / `_publication_date()` — its `datetime.now(timezone.utc)` is intentional.
- `backfill_slug()` behavior — handled separately; do not change it here.
- The DB (P1) branch.

## Git workflow

- Branch: `advisor/002-identity-deterministic-date`
- One commit; `fix(identity): …` style.
- Do NOT push or open a PR.

## Steps

### Step 1: Decide the deterministic fallback

Replace the `datetime.now()` fallback on line 94 with a **deterministic** source, in this preference order:

1. If `_date_from_slug(slug)` returns a date → use it (unchanged, the happy path).
2. If it returns `None` → derive the date from a stable, already-known source rather than "now". The article's stored `collected_date`/`published_date` is the correct deterministic anchor (it is what P3 creation mode itself prefers, per the line 72 docstring "source date, collected date, then now()").

Look at how the class already reaches article data (e.g. `self._get_db_slug(article_id)` at line 77 shows there is a DB accessor `self._db`). Determine whether a stored article date is reachable from here. **If a deterministic article date is reachable**, use it. **If it is NOT reachable without new I/O wiring**, prefer the safe fail-loud option in Step 2 instead of inventing a date.

### Step 2: Implement — fail loud rather than invent a date

If no deterministic date is available for a malformed recovered filename, do **not** fabricate one. Raise a clear error so the malformed file surfaces instead of being silently mis-dated:

```python
canonical_date = self._date_from_slug(slug)
if canonical_date is None:
    raise ValueError(
        f"Recovered post file '{fn}' for article {article_id} has no "
        f"parseable date prefix; refusing to invent a non-deterministic date."
    )
```

This keeps identity deterministic: a given on-disk filename always yields the same date, and an unparseable one fails fast instead of producing day-dependent output. (If Step 1 found a reachable deterministic article date, you may use that instead of raising — either is acceptable as long as the result does not depend on the wall clock.)

**Verify:** `grep -n "datetime.now()" news_collector/logic/workflows/publication_identity.py` → the only remaining match (if any) is inside `_publication_date`/P3 creation mode, NOT in the P2 branch around line 94.

### Step 3: Add a regression test

In the existing identity test file, add a test that exercises the P2 recovery branch with a **dateless** filename (e.g. `some-article-without-date.md`) and asserts the new behavior (raises `ValueError`, or returns the deterministic article date if you implemented Step 1). Add a second test asserting a **well-formed** recovered filename (`2026-01-15-some-slug.md`) still returns `canonical_date == "2026-01-15"` and `is_new=False`. Model structure after the existing tests in that file.

**Verify:** `.venv/bin/pytest tests/<identity test> -q` → all pass, including the 2 new tests.

## Test plan

- New tests (in the existing identity test module):
  - `test_p2_recovery_dateless_filename_is_deterministic` — dateless recovered file does not produce a `now()`-based date (raises, or returns stored date).
  - `test_p2_recovery_dated_filename_uses_slug_date` — `2026-01-15-foo.md` → `canonical_date == "2026-01-15"`.
- Pattern to follow: the existing identity tests (locate via `find tests -iname '*identity*'`).
- Verification: `make test` → all pass.

## Done criteria

ALL must hold:

- [ ] No `datetime.now()` in the P2 recovery branch of `publication_identity.py` (it may remain only in `_publication_date`/P3)
- [ ] **Preference honored**: if a stable stored article date (`collected_date`/`published_date`) is reachable from the P2 branch, it is used; raising `ValueError` is the **last resort only** when no deterministic date is reachable (raising turns a previously-tolerated dateless file into a hard recovery failure, so prefer deriving)
- [ ] `make type` exits 0
- [ ] `make test` exits 0; the 2 new identity tests exist and pass
- [ ] Only `publication_identity.py` and the identity test file modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The live code around line 94 no longer matches the excerpt (drift).
- Making the fallback deterministic appears to require new DB I/O wiring into a module that is supposed to stay I/O-light — report the options rather than adding broad new I/O.
- A test reveals that some caller actually relies on the `now()` fallback (e.g. an existing test asserts today's date for a dateless slug) — report it; do not weaken your fix to satisfy a test that encodes the bug.

## Maintenance notes

- If a future change lets P2 recovery reach the stored article date cheaply, prefer returning that over raising.
- A reviewer should confirm P3 creation-mode dating is untouched and that the new behavior is covered by both a positive and a negative test.
