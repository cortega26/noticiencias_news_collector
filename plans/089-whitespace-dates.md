# Plan 089: Treat whitespace-only dates as missing in publication identity derivation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/logic/workflows/publication_identity.py tests/decompose_refinery/test_publication_identity.py`
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

`_parse_date_like("   ")` returns `None` (missing), but `_derive_date` then
checks the *raw* value — `"   " not in (None, "")` — and raises
`UndatedArticleError` instead of falling through to `collected_date`. An
article with a blank-padded `published_date` and a perfectly good
`collected_date` fails publication with `E_IDENTITY_NO_DATE`. One-line
normalization fixes it, preserving the quarantine for genuinely unparseable
values. Publication identity stays deterministic (LAW-B5); only the
missing-vs-unparseable boundary moves to where the parser already says it is.

## Current state

The relevant files, each with one line on its role:

- `news_collector/logic/workflows/publication_identity.py` — identity resolver: `_parse_date_like` (lines 295-327), `_derive_date` (lines 329-352)
- `tests/decompose_refinery/test_publication_identity.py` — existing identity tests (extend; happy-path backfill/register tests at ~lines 459-483 show the pattern)

Excerpts of the code as it exists today:

`publication_identity.py:306-317` — the parser already treats whitespace as missing:

```python
if value is None or value == "":
    return None
...
text = value.strip()
if not text:
    return None
```

`publication_identity.py:338-348` — but the caller judges the raw value:

```python
for field in ("published_date", "collected_date"):
    raw = article.get(field)
    parsed = PublicationIdentityResolver._parse_date_like(raw)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d")
    if raw not in (None, ""):
        raise UndatedArticleError(
            article.get("id", "unknown"),
            field,
            detail=f"unparseable value {raw!r}",
        )
```

Repo conventions that apply here:

- LAW-B5: no clock, no randomness in identity; this change only reorders an existing deterministic fallback — no migration plan needed since no previously-successful identity changes value (whitespace-date articles previously hard-failed; they had no identity to preserve).
- Test pattern: pure-resolver tests with fake DB/manifest in `tests/decompose_refinery/test_publication_identity.py`.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/logic/workflows/publication_identity.py` (`_derive_date` only)
- `tests/decompose_refinery/test_publication_identity.py` (new cases only)

**Out of scope** (do NOT touch, even though they look related):

- `_parse_date_like` itself — already correct.
- The `collected_date`-missing quarantine and `UndatedArticleError` taxonomy — behavior preserved.
- Manual-ingest date inference (`manual_ingest.py:556-559`) — owned by plan 100.

## Git workflow

- Branch: `advisor/089-whitespace-dates`
- Conventional commits, e.g. `fix(identity): treat whitespace-only dates as missing`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Normalize before the missing check

In `_derive_date`, replace:

```python
if raw not in (None, ""):
```

with a strip-aware check:

```python
missing = raw is None or (isinstance(raw, str) and not raw.strip()) or raw == ""
if not missing:
```

i.e. raise `UndatedArticleError` only when the value is present *and*
non-blank-but-unparseable (the parser already returned `None` for it).
Whitespace now falls through to the next field exactly like `None`/`""`.

**Verify**: REPL probe —
`resolve`/`_derive_date({"published_date": "   ", "collected_date": "2026-09-01", "id": 1})` returns `"2026-09-01"`;
`_derive_date({"published_date": "   ", "collected_date": "   ", "id": 1})` raises `UndatedArticleError`;
`_derive_date({"published_date": "not-a-date", "collected_date": "2026-09-01", "id": 1})` still raises (genuinely unparseable is still a data problem, not a silent skip).

### Step 2: Add regression tests

In `tests/decompose_refinery/test_publication_identity.py`, following the existing resolver-test pattern:

1. whitespace `published_date` + valid `collected_date` → collected date used;
2. whitespace both → `UndatedArticleError`;
3. garbage `published_date` + valid `collected_date` → still raises (pins the preserved quarantine).

**Verify**: `.venv/bin/python -m pytest tests/decompose_refinery/test_publication_identity.py -q` → all pass including the 3 new tests.

### Step 3: Run the full gates

**Verify**: `make lint && make type && make test` → all exit 0.

## Test plan

- Three new resolver cases (fall-through, double-blank quarantine, garbage still quarantines).
- Existing identity suites (`test_publication_identity.py`, refinery engine workflow tests) stay green — no previously-successful identity may change value.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test` all exit 0
- [ ] New whitespace-date tests exist and pass
- [ ] `grep -n "if raw not in (None" news_collector/logic/workflows/publication_identity.py` → no matches
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Any existing test asserts that whitespace-only dates quarantine (that would make this a behavior dispute, not a bug — report it).
- The fix appears to require touching anything outside `_derive_date` + tests.

## Maintenance notes

- The sibling date parsers (`manual_ingest._parse_datetime`, `collector._from_iso_string`, `pipeline_e2e._parse_published`) still have divergent missing-vs-bad semantics — deliberately out of scope; unifying them needs a strict/lenient design first.
- Reviewers: confirm no fixture or golden file contains a whitespace date whose expected outcome was quarantine.
- **Deferred:** single date-coercion helper for all four parsers — unblocked, needs contract tests pinning each call site first.
