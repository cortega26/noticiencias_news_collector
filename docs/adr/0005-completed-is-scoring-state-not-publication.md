# ADR-0005: "Completed" is a scoring state, not a publication state

- **Date**: 2026-08-06
- **Status**: Accepted

## Context

The Refinery admin panel reported "Se ocultaron 50 artículos ya publicados. No hay
artículos disponibles para procesar." after a normal collection run, even though
no article had ever been deployed.

Root cause analysis of `data/news_v3.db` (2033 articles) showed:

- `processing_status` distribution: 953 `completed`, 1080 `rejected`, **zero**
  `new`/`pending`.
- Every single row had `published_url = NULL` and `published_at = NULL`.

The pipeline's scoring phase (`update_article_score` /
`update_articles_score_bulk` in `news_collector/storage/article_repository.py`)
sets `processing_status = "completed"` as soon as scoring finishes. Plan 021's
publication flow (`mark_article_published` → `publishing`, then
`complete_publication_attempts` → `completed` + `published_url`/`published_at`)
reuses the same `completed` literal for a *real deploy*.

So `processing_status = "completed"` is ambiguous: it means "scoring finished"
in one path and "deploy completed" in another. The only unambiguous publication
signal is `published_url`/`published_at`.

The dedup guard `is_article_in_flight_or_done` /
`articles_in_flight_or_done` treated any `completed` row as published, which
hid every scored-but-never-published article from the editorial UI.

## Decision

`is_article_in_flight_or_done(article_id)` and its batch sibling
`articles_in_flight_or_done(article_ids)` now return true **only** when:

1. `processing_status == "publishing"` (open PR, plan 021), or
2. `published_url IS NOT NULL` or `published_at IS NOT NULL` (confirmed deploy).

Plain `completed` (scored, never deployed) no longer counts as done and remains
a valid editorial candidate.

This is a root-level semantic fix: the three Refinery call sites
(`admin_panel.py` candidate filter, `admin_panel.py` detail warning,
`main.py` export dedup) all inherit the corrected behavior without individual
patches. The previously added `publishing_ids_in` batch helper was removed
again because it lost its only consumer once the root method carried the
correct semantics (LAW-B8: no single-consumer helpers).

## Consequences

Easier:

- Scored-but-unpublished articles are again visible and processable in the
  Refinery UI.
- One source of truth for "already in flight or done" across panel and
  export-dedup paths.

Harder / risks:

- **Legacy data risk**: the 953 pre-existing `completed` rows in
  `data/news_v3.db` have no `published_url`/`published_at`, so they are now
  indistinguishable from never-published articles. If any of them were
  actually deployed before plan 021 existed (when `mark_article_published`
  jumped straight to `completed`), re-selecting them risks a duplicate PR.
  There is no reliable way to recover that distinction from current data;
  operators must eyeball candidates before publishing the old backlog.
- **Rescoring semantics unchanged**: `get_completed_articles_for_rescoring`
  still selects `completed` rows without published fields, which is consistent
  with the corrected guard (both treat scored-unpublished as actionable).
- **Coverage gate**: `apps/refinery/admin_panel.py` is excluded from coverage
  measurement (`[tool.coverage.run] omit` in `pyproject.toml`) because
  Streamlit is not importable in the test venv; its helpers are exercised via
  AST decomposition tests. Any commit touching `admin_panel.py` previously
  tripped the 90%-changed-modules ratchet gate for that reason, unrelated to
  actual coverage regression.

## Alternatives considered

| Option | Reason rejected |
|--------|-----------------|
| Keep `completed` in the guard and only patch `admin_panel.py` candidate filter | Leaves `main.py` export dedup and the detail-view warning with the same bug; three divergent semantics to maintain |
| Change the scoring phase to write `pending` instead of `completed` | Large contract change touching scoring, rescoring, and reporting; the corrected guard already resolves the user-visible bug with a single-point fix |
| Add a new `scored` status | Schema migration plus cross-repo contract implications; no additional behavioral value over the corrected guard |
