# Plan 060 / Phase 2a todo: Characterize and harden the v2 fail-closed gate; retire the v1 smoke fixture

Execution index for [`spec.md`](spec.md). The spec's baseline correction,
exact scope, STOP conditions, and acceptance criteria are binding; do not
implement from this checklist alone.

## Step 0 — baseline

- [ ] Read `ai_editor.py:203-235`, `:1355-1429`, `:1955-1995`, `:2107-2218`
      and `refinery_engine.py:283-560` in full; confirm the Baseline
      correction in spec.md still matches the live file (line numbers may
      have drifted since this plan was written — re-grep, don't trust the
      numbers blindly).
- [ ] `pytest tests/unit/editorial/ tests/unit/logic/workflows/test_refinery_engine.py -v`
      passes on an unmodified checkout.
- [ ] Grep the whole repo for `FIXTURE_ARTICLE_ID`, `build_fixture_post`,
      `render_fixture_markdown`, `_smoke-test` — list every caller found
      before touching Step 2.

## Step 1 — integration test: fail-closed boundary

- [ ] New test(s) added to `tests/unit/logic/workflows/test_refinery_engine.py`
      following the file's existing mocking conventions.
- [ ] Case: `process_article` raises `GeneratedArticleValidationError`
      with `error_code="editorial_v2_incomplete"` →
      `process_single_article` returns `False`,
      `create_branch.assert_not_called()`, writer not called,
      `_last_blocked_error["error_code"]` correct.
- [ ] Control case: successful `process_article` → pipeline proceeds to
      `branch_created` (matching existing successful-path test depth).
- [ ] No changes made to `ai_editor.py` or `refinery_engine.py` in this
      step.

## Step 2 — production-path v2 smoke fixture

- [ ] `build_fixture_post()` / `render_fixture_markdown()` replaced with a
      builder that calls `EditorAgent.process_article` through a
      deterministic stubbed LLM provider (pattern matched from
      `tests/unit/editorial/test_enrichment_fields.py`'s `setUp`).
- [ ] Raw input content clears `min_content_length` (checked, not
      guessed).
- [ ] Output markdown contains `schema_version: 2` and all six enrichment
      fields.
- [ ] `FIXTURE_ARTICLE_ID` / `FIXTURE_POST_FILENAME` preserved, or every
      caller from Step 0's grep updated in the same commit if changed.
- [ ] `run_frontend_publication_validation`'s stage/validate/restore
      lifecycle still works end-to-end with the new fixture.

## Step 3 — prove fail-closed per field

- [ ] New/extended test module: six cases, one per required field
      (`summary_points`, `glossary`, `fact_check`, `why_it_matters`,
      `confidence`, `sources`), each built by making the provider stub
      omit that field — not by hand-editing rendered YAML.
- [ ] `sources` case specifically: raw input built with `source_url` and
      `source_name` both absent (not just the stub omitting `sources`) —
      otherwise the deterministic backfill at `ai_editor.py:1409-1421`
      fills `sources` back in and the case passes for the wrong reason.
- [ ] Each case asserts `GeneratedArticleValidationError` +
      `error_code="editorial_v2_incomplete"`.
- [ ] Complete-fixture case asserts success.

## Step 4 — end-to-end frontend run

- [ ] `run_frontend_publication_validation` (or its CLI entry point) run
      against a real frontend checkout with the new production-path
      fixture; exit code recorded.
- [ ] `npm run validate:content` / `build` / `test:dist` / `test:audit`
      actually executed against the staged `_smoke-test.md` (not mocked).
- [ ] Post-run `git status` in the frontend checkout is clean (workspace
      restore leaves no residue) on both pass and fail outcomes.

## Step 5 — close out

- [ ] `pytest tests/unit/logic/workflows/test_refinery_engine.py -v` green.
- [ ] `pytest tests/unit/editorial/ -v` green, unchanged pass count outside
      the new additions (no regressions).
- [ ] New fixture test module green.
- [ ] `make test` passes.
- [ ] `git diff --stat` shows only: `tests/unit/logic/workflows/test_refinery_engine.py`,
      `news_collector/logic/workflows/frontend_publication_validation.py`,
      the new/extended fixture test module, and (only if required by
      Step 2) any caller files identified in Step 0.
- [ ] `plans/060/todo.md` Phase 2 checklist: check off exactly the three
      lines spec.md's "Done criteria" section names — no others.
- [ ] This file fully checked off.
