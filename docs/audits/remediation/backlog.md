# Remediation Backlog — 2026-Q1

**Last updated**: 2026-03-26 (Wave 3+4 execution)
**Source**: [plan.md](plan.md) | Findings: [Findings_Ledger.md](../Findings_Ledger.md)

> **This file is the source of truth for tracking remediation progress.**
> Update Status as work proceeds. Do not delete completed items.

## Status key

`todo` | `ready` | `in-progress` | `done` | `blocked` | `wontfix`

---

## Horizon A — Immediate fixes

### A-01: Fix XSS in search results page

| Field | Value |
|-------|-------|
| **Type** | security |
| **Findings** | F-0014 |
| **Severity** | S0 |
| **Priority** | P0 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Frontend |
| **Effort** | S |
| **Change** | Replace `innerHTML` with `createElement` + `textContent` in `noticiencias/src/pages/buscar.astro:220-227`. Add check in `dist-sanity.js` to detect `innerHTML` with template literals. |
| **Definition of Done** | No `innerHTML` with dynamic variables in buscar.astro. A title containing `<script>alert(1)</script>` renders as plain text. |
| **Validation** | dist-sanity.js check passes. Manual test with HTML-containing title. |
| **Notes** | Wave 1: innerHTML replaced with createElement+textContent in buscar.astro. dist-sanity.js check for innerHTML+template literals added. |

---

### A-02: Double-click guard on Streamlit action buttons

| Field | Value |
|-------|-------|
| **Type** | bugfix |
| **Findings** | F-0013 |
| **Severity** | S0 |
| **Priority** | P0 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Streamlit |
| **Effort** | S |
| **Change** | Before `run_refinery()`, set `st.session_state["op_in_progress"] = True`. In `finally`, set `False`. Render buttons with `disabled=st.session_state.get("op_in_progress", False)`. Apply to Publish (line 1267), Sync (line 864), and Delete (line 1200). |
| **Definition of Done** | During execution, all action buttons are disabled. Second click during operation does not trigger second execution. |
| **Validation** | Manual test: start publish, verify button disabled, verify re-enabled after completion. |
| **Notes** | Wave 1: op_in_progress session_state guard added to Sync, Publish, Force Reprocess, and Delete buttons. try/finally ensures reset. |

---

### A-03: Check published status before publishing

| Field | Value |
|-------|-------|
| **Type** | bugfix |
| **Findings** | F-0028 |
| **Severity** | S2 |
| **Priority** | P1 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Streamlit |
| **Effort** | S |
| **Change** | Before `run_refinery()` in admin_panel.py:1276, call `refinery_db.is_article_published(int(selected_id))`. If True, show `st.error()` and return. Implement Force Reprocess as explicit separate path (replace current `pass` at line 1186). |
| **Definition of Done** | Selecting a published article and clicking Publish shows error. Force Reprocess requires explicit user action on a separate button. |
| **Validation** | Manual test with published article. |
| **Notes** | Wave 1: Main Publish button hidden when is_pub=True. Force Reprocess button now calls run_refinery() with same parameters. st.error shown for already-published articles. |

---

### A-04: Detect existing PR on GitHub 422 response

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0016 |
| **Severity** | S1 |
| **Priority** | P1 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Backend |
| **Effort** | M |
| **Change** | In `github_publisher.py` `create_pull_request()`, on status_code 422: GET `/repos/{owner}/{repo}/pulls?head={owner}:{branch_name}&state=open`. If PR found, return its `html_url`. If not, raise original exception. |
| **Definition of Done** | Retry after partial failure recovers existing PR URL instead of raising. Non-duplicate 422 errors still raise. |
| **Validation** | Unit test: mock 422 response + mock GET returning existing PR. Unit test: mock 422 + empty GET result raises. |
| **Notes** | Wave 2: 422 handler added with GET search for existing open PR. 4 unit tests in tests/unit/test_pr_422_recovery.py (422+existing PR returns URL, 422+no PR raises, 422+search API failure raises, 201 unaffected). Prerequisite for B-01. |

---

### A-05: Check return value of set_canonical_slug

| Field | Value |
|-------|-------|
| **Type** | bugfix |
| **Findings** | F-0023 |
| **Severity** | S2 |
| **Priority** | P2 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Backend |
| **Effort** | S |
| **Change** | At `refinery_engine.py:364-366`, capture return value. If False, log "Canonical slug already exists or failed to persist" instead of "Identity Created". Do not abort (existing slug is valid for reprocessing). |
| **Definition of Done** | Second call for same article logs "already exists", not "Created". |
| **Validation** | Unit test: process_single_article twice with same article, verify log of second invocation. |
| **Notes** | Wave 1: Return value of set_canonical_slug now checked. Logs "already exists" if False. Combined with B-02 (moved after policy check). |

---

### A-06: Replace print() and contextlib.suppress with structured logging

