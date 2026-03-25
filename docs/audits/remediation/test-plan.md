# Test & Validation Plan — 2026-Q1 Remediation

**Last updated**: 2026-03-25
**Backlog**: [backlog.md](backlog.md)

---

## Unit tests

| Test name | Validates fix | Finding | Bug prevented | Enters with |
|-----------|---------------|---------|---------------|-------------|
| `test_pr_422_returns_existing_url` | A-04 | F-0016 | Retry creates duplicate PR instead of recovering existing one | PR-7 |
| `test_pr_422_no_existing_pr_raises` | A-04 | F-0016 | False positive recovery on genuine 422 error | PR-7 |
| `test_canonical_slug_return_false_logged` | A-05 | F-0023 | Misleading "Identity Created" log when slug already exists | PR-4 |
| `test_dispatcher_logs_collector_exceptions` | A-06 | F-0022 | Failed collectors invisible (print instead of logger) | PR-4 |
| `test_metadata_update_failure_logged` | A-06 | F-0026 | Feed metadata update failure silenced by contextlib.suppress | PR-4 |
| `test_policy_rejects_then_slug_not_persisted` | B-02 | F-0018 | Rejected article consumes immutable slug | PR-5 |
| `test_manifest_write_atomic` | B-05 | F-0025 | Manifest corrupted by partial write | PR-9 |
| `test_velocity_mode_rejects_below_minimum` | C-03 | F-0027 | Zero-quality article passes velocity mode audit | PR-13 |

## Integration tests

| Test name | Validates fix | Finding | Bug prevented | Enters with |
|-----------|---------------|---------|---------------|-------------|
| `test_content_hash_dedup_cross_url` | B-03 | F-0019 | Syndicated articles (same content, different URL) stored as duplicates | PR-8 |
| `test_publishing_state_recovery_with_existing_pr` | B-01 | F-0012 | Article stuck after crash; PR exists but DB not updated | PR-10 |
| `test_publishing_state_recovery_without_pr` | B-01 | F-0015 | Branch pushed but no PR; retry fails instead of creating PR | PR-10 |
| `test_pipeline_idempotency_full` | C-02 | F-0020 | Pipeline run twice produces 2N articles instead of N | PR-11 |
| `test_save_article_concurrent_insert` | C-01 | F-0019 | Race condition: two processes insert same URL simultaneously | PR-12 |

## Frontend tests

| Test name | Validates fix | Finding | Bug prevented | Enters with |
|-----------|---------------|---------|---------------|-------------|
| `test_no_innerhtml_with_dynamic_vars` (dist-sanity.js) | A-01 | F-0014 | XSS regression via innerHTML with template literals | PR-1 |
| `test_duplicate_slugs_break_build` (Vitest) | B-04 | F-0021 | Two posts with same permalink; last silently wins | PR-6 |

## Security checks

| Check | Validates fix | Finding | Enters with |
|-------|---------------|---------|-------------|
| Add grep for `innerHTML.*\$\{` in dist-sanity.js | A-01 | F-0014 | PR-1 |
| Manual: insert article with `<script>` in title, verify renders as text in search | A-01 | F-0014 | PR-1 |

## Manual Streamlit tests

These cannot be automated due to Streamlit's GUI-only execution model.

| Test | Validates fix | Steps | Expected result |
|------|---------------|-------|-----------------|
| Double-click on Publish | A-02 | Start publish for any article; immediately click Publish again | Button is disabled during spinner; second click has no effect |
| Publish already-published article | A-03 | Enable "Show processed", select published article, click Publish | Error message shown; `run_refinery()` not called |
| Sync + Publish concurrency | A-02 | Click Sync; while spinner is active, try to click Publish | Publish button is disabled while Sync runs |
| Reset Total partial failure | B-06 | Trigger Reset; verify all tables cleared or none cleared | All-or-nothing behavior |
| Stale JSON warning | B-07 | Wait 30+ min after sync, reload admin panel | Warning about stale data visible |
| Force Reprocess path | A-03 | Select published article, click Force Reprocess | Explicit confirmation required; article reprocessed correctly |

## Test dependencies (what must be merged before writing certain tests)

```
A-04 merged ──> B-01 tests can be written (publishing state recovery)
B-03 merged ──> C-02 test can be written (idempotency test needs cross-URL dedup)
B-01 merged ──> C-01 tests can be written (storage tests need publishing state)
```
