# Plan 094: Unify slug extraction behind `PublicationIdentityResolver`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/logic/workflows/refinery_engine.py news_collector/logic/workflows/publication_identity.py tests/decompose_refinery/test_publication_identity.py tests/unit/logic/workflows/test_refinery_engine.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`RefineryEngine._extract_slug` is a line-for-line duplicate of
`PublicationIdentityResolver.extract_slug` — same regexes, same fallback, same
`NC-BE-015` sanitize guard. A sanitization fix (like the guard itself once was)
must land in two places or canonical slugs/filenames diverge by workflow path,
violating LAW-B5 identity determinism. After this plan there is exactly one
slug-extraction implementation.

## Current state

The relevant files, each with one line on its role:

- `news_collector/logic/workflows/publication_identity.py` — canonical `extract_slug` (lines 253-279)
- `news_collector/logic/workflows/refinery_engine.py` — duplicate `_extract_slug` (lines 928-947)

Excerpts (both read in full — identical logic):

Resolver `publication_identity.py:253-279`:

```python
@staticmethod
def extract_slug(content: str, fallback_id: str) -> str:
    """
    Extract slug from frontmatter 'slug:' or 'title:' field.

    Applies NFKD normalisation, ASCII encode, special-char sanitise, and dedash.
    This is a pure function — no I/O.
    """
    slug = None

    if "slug:" in content:
        match = re.search(r'slug:\s*"?([^"\n]+)"?', content)
        ...
    # NC-BE-015 S0 GUARD: strict sanitise
    slug = slugify(slug, fallback=f"article-{fallback_id}")

    return slug
```

Engine `refinery_engine.py:928-947`:

```python
def _extract_slug(self, content: str, fallback_id: str) -> str:
    """Extracts slug from frontmatter or generates fallback."""
    slug = None
    if "slug:" in content:
        match = re.search(r'slug:\s*"?([^"\n]+)"?', content)
        ...
    # --- NC-BE-015 S0 GUARD: Strict sanitize ---
    slug = slugify(slug, fallback=f"article-{fallback_id}")

    return slug
```

Repo conventions that apply here:

- LAW-B2: structural/normalization mapping has one choke point; LAW-B5: identity derivation must not diverge by path.
- Pure functions: both are I/O-free, so replacement is behavior-verifiable by unit tests alone.
- Existing pattern: `tests/decompose_refinery/test_publication_identity.py` pins resolver behavior.

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

- `news_collector/logic/workflows/refinery_engine.py` (replace `_extract_slug` body with delegation; keep the method as a thin wrapper to avoid caller churn — or remove it if it has exactly one caller, your call after Step 1)
- `tests/decompose_refinery/test_publication_identity.py` + `tests/unit/logic/workflows/test_refinery_engine.py` (parity/pinning tests only)

**Out of scope** (do NOT touch, even though they look related):

- `image_handler._derive_slug` / `image_briefs.derive_slug` date-prefixed composition — separate pair, deferred (see below).
- `slugify_text`/`_slugify` one-line wrappers — trivial, leave them.
- Any change to slug *semantics* — byte-identical output is the requirement.

## Git workflow

- Branch: `advisor/094-unify-slug-extraction`
- Conventional commits, e.g. `refactor(identity): unify slug extraction behind resolver`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Map callers and prove byte-equivalence first

1. `grep -rn "_extract_slug\|extract_slug" news_collector/ apps/ scripts/ tools/ | grep -v test` — every caller of both.
2. Diff the two bodies line by line (ignore docstring/comment wording). If they differ in ANY logic (regex, guard, fallback, strip), STOP and report the diff — the plan's premise is exact duplication.
3. Write a throwaway parity probe (not committed): run both functions over a shared corpus (frontmatter with slug, title-only, neither, quoted values, unicode titles, empty string) and assert identical outputs. If any input diverges, STOP and report.

**Verify**: parity probe passes on all corpus cases; caller list recorded.

### Step 2: Delegate

Replace `RefineryEngine._extract_slug` body with:

```python
def _extract_slug(self, content: str, fallback_id: str) -> str:
    """... (note: delegates to PublicationIdentityResolver.extract_slug)"""
    return PublicationIdentityResolver.extract_slug(content, fallback_id)
```

Check the engine's imports for `PublicationIdentityResolver` (add the import if absent; remove the now-unused `slugify`/`re` imports in the engine file ONLY if nothing else uses them — verify with grep first).

**Verify**: `make lint` → exit 0; committed parity test (promote the Step 1 probe into `tests/decompose_refinery/test_publication_identity.py` or the engine test file — parametrized slug cases asserting both entry points agree).

### Step 3: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries` → all exit 0.

## Test plan

- Committed parity test: N slug-extraction cases × both entry points, identical output.
- Existing identity + engine suites green (no slug value anywhere may change).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` all exit 0
- [ ] Exactly one regex-based slug-extraction implementation remains (`grep -rn "slug:\\\\s" news_collector/logic/workflows/*.py` → one file)
- [ ] Parity tests exist and pass
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- The bodies differ logically (not just comments) — duplication premise broken.
- Any caller subclasses/overrides `_extract_slug` (grep for `def _extract_slug` beyond these two files).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- All slug-extraction fixes now land in `PublicationIdentityResolver.extract_slug` — say so in the method docstring.
- Reviewers: the parity test is the proof; scrutinize its corpus for missing shapes (CRLF, BOM, multiline titles).
- **Deferred:** unifying `_derive_slug`/`derive_slug` date-prefixed composition — unblocked, needs the same parity-first recipe.
