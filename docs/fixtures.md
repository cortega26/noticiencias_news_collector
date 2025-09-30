# Fixture Maintenance Guide

This document explains how to maintain the golden datasets used by the end-to-end
collector pipeline tests. The goal is to keep `tests/data/golden_articles.json`
and the chained fixture `tests/data/collector_pipeline_chain.json` in sync with the
current schemas for collector payloads, enrichment outputs, and storage rows.

## When to Refresh Fixtures

Refresh the fixtures whenever one of the following happens:

- The collector contract (`CollectorArticleModel`) gains or changes required fields.
- The enrichment pipeline updates its payload schema or output semantics.
- Storage models (`Article`, `ScoreLog`) evolve in a way that changes persisted
  columns validated by the tests.
- Scoring logic adds new components or renames existing ones.

## Refresh Procedure

1. **Regenerate enrichment expectations**
   - Update `tests/data/golden_articles.json` so that it reflects the latest
     enrichment outputs for your canonical article samples.
   - If you have added new samples, ensure their `expected` block mirrors the
     deterministic enrichment pipeline output.

2. **Rebuild the chained pipeline fixture**
   - Copy the structure used in `tests/data/collector_pipeline_chain.json` for
     each article (source metadata, collector payload, expected storage fields).
   - For new schema fields, add the minimum values required by
     `CollectorArticleModel` and by the scoring/storage contracts.
   - Keep summaries at least `TEXT_PROCESSING_CONFIG["min_content_length"]`
     characters so validation passes.

3. **Validate with the E2E test**
   - Run `pytest -s tests/test_collector_pipeline_e2e.py` to execute the mocked
     pipeline.
   - The test writes a reconciliation artifact listing expected vs. actual
     fields. Copy the printed `pipeline_reconciliation_artifact=...` path and
     inspect the JSON to confirm the new schema is represented correctly.

4. **Iterate until clean**
   - Adjust fixture entries until the test passes without diffs outside the
     acceptable tolerances (language, sentiment, topics/entities containment,
     score thresholds, etc.).

5. **Commit the updates**
   - Commit changes to the fixture JSON files together with any schema or code
     updates so CI runs against matching expectations.

## Tips

- When schemas gain optional fields, prefer adding them to the fixture so the
  pipeline test exercises the new shape early.
- If scoring parameters change, bump the `final_score_min` guardrails rather than
  hard-coding exact scores—this keeps the test resilient to minor tuning.
- Keep the reconciliation artifact from the latest run attached to CI logs; it
  provides fast feedback when the pipeline diverges from the expected fixtures.
