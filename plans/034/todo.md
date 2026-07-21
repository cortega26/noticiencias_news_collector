# Plan 034 TODO

## Step 1: Characterize current accepted/rejected fixtures
- [x] `tests/unit/collectors/test_admission.py` — table-driven fixtures:
      valid article, title below configured minimum (config vs. Pydantic's
      hardcoded floor), title at exact boundary, content below/at boundary,
      summary_only exemption, penalty-phrase title (intentionally accepted),
      non-http scheme (documents pre-existing coercion, not rejection).
- [x] Confirmed via reading the code (not assumed) that the previous policy
      was dead code — zero callers besides a unit test — before writing any
      fixtures against it.

## Step 2: Define a typed admission decision
- [x] `news_collector/collectors/admission.py`: `AdmissionReason` enum
      (`TITLE_TOO_SHORT`, `CONTENT_TOO_SHORT`), frozen `AdmissionDecision`
      dataclass, pure `evaluate_admission(article, config)`.
- [x] Reads the canonical config (`text_processing_config`), no copied
      keyword/threshold lists.
- [x] Pure: no I/O, no mutation of `article` or `config` — verified by the
      characterization tests running the same function repeatedly with no
      side effects.

## Step 3: Apply policy once before duplicate lookup and persistence
- [x] Wired into `BaseCollector._filter_and_save_articles`, replacing the
      inline `min_length`-only check, right after model conversion and
      before the duplicate-check/save phases.
- [x] Deleted `base_collector.py`'s dead `_validate_article_data()`.
- [x] Deleted `rss_collector.py`'s weaker `_validate_article_data()`
      override and its extraction-time call site (the shared boundary now
      catches missing url/title via Pydantic model validation + the new
      policy; no separate RSS gate needed).
- [x] `tests/unit/collectors/test_admission_boundary.py` — 4 integration
      tests proving the plan's own Step 3 Verify clause literally: rejected
      articles cause zero `articles_exist()` and zero `save_articles_bulk()`
      calls; valid articles reach both; `summary_only` still bypasses
      content length at the real boundary.
- [x] Updated `tests/unit/collectors/test_rss_collector_images.py`'s two
      dead mocks of the removed method.
- [x] Deleted `tests/unit/collectors/test_validation_config.py` (exercised
      the removed dead method directly; superseded by `test_admission.py`).

## Step 4: Align scoring terminology and observability
- [x] Added per-reason health-tracker counters: `SourceHealth.skipped_short_title`
      alongside the existing `skipped_short_content`;
      `record_filter_rejection()` now branches on `title_too_short` /
      `content_too_short` (plus the existing `min_length`/`duplicate`/`top_n`).
- [x] Checked whether `basic_scorer`'s `clickbait_indicators` and config's
      `penalty_keywords` are the same list — **they are not** (verified
      term-for-term). Did NOT unify them, since that would silently reweight
      scores — out of scope ("changing score weights").
- [x] Documented both lists' intentional separation in `basic_scorer.py` and
      `config_schema.py`'s `penalty_keywords` field description (now
      correctly states it has no consumer post-cleanup).

## Verification (all run this session, all green)
- [x] `pytest tests/unit/collectors tests/unit/scoring -q` → 67 passed.
- [x] `grep -rn "clickbait|penalty_keywords|_validate_article_data"
      news_collector/collectors news_collector/scoring` → dead method gone;
      other two only where intentional.
- [x] `pytest --ignore=tests/e2e_pipeline -q` → 1176 passed, 13 pre-existing
      failures (unchanged from `main`/plan-046 baseline), 4 skipped.
- [x] `make lint` / `make type` → same pre-existing baseline errors, none
      in touched files.

## Noted, not fixed (out of scope for this plan)
- `canonicalize_url()` silently coerces any non-http(s) URL scheme to
  `https` instead of rejecting it (`news_collector/utils/url_canonicalizer.py:154`).
  Documented as a passing test
  (`test_non_http_scheme_is_silently_coerced_not_rejected_by_contract`), not
  fixed — a URL-canonicalization correctness bug, not an admission-policy gap.
- `penalty_keywords` config is now fully unconsumed (its only prior caller
  was the dead method this plan removed). Left as configured-but-unwired;
  reconnecting it (to scoring or to a reintroduced keyword-admission rule)
  needs its own deliberate, characterized decision.
