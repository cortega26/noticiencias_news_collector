# Plan 058 TODO — Deterministic canonical publication date (LAW-B5)

## Pre-work
- [x] Recon: `PublicationIdentityResolver.resolve()` priorities 1-3
      (publication_identity.py); `_derive_date` is the only non-deterministic
      path (always `datetime.now(timezone.utc)`); P2 already refuses to
      invent dates; engine `process_articles` quarantines per-article
      exceptions with `public_message`/`error_code` support.
- [x] Mapped date-field availability across every article source:
      CollectorArticleModel.published_date required (validator); DB
      Article.collected_date non-null; export fallback goes through the
      collector adapter; manual_ingest always fills (now() + flag). Only
      synthetic/test fixtures are dateless → quarantine blast radius ~0.
- [x] Existing tests IDENT-03/04/05 assert the violation as expected
      behavior — must be rewritten, not just added to.
- [x] spec.md written (goals, design, quarantine error, out-of-scope,
      compatibility plan, verification).

## Implementation
- [x] Add `UndatedArticleError(ValueError)` + `_parse_date_like()` +
      deterministic `_derive_date()` in publication_identity.py.
- [x] Update module docstring Priority-3 lines (8, 72) + _derive_date docstring.
- [x] Drop now-unused `timezone` import (parser keeps `date`/`datetime`).

## Tests (rewrite IDENT-03/04/05 + new)
- [x] IDENT-03: published_date (datetime object) → its date, not today.
- [x] IDENT-03b: published_date as ISO / space-separated strings (7 parametrized cases).
- [x] IDENT-04: no published_date → collected_date used.
- [x] IDENT-04b: both present → published_date wins.
- [x] IDENT-05: no dates → UndatedArticleError (public_message + code).
- [x] IDENT-05b: unparseable published_date → UndatedArticleError.
- [x] IDENT-05c: determinism — same article, two calls, identical identity.
- [x] IDENT-05d: empty/None falls through; lowercase z/t parse (review minor).

## Validation
- [x] `pytest tests/decompose_refinery/ -q` green (116 → 41 identity tests pass).
- [x] `make lint && make type && make test` green (1844 passed).
- [x] `make test-boundaries` green.
- [x] Grep publication_identity.py for `datetime.now` → none.

## Docs / tracking
- [x] Close the "Remove current-date fallback" item in
      `docs/dev/source-of-truth-backlog.md` (docs follow code).
- [x] Fix stale `docs/SOURCE_OF_TRUTH.md` identity-order section (review minor).
- [x] Harden `ai_editor` missing override_date → raise (review minor).
- [x] Add plan 058 row to `plans/README.md`.
- [x] Update root `spec.md` / `todo.md` sequencing.
- [ ] Commit + push.
