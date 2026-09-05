# Plan 069 — Persist stages on unexpected exceptions

## Finding

`process_single_article` only persists attempt summaries on explicit
`return False` paths. An unexpected exception (like run 17's headline
`ValueError` pre-063, or any future stage crash) propagates to
`process_articles`, which records the error but persists nothing — so
exactly the failed runs editors most want to inspect show bare rows
without stage checklists in Quality (verified live: runs 16/17).

## Design

Mirror, don't restructure (no 300-line re-indent):

1. `__init__`: `self._last_publication_stages = None` (typed).
2. `process_single_article` top: reset to `None` (covers raises before
   any stage, e.g. identity resolve); `record_stage` closure mirrors
   `self._last_publication_stages = publication_stages` on every record.
3. New `_persist_interrupted_attempt(article_id, stages)`: no-op when
   id is missing/`"unknown"` or stages falsy; never overwrites an
   existing *successful* attempt file (re-publish crash must not destroy
   the prior PR record); never raises (warns instead); `failure_class`
   stays `None` (the Literal has no generic member).
4. `process_articles` except-block calls it before building the error
   entry. Error entry content/behavior unchanged (still re-raised
   semantics from the caller's view — the exception still propagates
   out of `process_single_article`; only a summary file is added).

## Verification

- New tests: unexpected mid-pipeline raise ⇒ summary file with the
  stages recorded so far + `success: False`, error entry intact;
  pre-existing successful file never overwritten; unresolvable id
  writes nothing.
- `make lint && make type && make test && make test-boundaries`.
