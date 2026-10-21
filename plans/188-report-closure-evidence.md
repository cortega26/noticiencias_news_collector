# Plan 188: Reader reports — publication/deploy evidence before closure (060 Phase 10, item 5)

> Execute; run every verification; stop on STOP.
> **Drift check**: `git diff --stat <187-merge-sha>..HEAD -- news_collector/contracts news_collector/logic/workflows news_collector/storage news_collector/serving alembic/versions tests` — and confirm plan 187 is merged before starting.

## Status

- **Priority**: P2 (060 Phase 10)
- **Effort**: M
- **Risk**: MEDIUM (first closure path; evidence rules must be strict)
- **Depends on**: plans 185 (`51d01787`), 186 (`fb2e77f1`), **187 (merged — read its report first)**
- **Category**: serving / admin workflow dispatch (closure rules)
- **Planned at**: backend `83e18579`, 2026-10-20

## Why this matters

An accepted correction must not "close" until the corrected content is
**actually published and deployed**, with the ledger pointing at real
evidence. This closes Phase 10's trust loop: report → decision → publication
proof → authenticated closure.

## Current state (verified anchors)

- Evidence chain: the frontend `publish_complete` webhook (receipt-first via
  `serving/webhook_handler.py:45-59`) → `apply_publish_complete` →
  `articles.complete_publication_attempts(refinery_ids, deploy_url)`
  (`article_repository.py:427` — sets `Article.published_url = deploy_url`,
  `published_at`, state COMPLETED) → dual-write `_dual_write_transition`
  (`database.py:539`; `PUBLICATION_TRANSITION_EVENT_TYPES` maps
  `COMPLETED → "deployed"`, `details={"deploy_url": deploy_url[:500]}`,
  applied to the article's latest `publication_attempts` row, CAS-verified).
- `PublicationAttemptRecord` (`models.py:791`): `refinery_id`, `state`
  (PUBLISHING|PR_CREATED|REJECTED|COMPLETED), `pr_url`, `branch_name`,
  `details`, `attempt_number` (latest = max by `(attempt_number, id)`).
- `PublicationEvent` (`models.py:864`): `event_type ∈ {pr_created,
  check_passed, deployed, rejected}`, `occurred_at`, `details`.
- Report side (185): `ReaderReportDecision.closed_at` nullable — **closure is
  a decision-row timestamp, NOT a new report status** (the `reader_reports.
  status` CHECK holds 5 values without `closed`; do NOT add one).
  `ReaderReport.resolved_refinery_id` + `resolved_content_sha256` are stamped
  by the 185 resolver; re-running the resolver after a republish gives the
  **current** content revision for the delta proof.
- 187 added the admin decision surface + its duplicate-payload idempotency
  rule and (per its report) the `duplicate_of_report_id` migration; mirror its
  request/response and purity conventions. An accepted decision is reachable
  but `closed` is unreachable — this slice adds the ONLY transition to it.

## Scope

**In scope**:
- `news_collector/logic/workflows/report_closure.py` — pure evidence rules
- `news_collector/storage/` — closure application (extend
  `reader_report_repository` or a sibling module; same transactional style)
- `news_collector/serving/` — `POST /v1/admin/reader-reports/{id}/closure`
  (+ its part of the detail DTO: closure state/refs)
- `news_collector/contracts/reader_reports.py` — closure request/response
- tests (rules / repo / wire); NO migration (no new columns needed)

**Out of scope**: contact purge (189), email notification to the reporter,
Astro admin GUI wiring, Worker/frontend changes, changing the deploy
pipeline, `reader_reports.status` vocabulary changes.

## Design

1. **Pure rules** (`report_closure.py`), all evidence passed in, no I/O:
   - Only the report's **latest decision row** may be closed; it must be
     `accepted` (the other kinds closed *at decision time* already — if 187
     shipped otherwise, match what it reports).
   - `accepted` closure requires:
     a. `publication_ref` resolves (by attempt id, else by `pr_url` 1:1) to a
        `PublicationAttemptRecord` for **this report's**
        `resolved_refinery_id`, in state `COMPLETED`, with a
        `PublicationEvent(event_type="deployed")` — stale/attempts for other
        articles are typed refusals (`evidence_not_for_report`,
        `attempt_not_completed`, `no_deployed_event`).
     b. `deploy_evidence` normalizes (185 `normalize_published_url`) to the
        SAME url the deploy wrote (`Article.published_url` or the deployed
        event's `details.deploy_url`) — mismatch → `deploy_evidence_mismatch`.
     c. For `content_*` problem types: re-resolved identity
        (`resolve_report_identity` on the report's `article_url`) must yield a
        content revision **different from** `resolved_content_sha256`
        (`content_revision_unchanged` otherwise) — the *proof the correction
        shipped*. Non-content types (`technical_*`) may close without the
        delta (publish pipeline untouched by them) — the delta becomes a
        documented soft rule there.
   - Actor/notes discipline mirrors 187 (exact-duplicate payload idempotent —
     closing twice with the identical payload returns the same closed state,
     no second row).
2. **Repository**: `close_report(session, report_id, closure)` — one
   transaction: UPDATE the latest decision row (`closed_at=now`, store the
   resolved attempt id + resolved deploy url inside `publication_ref`/
   `deploy_evidence` already provided) — no other rows change; race guarded
   like 187 (optimistic re-check inside the transaction; integrity-error
   replay mirrors 186/187 patterns).
3. **Serving**: POST `/v1/admin/reader-reports/{id}/closure` → typed request;
   404 unknown id; 409 typed mismatch reasons; 200 returns the closed DTO with
   the evidence links; `verify_admin_token`; detail DTO gains closure fields.
   No unbounded list; no direct writes outside the repository.
4. **Contracts**: `ReportClosureRequest` (actor, notes optional, publication_
   ref (attempt id or pr URL), deploy_evidence (url)), `ReportClosureView`
   (decision id, closed_at, attempt_id, deployed url, delta proven flag).
5. **Tests**: rule matrix (each refusal), delta proof vs unchanged content,
   non-content exemption, pr_url-vs-attempt-id resolution, repo
   transactionality + race replay, wire codes (401/404/409/200),
   duplicate-payload idempotency. Engine-proof the migration absence: schema
   parity tests still pass untouched.

## Done criteria

- [ ] `closed` is ONLY reachable via evidenced closure (409 matrix proven)
- [ ] The ledger row stores publication + deploy evidence that a third party
      can trace to `publication_attempts`/`publication_events`
- [ ] Accepted corrections of `content_*` types close only with shipped-new-
      content proof; audit trail append-only
- [ ] Gates: `make lint`, `make type` (committed), `make test`,
      `make test-contracts`, `make test-boundaries`, `make docs-check`,
      `make inventory-refresh && make inventory-check`,
      `make plans-ledger-check`

## STOP conditions

- 187's realized shapes differ from this plan's assumptions in a way that
  changes the closure data model (e.g. it already allows `closed`) → read its
  report and reconcile; if unresolvable, STOP before writing.
- A deploy can be observed only by probing live URLs from the backend (no
  persisted deploy_url) → STOP (do not invent live probing; report).
- Any need for a migration beyond what 187 leaves (STOP: propose first).
- Any direct database write from serving handlers → STOP (boundary law).
