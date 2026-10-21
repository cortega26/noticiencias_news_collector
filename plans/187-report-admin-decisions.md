# Plan 187: Reader reports — admin triage/decision endpoints (060 Phase 10, item 4)

> Execute; run every verification; stop on STOP.
> **Drift check**: `git diff --stat a525b796..HEAD -- news_collector/contracts news_collector/logic/workflows news_collector/storage news_collector/serving alembic/versions tests`

## Status

- **Priority**: P2 (060 Phase 10)
- **Effort**: M
- **Risk**: MEDIUM (first admin mutations on the report surface; new migration)
- **Depends on**: plans 185 (`51d01787`) + 186 (`fb2e77f1`) — merged
- **Category**: serving / admin workflow dispatch
- **Planned at**: backend `a525b796`, 2026-10-20

## Why this matters

Reports now flow R2→backend (186) with identity (185), but an editor cannot
act on them: no admin surface can triage or record a corrected/rejected state.
This slice adds the **legal transition + audit** surface. Closure of an
accepted correction (publication/PR + deploy evidence) is deliberately a
separate slice (188), so 187 must refuse reaching `closed` state.

## Current state (verified anchors)

- Admin surface precedent: `news_collector/serving/api.py` — the comment block
  "Admin surface (/v1/admin/*) — Phase 1 of the Refinery GUI decoupling" at
  ~line 1571: read-oriented per LAW-B4; mutations only dispatch to existing
  idempotent storage transitions (webhook-handler pattern). Envelope style:
  `AdminArticleListEnvelope`; `page_size Query(20, ge=1, le=50)`, `cursor`;
  `verify_admin_token` at :1114.
- Models: `ReaderReport` (status `new|triaged|accepted|rejected|duplicate|
  no_action`; `resolution_status`, `resolved_refinery_id`,
  `resolved_content_sha256`, `contact_purged_at`, now + `submitted_at`),
  `ReaderReportContact` (email only), `ReaderReportDecision`
  (`decision accepted|rejected|duplicate|no_action`, `actor`, `notes`,
  `corrected_at`, `correction_summary`, `publication_ref`,
  `deploy_evidence`, `created_at`, `closed_at`). Migrations head:
  `d2e3f4a5b6c7` (after 185 `e7f1a2b3c4d5`).
- Repos: `storage/reader_report_repository.py` (186; upsert + race-safe),
  `article_repository.py` style.
- Contracts: `contracts/reader_reports.py` (185 + 186 reconciliation shapes).
- Wire-test precedent: `tests/test_serving_admin_api.py`; boundaries suite
  `make test-boundaries`; serving-only I/O law: logic modules stay pure.

## Scope

**In scope**:
- `news_collector/logic/workflows/report_decisions.py` — pure transition rules
- `news_collector/storage/report_decision_repository.py` — transactional
  decision append + report status update (+ duplicate_of column migration)
- `news_collector/serving/admin_reader_reports.py` — admin router (follow the
  `admin_images.py` `build_router(verify_admin_token)` pattern) mounted from
  `api.py`, or app-level routes following the admin articles block if that
  matches api.py idiom better
- `news_collector/contracts/reader_reports.py` — decision request/response
  models (typed, no dict payloads)
- one Alembic migration on top of `d2e3f4a5b6c7` adding ONE nullable
  `duplicate_of_report_id INTEGER` column on `reader_report_decisions`
  (no FK constraint; same inspector-guarded style as 186)
- tests: rules purity, repo transactionality/audit order, wire tests

**Out of scope**: closure/`closed` transitions and publication/deploy evidence
enforcement (plan 188), contact purge (189), Astro-admin GUI wiring, email
notification to the reporter, OpenAPI regeneration concerns beyond new paths
(adding paths is allowed; moving existing ones is blocked by the pending
path-ordering decision).

## Design

