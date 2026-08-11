# Plan 056: Collector regression sweep — admission, recency, canonicalization

> **Executor instructions**: Close the gaps in an uncommitted regression batch
> left in the working tree from the 2026-08-07 evening session (after the
> plans 051/053/054/055 commit `75122ab`). The batch had never been committed
> nor registered in the plan ledger. This plan validates it, fixes formatting,
> and lands it.
>
> Drift check: `git status --short` and `git diff --stat HEAD` must show
> only plan files + the intended code/test changes.
>
> Must finish with `make lint && make type && make test` per
> `docs/AGENTS.md` §10.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH (collector boundary, contracts, storage, canonical identity)
- **Depends on**: none
- **Category**: regression sweep (correctness fixes)
- **Planned at**: backend, 2026-08-10

## Scope (what the batch fixes)

1. **RSS recency filter re-enabled** (`rss_collector.py`): the date filter
   (drop items older than `recent_days_threshold`) was commented out; it now
   applies again, treating naive datetimes as UTC. Complements plan 050's
   candidate gate at the ingestion boundary.
2. **Headless admission gate** (`headless_collector.py`): articles from the
   headless collector now pass through `evaluate_admission` at the save
   boundary (same policy as RSS, plan 034), with a structured log event on
   rejection.
3. **Auditor no longer poisons the cache** (`auditor.py`): when the LLM
   returns no usable data, the all-zeros default is no longer persisted as a
   real score and status becomes `audit_unavailable` instead of
   `audit_passed`.
4. **Contract sanitizers** (`contracts/collector.py`): `word_count` and
   `reading_time_minutes` clamp NaN/negative/non-numeric values to safe
   defaults so malformed feeds cannot produce invalid rows.
5. **URL canonicalizer preserves non-web schemes** (`url_canonicalizer.py`):
   `ftp:`/`mailto:`/`javascript:` URLs are no longer force-rewritten into
   `https` (they now fail `AnyHttpUrl` validation at the contract instead);
   `:80`/`:443` default ports stripped after consolidation to `https`.
6. **YAML-aware `refinery_id` frontmatter match** (`target_repo_writer.py`):
   string-literal search misidentified posts when the value was dumped as an
   int or quoted string; the frontmatter block is now parsed and compared
   normalized.
7. **Concurrent slug registration is idempotent** (`article_repository.py`):
   `IntegrityError` on a deterministic slug commit is treated as success
   (another worker won).
8. **UTC-safe struct_time conversion** (`datetime_utils.py`):
   `calendar.timegm` instead of host-local `mktime` (UTC + pre-2038 safety).
9. **Per-session job-key scoping** (`base_collector.py`): `_job_keys_seen`
   cleared at session start so a retry with the same source/target is not
   treated as a duplicate of a previous session.
10. **Smoke fixture dates shifted** (`run_collector_smoke.py`): replay
    fixture publish dates are shifted into the recency window, mirroring
    plan 050's `_relative_fixture_dates` in e2e tests.

## Follow-up audit (2026-08-10, committed `053509b`)

Adversarial audit of the batch found and fixed 7 bugs + 19 new regression
tests (450 insertions):

1. **Sanitizer OverflowError**: `sanitize_word_count`/`sanitize_reading_time`
   crashed on ±inf / `'1e999'` (`int(inf)` uncaught); NaN was handled but
   infinity wasn't. Now `math.isfinite`.
2. **Foreign-scheme mangling**: the hostport misparse heuristic rewrote
   `tel:12345`/`data:12345`/`javascript:12345` into `https://tel:12345/`.
   Discriminator is now the scheme itself (dot or `localhost`).
3. **Frontmatter CRLF + missing `---`**: `_frontmatter_refinery_id_matches`
   failed on CRLF files and sliced the whole head when the closing marker
   was absent (body parsed as YAML → false match). Normalized + guarded.
4. **Headless never saved**: admission gate validated a filtered model but
   `_save_article` received the raw dict (`tags`/`published_at` →
   `extra="forbid"` → ValidationError → article dropped). Model now saved.
5. **Auditor junk dict**: `if raw_data:` only guarded the empty dict; a
   truthy junk dict (`{"error": ...}`) still persisted all-zeros as real
   `audit_passed`. Key-presence check now the discriminator.
6. **Slug collision lie**: `set_canonical_slug` returned True on ANY
   IntegrityError — including a collision with a *different* article whose
   slug was never persisted. Now re-queries and verifies ownership.
7. **RSS filter TypeError**: recency filter compared non-datetime
   `published_date` (crash); smoke script `Z`→`+00:00` replace was global
   not trailing-anchored.

Validation: `make lint`/`make type`/`make test` green (1758 passed / 4
skipped). `make test-contracts` coverage gate 78.38% vs 80% remains the
pre-existing failure documented in plans 050/051 (clean tree: 77.03% —
this audit raised it). One pre-existing flaky e2e
(`test_pipeline_e2e_bundle_root_is_repeatable`) fails intermittently on
the clean tree too (passes in isolation / full-file runs).

## Verification

```bash
make lint
make type
make test
```

- `make type` run: 1741 passed / 4 skipped, coverage ratchet OK
  (85.97% vs 85.73% baseline).
- `make test` run: 1 failure only in
  `test_enrichment_metrics_store.py::test_interleaved_attempts_and_successes_match_between_immediate_and_batched`
  — a pre-existing flaky timing test (passes in isolation, unrelated to
  this batch).
- `git diff --check` clean.
