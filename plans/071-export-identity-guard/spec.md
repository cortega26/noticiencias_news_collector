# Plan 071 — Export↔DB identity guard (wrong-article publish)

## Incident (run 18, 2026-09-04)

Requested DB id 158 ("Evidence of tornadic phenomena…"), published the
giant-tortoise article, opened real PR #143 (closed afterwards), no DB
trace on 158, empty run summary. Root causes, in order:

1. **Systemic**: the daily CI job commits `data/exports/latest_articles.json`
   built from an *ephemeral* DB (fresh autoincrement ids). Those ids do
   not match production `data/news_v3.db` — yet every consumer joins or
   filters by `id` (publishable scores, refinery `process_id` filter).
   Here: export id 158 = tortoise content; production id 158 = tornado.
2. **Proximate (mine)**: merged the 09-04 data update over the correct
   local 09-03 regen, then launched publish-by-id without re-verifying
   export↔DB consistency.

## Design

Defense in depth at the exact bite point
(`apps/refinery/main.py::_load_export_articles`, `process_id` path only —
bulk mode and filename fallback carry no cross-id risk):

- After the id filter matches, `_export_identity_matches_db(art,
  process_id, db_manager)`: numeric ids only; fetch the production row
  via `db_manager.get_article_by_id`; require stripped-exact match on
  BOTH title and url. Mismatch or absent row ⇒ error log (both sides,
  truncated) and drop the candidate ⇒ existing "no articles for ID"
  noop path instead of a wrong publish.
- Fail-open (warn + allow) when identity is *unverifiable*: non-numeric
  ids, DB access errors, non-string fields (toy mocks in existing tests).
  Only *proven* mismatch or *absent* row blocks.
- No contract/storage/UI changes; no new LLM calls; filesystem fallback
  and bulk paths untouched.

## Verification

- New tests in `test_main_export_payload.py`: match kept; title mismatch
  dropped; url mismatch dropped; unknown id dropped; method-less dummy
  DB still passes (fail-open); non-numeric process_id untouched.
- Existing `_load_export_articles` suites green.
- Regenerate `data/exports/latest_articles.json` from production DB and
  assert id 158 = tornado article again.
- `make lint && make type && make test && make test-boundaries`.