1. **Transition rules (pure)**: `plan_decision(report, request) -> intended`
   validates:
   - `actor` ≠ empty; `notes` non-empty (or optional when the decision
     kind provides its own justification? NO: notes REQUIRED for all
     decisions — audit discipline).
   - `accepted` requires `corrected_at` + `correction_summary` (the
     publication/deploy evidence check comes in 188; today accepted leaves the
     report in `accepted`, NOT closed).
   - `duplicate` requires `duplicate_of_report_id` pointing at an existing
     other report (existence checked by the repository; the rule module takes
     it as input to stay pure).
   - re-decision allowed while not closed (accepted→rejected with notes, etc.);
     never back to `new`/`triaged` via decisions; `closed` winner unchangeable.
   - a `triage` action (kind `triage`, notes-only) may move `new`→`triaged`;
     nothing may move back to `new`.
2. **Repository**: `apply_report_decision(session, report_id, intended)` —
   INSERT the decision row (append-only audit: no UPDATE of past rows) and
   UPDATE `reader_reports.updated_at/status` in the same transaction;
   `reporter_email` never appears in request/response contracts beyond the
   detail endpoint's explicitly documented 420-priviledged read.
   Race rule: decisions are applied one-per-transaction, optimistic
   `with_for_update` when the backend supports it, else documented ordering via
   the runner's session discipline (mirror lifecycle repository behavior).
3. **Serving**:
   - `GET  /v1/admin/reader-reports` (filters: `status`, `resolution`,
     `problem_type`, `page_size` ≥1 ≤50, cursor) → typed envelope (list item
     WITHOUT contact/email — privacy separation at the surface).
   - `GET  /v1/admin/reader-reports/{id}` → full report + decision history +
     `reporter_email` ONLY when `contact_purged_at IS NULL` and a contact row
     exists; explicit doc line referencing the privacy contract.
   - `POST /v1/admin/reader-reports/{id}/decisions` body
     `ReportDecisionRequest` → router verifies token, loads, applies rules +
     repository; 200 with the updated report DTO (status/decision included).
     404 unknown id; 409 illegal-transition typed reason; 422 validation.
   - All routes follow verify_admin_token; bounded page sizes; cursor via the
     article pattern; NO unbounded dumps.
4. **Contracts**: `ReportActionKind` (triage|decision), `ReportDecisionKind`,
   `ReportDecisionRequest` (actor, notes, decision fields...),
   `AdminReaderReportEnvelope` (+ Item with decision history refs), detail
   DTO. Pure models on top of the 185 file; NO dict payloads.
5. **Tests**:
   - rules: every legal transition matrix line (incl. re-decision and
     refusals), duplicate existence semantics, actor/notes discipline.
   - repo: append-only audit order, status update atomicity, race-free two
     sequential decisions, contact untouched.
   - serving wire: 401/404/409/422 codes, list filter validation bounds,
     detail email-absent after `contact_purged_at` stamp, decision idempotence
     NOT promised (repeat same decision = NEW row? NO: re-posting the exact
     same decision payload to the same report returns 200 with the SAME
     state — the repository MUST ignore an exact-duplicate pending action and
     return the current answer; document `X-Reader-Report-Decision` status
     via existing decision row match before insert).
6. **Gates**: `make lint`, `make type` (committed), `make test`,
   `make test-contracts`, `make test-boundaries`, `make docs-check`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`,
   plus `make weak-tests-check` ratchet if new tests added (direct asserts).

## Done criteria

- [ ] Triaging and ALL non-closure decisions are operational, audited
      append-only, and bounded; surfaçe never leaks contact data by list path
- [ ] `closed` remains unreachable (no evidence path yet)
- [ ] Exact-duplicate decisions persist→single row audit conservation
- [ ] Migration with downgrade roundtrip; integration locks stay green
- [ ] `git diff --name-only main...HEAD` limited to in-scope files
- [ ] Ledger row 187 updated by the reviewer

## STOP conditions

- The admin surface law (Read per LAW-B4) contradicts adding POST decisions →
  check `docs/ARCHITECTURE.md` §3.6 and the /v1/admin/* comment block; abort
  and report if a rule change is needed rather than improvising.
- The migration needs more than one column → STOP (propose).
- Real duplicate-of needs FK cascade considerations → STOP (propose).
- Something in the merge/editor branches diverges → STOP.
