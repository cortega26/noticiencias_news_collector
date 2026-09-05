# Plan 077 — Preserve export `id` through the collector adapter

## Finding (from run-20 warnings triage)

`adapt_export_article_to_collector_payload` strips every key not declared
on `CollectorArticleModel` (`extra="forbid"`), and the model has no `id`
field — verified live: `id preserved: None`. Consequence: EVERY
publish-by-id degrades to title-fallback identity downstream (attempt
files named by title so the run summary lookup misses, numeric DB
publish-marking skipped, frontend callback correlation broken — exactly
what the `refinery_id` fallback warning says). This compounded run 18:
even with correct content, its summary would have missed.

## Design

One additive optional field: `id: int | str | None = None` on
`CollectorArticleModel` (first field, documented as export/DB identity
carried through, never used for inserts). The adapter's `_ALLOWED` set
derives from model fields, so preservation is automatic; no adapter code
changes. Safe for persistence: `save_article`/`_prepare_bulk_row`
construct `Article(...)` with explicit keywords (no `id` passthrough),
dedup stays URL/hash-based (verified by reading both paths).

Non-goals: changing identity resolution (already prefers `id`), touching
scoring/validation payloads, frontend changes.

Side effect found by tests (intended, kept): with numeric ids flowing
again, export-loaded articles now consult publishing recovery (B-01) —
previously dead code for them since the stripped id forced title
fallback. `test_refinery_publish_hardening` mocks now return no stuck
state to keep covering the golden full-pipeline path.

## Verification

- Tests: adapt preserves int id, preserves string id, absent id stays
  absent (no crash, no phantom key).
- Existing adapter suites green (subset asserts unaffected by one
  additive optional key).
- `make lint && make type && make test && make test-contracts`.