| Field | Value |
|-------|-------|
| **Type** | observability |
| **Findings** | F-0022, F-0026 |
| **Severity** | S1 (F-0022), S2 (F-0026) |
| **Priority** | P2 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Backend |
| **Effort** | S |
| **Change** | (a) `dispatcher.py:51-62`: replace `print(f"Error...")` with `logger.error(...)`. (b) `rss_collector.py:484,529,544`: replace `contextlib.suppress(Exception)` with `try/except Exception as e: logger.warning(...)`. |
| **Definition of Done** | Collector init failures and metadata update failures appear in structured logs. |
| **Validation** | Unit test: collector init failure produces log entry (not print). |
| **Notes** | Wave 1: All print() in dispatcher.py replaced with logger.error/warning/debug. All 3 contextlib.suppress(Exception) in rss_collector.py replaced with try/except + _emit_log warning. Also fixed silent swallow of collector task exceptions in gather results. |

---

## Horizon B — Structural hardening

### B-01: Introduce `publishing` state and recovery mechanism

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0012, F-0015 |
| **Severity** | S0 |
| **Priority** | P0 |
| **Status** | done |
| **Dependencies** | A-04 |
| **Area** | Backend / Pipeline |
| **Effort** | L |
| **Change** | (1) Add `"publishing"` to PROCESSING_STATUS_VALUES. (2) Before `git.create_branch()`, mark article as `processing_status="publishing"` with `publishing_started_at` and `publishing_branch` in article_metadata. (3) On PR failure, leave status as `publishing` with branch info. (4) At start of `process_single_article`, if article is in `publishing` state, attempt recovery: find existing PR for branch (using A-04 logic), mark completed if found, or retry PR creation. (5) Add 1-hour timeout for stuck `publishing` state. |
| **Definition of Done** | Article with status `publishing` + existing PR recovers to `completed`. Article with status `publishing` + no PR retries creation. Articles stuck >1h in `publishing` can be reprocessed. |
| **Validation** | Integration test: simulate crash post-push/pre-PR, verify recovery. Unit test: `publishing` + existing PR -> completed. |
| **Notes** | Wave 3: "publishing" added to PROCESSING_STATUS_VALUES (Python-level, no ALTER TABLE). mark_article_publishing() and get_publishing_state() added to DatabaseManager. Recovery logic added at start of process_single_article(). Mark-before-git-ops added before create_branch(). 1-hour timeout for stuck articles. 4 integration tests in tests/integration/test_publishing_state_recovery.py (recovery with PR, recovery without PR, timeout reprocessing, mark before git). |

---

### B-02: Move canonical slug persistence after policy enforcement

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0018 |
| **Severity** | S1 |
| **Priority** | P1 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Backend |
| **Effort** | S |
| **Change** | Move the `set_canonical_slug()` block (refinery_engine.py:362-369) to after line 388 (after all policy and frontmatter checks). Slug calculation (collision loop at 342-360) stays in place; only persistence moves. |
| **Definition of Done** | Article rejected by policy has no canonical_slug in DB. Article approved persists slug normally. |
| **Validation** | Unit test: article rejected by policy, verify canonical_slug is None in DB. |
| **Notes** | Wave 1: set_canonical_slug block moved after both _enforce_editorial_policy and _has_quoted_date_only_frontmatter checks. Combined with A-05 (return value check). |

---

### B-03: Make content hash dedup independent of URL check

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0019 |
| **Severity** | S1 |
| **Priority** | P1 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Backend |
| **Effort** | M |
| **Change** | In `database.py` `save_article()`, compute content hash before URL check. Run both checks independently: URL match -> return None; content hash match -> return None; then proceed to insert. |
| **Definition of Done** | Article A with URL-1 inserted. Article B with URL-2 but identical content rejected as duplicate. |
| **Validation** | Integration test: two articles with same content, different URLs; second rejected. |
| **Notes** | Wave 2: Content hash computed before URL check. Both dedup checks run independently. 3 integration tests in tests/integration/test_content_hash_dedup.py (cross-URL dedup, different content accepted, same-URL regression). Unblocks C-02. |

---

### B-04: Detect slug/permalink collisions in frontend build

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0021 |
| **Severity** | S1 |
| **Priority** | P1 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Frontend |
| **Effort** | S |
| **Change** | In `noticiencias/src/utils/blog.ts` `fetchPosts()`, after generating normalized posts, add a Map of permalinks. If duplicate detected, throw error naming both post IDs. |
| **Definition of Done** | Two posts with same permalink cause build failure with error identifying both posts. |
| **Validation** | Vitest test with two posts generating same slug; verify error thrown. |
| **Notes** | Wave 1: Map-based uniqueness check added in fetchPosts(). Throws with both post IDs on collision. Vitest test added (tests/slug-uniqueness.test.ts) validating no existing duplicates. |

---

