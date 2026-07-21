# Plan 034: Centralize article admission — spec

## Outcome: DONE

All 4 steps landed. Every collector's real save path now applies one
shared, typed, structural admission policy exactly once, before duplicate
lookup and persistence — replacing a policy that was dead code (never
called) plus a weaker, RSS-only pre-filter.

## What was actually wrong (confirmed by reading the code, not assumed)

- `base_collector.py`'s `_validate_article_data()` (title length, URL
  scheme, min content length, penalty-keyword rejection) was **never called
  by the real save path**. The only caller anywhere in the codebase was a
  unit test exercising it directly. The actual bulk-save path,
  `_filter_and_save_articles()`, only did Pydantic model validation plus a
  bare `min_content_length` check (respecting the `summary_only` exception).
- `rss_collector.py` had its own, weaker `_validate_article_data()` override
  (URL + title *presence* only, no length checks) called during extraction,
  before articles even reach `_filter_and_save_articles`.
- HTML and Reddit collectors called `_filter_and_save_articles()` directly
  with no article-level gate beyond the base class's dead-code method.
- Net effect: configuring `min_title_length` above 10 (Pydantic's
  hardcoded `Field(min_length=10)` on `CollectorArticleModel.title`) would
  have **silently had zero effect** on any collector's real save path —
  exactly the plan's "configuration can appear active while having no
  effect" framing. At today's actual `config.toml` value (10, matching the
  Pydantic hardcoded minimum), this was invisible; it would only surface the
  moment someone raised the threshold.
- `text_processing_config["penalty_keywords"]` was read only inside the
  same dead method — also effectively unconsumed configuration.

## Design decisions (each checked against risk before landing)

1. **Hard-structural vs. soft-scoring, kept separate.** The new admission
   module (`news_collector/collectors/admission.py`) only enforces title
   length and content length (respecting `summary_only`). It does **not**
   hard-reject on `penalty_keywords`, unlike the old dead method. Keyword
   "clickbait" signals stay a soft, scoring-only concern
   (`basic_scorer._evaluate_title_quality`'s own, separately-hardcoded
   `clickbait_indicators` list). Verified the two keyword lists genuinely
   differ term-for-term (config's `penalty_keywords` has "conspiracy",
   "hoax", "fake news", "Trump"; the scorer's list has "amazing",
   "incredible", none of which overlap exactly) — so unifying them would
   silently reweight scores for specific keyword hits, which is explicitly
   out of this plan's scope ("changing score weights"). Left as two
   independent, documented lists; see Step 4 below.
2. **URL scheme is not re-checked in the new module.**
   `CollectorArticleModel.url: AnyHttpUrl` already structurally guarantees
   an http(s) URL before `evaluate_admission()` is ever reached — adding a
   redundant check would be dead code. **Discovered in passing** (not part
   of this plan's scope to fix): `canonicalize_url()`
   (`news_collector/utils/url_canonicalizer.py:154`) silently *rewrites*
   any non-http(s) scheme to `https` rather than rejecting the URL — so an
   `ftp://` input doesn't get rejected, it gets coerced. This is a
   pre-existing, separate bug in URL canonicalization, documented as a test
   (`test_non_http_scheme_is_silently_coerced_not_rejected_by_contract`)
   rather than fixed here.
3. **`summary_only` exemption preserved exactly.** The old inline check
   (`if not is_summary_only and len(content) < min_length`) is now
   `evaluate_admission()`'s own `if article.content_mode != "summary_only"`
   branch — same semantics, single source now.
4. **Reason codes, not booleans.** `AdmissionDecision(accepted, reason,
   details)` with `AdmissionReason.TITLE_TOO_SHORT` /
   `CONTENT_TOO_SHORT` — logged via `collector.filter.admission_rejected`
   and counted via `health_tracker.record_filter_rejection(source_id,
   reason.value)`. `SourceHealth` gained a `skipped_short_title` counter
   alongside the existing `skipped_short_content`.

## Step 4: scoring terminology (deliberately narrow)

Per the plan's own scope note ("reuse ... where semantically appropriate")
and the keyword-list-divergence finding above, Step 4 was kept to
documentation only:

- `basic_scorer.py`'s `clickbait_indicators` list now has a comment
  explaining why it's intentionally separate from
  `text_processing_config["penalty_keywords"]`, and what a real unification
  would require (a characterized scoring-impact review, not an incidental
  cleanup).
- `config_schema.py`'s `penalty_keywords` field description now states
  plainly that it has no consumer after this plan removed its only (dead)
  caller, and that reconnecting it needs a deliberate decision.

No scoring weights changed as part of this plan.

## Verification

- New tests: `tests/unit/collectors/test_admission.py` (9, pure
  `evaluate_admission()` unit/characterization tests — every accept/reject
  boundary at today's real config values, plus the two out-of-scope
  findings above documented as passing tests) and
  `tests/unit/collectors/test_admission_boundary.py` (4, integration-level:
  a rejected article causes zero `db_manager.articles_exist()` and zero
  `db_manager.save_articles_bulk()` calls — literally the plan's own Step 3
  Verify wording).
- Removed `tests/unit/collectors/test_validation_config.py` (exercised the
  now-deleted dead method directly; its two scenarios — default threshold,
  configured override — are superseded by `test_admission.py`).
- `pytest tests/unit/collectors tests/unit/scoring -q` → 67 passed.
- `grep "clickbait|penalty_keywords|_validate_article_data"
  news_collector/collectors news_collector/scoring` → `_validate_article_data`
  no longer exists anywhere; the other two only appear where intentional.
- `pytest --ignore=tests/e2e_pipeline -q` → 1176 passed (1165 baseline from
  plan 046 + 9 new `test_admission.py` + 4 new `test_admission_boundary.py`
  − 2 removed `test_validation_config.py` = 1176, exact), 13 pre-existing
  failures unchanged, 4 skipped.
- `make lint` / `make type` → same pre-existing baseline errors as `main`
  (1 lint, 3 type), none in any file this plan touched.
