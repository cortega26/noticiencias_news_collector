# Spec: Plan 058 — Deterministic canonical publication date (LAW-B5)

## Goals

Make Priority-3 (creation-mode) identity resolution in
`PublicationIdentityResolver` deterministic, satisfying LAW-B5 ("Runtime
time, randomness, request order, and batch order must not change canonical
publication outputs").

Today `_derive_date()` (`news_collector/logic/workflows/publication_identity.py:263`)
**always** returns `datetime.now(timezone.utc)` — retrying publication of the
same dateless article on different days produces a different
`canonical_date`, slug, and filename. This closes the High item
"Remove current-date fallback from canonical publication identity" in
`docs/dev/source-of-truth-backlog.md`.

## Implementation details

`_derive_date(article: Dict[str, Any]) -> str` becomes deterministic:

1. **`published_date`** present and parseable → its `YYYY-MM-DD` (source date).
2. else **`collected_date`** present and parseable → its `YYYY-MM-DD`.
3. else → raise a typed quarantine error (see below).

Parsing via a new `_parse_date_like(value)` static helper that accepts:

- `datetime` / `date` objects (incl. naive and tz-aware)
- ISO-8601 strings (`2025-12-25`, `2025-12-25T10:00:00[.fff][±HH:MM|Z]`)
- space-separated datetimes (`2025-12-25 00:00:00`, the `str(datetime)`
  form produced by `RefineryEngine._normalize_article_payload`)

A **present-but-unparseable** date raises (data problem, quarantine) rather
than silently falling through — same philosophy as Priority 2's existing
`ValueError("...refusing to invent a non-deterministic date")`.

### Quarantine error type

New `class UndatedArticleError(ValueError)` in `publication_identity.py`
with:

- `public_message` (Spanish, user-facing — the engine's `process_articles`
  error handler already surfaces `public_message`/`error_code`)
- `error_code = "E_IDENTITY_NO_DATE"`

The engine already quarantines per-article exceptions
(`process_articles`, line ~235 `try/except Exception`), so no engine code
change is needed; the article fails publication with a clear reason and the
batch continues.

### Out of scope (documented, not changed)

- `manual_ingest.py:557` fills missing `published_date` with `now()` at
  **ingest** time, flagged `inferred_published_date`. That value is
  persisted to the DB **before** identity resolution, so a retry of the
  same persisted row is deterministic. Pre-persistence provenance is a
  separate concern; the flag already records it.
- Priority 1 (DB slug) and Priority 2 (FS scan) paths are already
  deterministic; untouched.
- `datetime.now()` for **metadata** timestamps (`generated_at`,
  `publishing_started_at`, etc.) is allowed by LAW-B5 ("Allowed
  non-determinism: ... metrics timestamps"); untouched.

### Files

- `news_collector/logic/workflows/publication_identity.py` — `_derive_date`
  + `_parse_date_like` + `UndatedArticleError`; docstrings at lines 8, 72.
- `tests/decompose_refinery/test_publication_identity.py` — rewrite
  IDENT-03/04/05 (they currently assert the violation) + new cases.
- `docs/dev/source-of-truth-backlog.md` — close the item (docs follow code).
- `plans/README.md`, root `todo.md` — plan 058 tracking rows.

## Compatibility / migration plan (LAW-B5 §5)

- **Behavior change**: dateless articles that previously published with
  today's date now fail with `E_IDENTITY_NO_DATE`. Real pipeline paths are
  unaffected: collector contracts require `published_date`
  (`CollectorArticleModel` validator), DB articles have non-null
  `collected_date`, export-fallback goes through the collector adapter
  (published_date required), and manual ingest always fills a date
  (flagged). Only synthetic/test fixtures without dates hit the quarantine.
- **No persisted-state migration** is needed: no stored identity changes;
  only future creation-mode resolutions change.
- **Rollback**: one revert of this commit restores `now()` behavior.

## Verification

1. `tests/decompose_refinery/test_publication_identity.py` — new/rewritten
   cases green; determinism asserted (same article dict → same identity,
   two calls, no clock dependence).
2. `make lint && make type && make test`
3. `make test-boundaries` (workflow boundary change — High class)
4. Targeted: `pytest tests/decompose_refinery/ -q`
5. Full regression: `make test` suite (covers any other P3 caller).
6. Grep for lingering `datetime.now` inside `publication_identity.py` → none.