### B-05: Atomic manifest writes

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0025 |
| **Severity** | S2 |
| **Priority** | P2 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Backend |
| **Effort** | S |
| **Change** | In `refinery_engine.py:712-718`, replace `manifest_path.write_text()` with write to `.tmp` file + `os.replace()`. |
| **Definition of Done** | Manifest is always either old-complete or new-complete, never partial. |
| **Validation** | Unit test: verify manifest is valid JSON after write. |
| **Notes** | Wave 2: write_text replaced with write-to-.tmp + os.replace(). Unit test test_manifest_write_atomic in test_refinery_manifest.py validates JSON integrity and no leftover .tmp. |

---

### B-06: Transactionalize Reset Total

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0029 |
| **Severity** | S2 |
| **Priority** | P2 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Streamlit |
| **Effort** | S |
| **Change** | In `admin_panel.py:787-804`, wrap all DELETE + UPDATE statements in explicit BEGIN/COMMIT with rollback on error. |
| **Definition of Done** | If any table DELETE fails, no tables are modified. |
| **Validation** | Manual test: simulate error in one table, verify others unchanged. |
| **Notes** | Wave 2: Per-table try/except removed. Pre-check table existence via sqlite_master. All operations in single transaction with conn.rollback() on any exception. |

---

### B-07: Add freshness timestamp to JSON export

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0017 |
| **Severity** | S1 |
| **Priority** | P2 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Backend + Streamlit |
| **Effort** | S |
| **Change** | (a) When exporting JSON, add `exported_at: ISO timestamp` to root object. (b) In admin_panel.py, when loading JSON, calculate age. If > 30min, show `st.warning()`. |
| **Definition of Done** | JSON export contains `exported_at`. UI shows warning when JSON > 30min old. |
| **Validation** | Unit test: verify `exported_at` present in export. Manual: verify UI warning. |
| **Notes** | Wave 2: `exported_at` added in reporting.py (ExportContractV2 path) and run_collector.py (v1 path). admin_panel.py checks `exported_at` or `generated_at` age, shows st.warning if > 30min. |

---

## Horizon C — Operational maturity

### C-01: Extend test coverage to storage/ and logic/workflows/

| Field | Value |
|-------|-------|
| **Type** | test |
| **Findings** | F-0020 |
| **Severity** | S1 |
| **Priority** | P2 |
| **Status** | done |
| **Dependencies** | B-01 |
| **Area** | Tests |
| **Effort** | L |
| **Change** | Add `--cov=news_collector/storage --cov=news_collector/logic` to pyproject.toml addopts. Add integration tests for: `mark_article_published`, `set_canonical_slug`, `save_article` dedup paths, `is_article_published`, and the `publishing` state transitions. |
| **Definition of Done** | Coverage report includes storage/ and logic/. Tests for dedup paths and publication state pass. |
| **Validation** | CI green with expanded coverage. |
| **Notes** | Wave 4: --cov=news_collector/storage and --cov=news_collector/logic added to pyproject.toml addopts and [tool.coverage.run] source. 16 integration tests in tests/integration/test_storage_coverage.py covering mark_article_published, set_canonical_slug, save_article dedup, is_article_published, and publishing state transitions. |

---

### C-02: E2E pipeline idempotency test

| Field | Value |
|-------|-------|
| **Type** | test |
| **Findings** | F-0020 (gap) |
| **Severity** | S0 |
| **Priority** | P1 |
| **Status** | done |
| **Dependencies** | B-03 |
| **Area** | Tests |
| **Effort** | M |
| **Change** | Create integration test: (1) feed static fixture with 5 articles, (2) run pipeline, (3) verify 5 articles in DB, (4) re-run pipeline with same feed, (5) verify still exactly 5 articles. |
| **Definition of Done** | Test passes: pipeline executed 2x produces exactly N articles, not 2N. |
| **Validation** | The test itself is the deliverable. |
| **Notes** | Wave 4: 2 integration tests in tests/integration/test_pipeline_idempotency.py. test_pipeline_idempotency_full: 5 articles saved, re-run → still 5. test_new_articles_still_accepted_after_dedup: dedup doesn't block genuinely new articles. |

---

### C-03: Minimum auditor threshold for velocity mode

| Field | Value |
|-------|-------|
| **Type** | hardening |
| **Findings** | F-0027 |
| **Severity** | S2 |
| **Priority** | P3 |
| **Status** | done |
| **Dependencies** | None |
| **Area** | Backend |
| **Effort** | S |
| **Change** | In `editorial/policy.py:142`, change `auditor_threshold=0.0` to `auditor_threshold=3.0`. |
| **Definition of Done** | In velocity mode, articles with epistemic score < 3.0 are rejected. |
| **Validation** | Unit test: policy enforcement with score=2.0 in velocity mode -> rejected. |
| **Notes** | Wave 4: auditor_threshold changed from 0.0 to 3.0 in velocity mode. 4 unit tests in tests/unit/editorial/test_velocity_threshold.py (rejects below minimum, accepts above, no longer zero, other modes unaffected). Existing test_editorial_policy.py::test_factory_velocity updated to expect 3.0. |
