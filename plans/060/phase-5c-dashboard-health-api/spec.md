# Plan 060 / Phase 5c — Dashboard health evidence API

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> annotate `plans/060/todo.md` Phase 5 item 5 (partial: backend evidence API
> done; frontend dashboard wiring remains 5d), update
> `docs/PIPELINE_CONTRACTS.md`, regenerate the admin OpenAPI artifact and
> validate the plans ledger.
>
> **Drift check (run first)**:
> `git diff --stat 6d0ad4c..HEAD -- news_collector/contracts/admin.py news_collector/storage/lifecycle_repository.py news_collector/storage/webhook_receipt_repository.py news_collector/serving/api.py tests/test_serving_admin_api.py docs/PIPELINE_CONTRACTS.md apps/admin/openapi.json`
> On any in-scope drift, re-verify the "Current state" references; on a
> mismatch treat it as a STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (additive read endpoint + aggregate queries; nothing existing
  changes)
- **Depends on**: Phase 3b/3c (lifecycle repository), Phase 5a (receipts),
  Phase 5b (events + reconciler). Backend half of Phase 5 item 5; the
  frontend dashboard wiring is 5d (cross-repo).
- **Category**: observability (plan 060 critical path)
- **Planned at**: backend `6d0ad4c`, 2026-09-25

## Why this phase exists

Plan 060 Phase 5 item 5:

> Drive dashboard schema, validation, hero/image, callback, and publication
> health from real attempt/event/check records. Missing evidence is `unknown`,
> not pass.

The frontend dashboard (`../noticiencias/src/pages/admin/dashboard.astro`)
is a static CI-built page reading `data/metrics/pipeline-metrics.json`.
Phase 1 already replaced two hard-coded `pass` states with `unknown`, but
nothing yet drives **callback** or **publication** health from the durable
records this program created (`publication_attempts`, `publication_events`,
`webhook_receipts`). Those records live only in the backend DB, so the
backend must expose them as a typed, authenticated evidence read before the
frontend can consume them.

This phase adds that backend evidence API. The contract's central rule is
the plan's: an area with **no records at all** reports
`evidence: "none"` and `status: "unknown"` — never `pass` merely because a
query returned zero rows. 5d (frontend) will consume it together with the
frontend-owned schema/hero-image/lint records.

## Current state (verified at `6d0ad4c`)

- `contracts/admin.py` — typed `/v1/admin/*` boundary shapes
  (`AdminSourceHealthEnvelope:97`, `AdminQualityRecentEnvelope:322`);
  `serving/api.py` maps each endpoint to one of these with
  `verify_admin_token` (`serving/api.py:724`).
- `storage/lifecycle_repository.py` — attempts/events/decisions read+write;
  no aggregate queries (no counts by state, no oldest/latest).
- `storage/webhook_receipt_repository.py` — `list_unprocessed_receipts`;
  no counts-by-status or age aggregates.
- `serving/api.py:1728` — `admin_quality_recent` is the closest read-model
  endpoint pattern (typed envelope + `meta.generated_at`).
- `docs/PIPELINE_CONTRACTS.md:146-148` — receipts/events/reconciler
  paragraphs; the dashboard evidence read is not documented yet.
- Admin OpenAPI artifact `apps/admin/openapi.json` + generated TS
  (`apps/admin/src/lib/generated/api.d.ts`) are CI-checked
  (`make admin-contracts-check`); a new route requires regeneration.
- Baselines: `pytest tests/test_serving_admin_api.py tests/unit/storage
  --no-cov -q` (record the count at Step 0).

## Scope

**In scope**:

- `news_collector/contracts/admin.py` — `AdminDashboardEvidence` +
  `AdminDashboardHealthEnvelope` (+ status Literal).
- `news_collector/storage/lifecycle_repository.py` — attempt counts by
  state, oldest non-terminal attempt age source, latest attempt/event
  timestamps, event counts by type.
- `news_collector/storage/webhook_receipt_repository.py` — receipt counts
  by status, oldest unprocessed receipt, latest receipt timestamp.
- NEW `news_collector/serving/dashboard_health.py` — pure-ish builder
  (`build_dashboard_health(db, *, now=None)`) with the status rules.
- `news_collector/serving/api.py` — `GET /v1/admin/dashboard/health`
  (admin auth, typed response).
- Tests: repository aggregates, builder unit tests (empty + each status
  rule + ages), endpoint auth/shape test.
- `docs/PIPELINE_CONTRACTS.md`; `plans/060/todo.md`; regenerated
  `apps/admin/openapi.json` + `apps/admin/src/lib/generated/api.d.ts`.

**Out of scope**:

- Frontend `generate-metrics.js` / `dashboard.astro` changes (5d) and any
  schema/hero-image/lint metric instrumentation (frontend-owned records).
- New HTTP surface for the reconciler (its audit rows are workflow_runs;
  this endpoint reads attempts/events/receipts only).
- Notifications/alerting; this is a read model for a dashboard.
- Any change to existing endpoints, contracts, or table schemas (no
  migration).

## Design

### Contract (`contracts/admin.py`)

```python
DashboardHealthStatus = Literal["pass", "warning", "fail", "unknown"]

class AdminDashboardEvidence(BaseModel):
    status: DashboardHealthStatus
    evidence: Literal["present", "none"]
    detail: str = ""
    measured_at: Optional[datetime] = None
    oldest_pending_age_seconds: Optional[int] = None
    counts: Dict[str, int] = Field(default_factory=dict)

class AdminDashboardHealthEnvelope(BaseModel):
    generated_at: datetime
    publication: AdminDashboardEvidence
    callbacks: AdminDashboardEvidence
    validation: AdminDashboardEvidence
```

`counts` always carries the area's full known key set (zeros when absent);
`evidence` is the sole unknown signal, so typed consumers get a stable
shape.

### Status rules (all from durable records)

**publication** — `publication_attempts` + `publication_events`:

| condition | status |
|---|---|
| zero attempts ever | `unknown`, `evidence="none"` |
| any `PUBLISHING` older than `PUBLISHING_TIMEOUT_SECONDS` (1h, imported from `pr_orchestrator`) | `fail` |
| any `PR_CREATED` older than `DEFAULT_STALE_MINUTES` (60, imported from `publication_reconciliation`) | `warning` |
| otherwise | `pass` |

counts: `PUBLISHING`, `PR_CREATED`, `REJECTED`, `COMPLETED`.
`oldest_pending_age_seconds`: oldest non-terminal attempt.
`measured_at`: newest attempt `created_at`.

**callbacks** — `webhook_receipts`:

| condition | status |
|---|---|
| zero receipts ever | `unknown`, `evidence="none"` |
| any `failed` | `fail` |
| any `received` (pending) | `warning` |
| otherwise (all `processed`) | `pass` |

counts: `received`, `processed`, `failed`.
`oldest_pending_age_seconds`: oldest `received`/`failed` receipt.
`measured_at`: newest `received_at`.

**validation** — `publication_events` of type `check_passed`/`rejected`:

| condition | status |
|---|---|
| neither event ever | `unknown`, `evidence="none"` |
| any `rejected` | `warning` (Content Guard blocked at least one attempt) |
| otherwise (`check_passed` only) | `pass` |

counts: `check_passed`, `rejected`.
`measured_at`: newest of those events.

Statuses are derived in one place (`serving/dashboard_health.py`) so the
endpoint stays a thin response mapper. Ages use a tz-normalizing helper
(SQLite may return naive datetimes; a naive value is assumed UTC, matching
`PROrchestrator.attempt_recovery`'s precedent).

### Endpoint

`GET /v1/admin/dashboard/health` — `verify_admin_token`, returns
`AdminDashboardHealthEnvelope`. Read-only; no request body/params.
`generated_at` is the builder's `now`.

## Test plan

- Repository (`tests/unit/storage/test_lifecycle_publication_events.py`,
  `tests/unit/storage/test_webhook_receipt_repository.py`): counts by
  state/status/type; oldest non-terminal / oldest unprocessed / latest
  timestamps; empty DB → empty dict / `None`.
- Builder (`tests/unit/serving/test_dashboard_health.py`, real SQLite,
  frozen `now`): empty DB → all three `unknown`/`evidence="none"` with full
  key sets; stuck `PUBLISHING` → publication `fail`; stale `PR_CREATED` →
  `warning`; all-terminal → `pass`; `failed` receipt → callbacks `fail`;
  `received` → `warning`; all processed → `pass`; rejected event →
  validation `warning`; check_passed-only → `pass`; ages computed exactly
  against the frozen now.
- Endpoint (`tests/test_serving_admin_api.py`): 200 + shape with auth;
  401 without; empty-DB response is all-`unknown` (never `pass`).
- Admin contracts: regenerated artifact passes
  `pytest tests/contracts/test_admin_openapi.py`.

## Steps

### Step 0: Baseline + drift

Record the baseline count; STOP on drift/non-green.

### Step 1: Contract + repository aggregates + tests

`AdminDashboardEvidence` / `AdminDashboardHealthEnvelope`; lifecycle and
receipt aggregate methods; unit tests.

### Step 2: Builder + endpoint + tests

`serving/dashboard_health.py`; route in `serving/api.py`; builder +
endpoint tests.

### Step 3: Gates + artifacts + docs

`make admin-contracts-generate`; `make lint && make type && make test &&
make test-contracts && make test-boundaries`; `make quality-gate`;
`docs/PIPELINE_CONTRACTS.md`; `plans/060/todo.md` item 5 annotation; ledger.

## Done criteria (machine-checkable)

- [ ] Baseline + full gates exit 0
- [ ] Empty DB yields all three areas `unknown`/`evidence="none"`, never
      `pass` (builder + endpoint tests)
- [ ] Each status rule has a test proving its boundary (stuck, stale,
      failed, pending, rejected, clean)
- [ ] `counts` always contains the full known key set per area (test)
- [ ] Endpoint is admin-token protected and typed; behavior matches
      `/v1/admin/*` conventions (tests)
- [ ] `apps/admin/openapi.json` + generated TS regenerated and
      `tests/contracts/test_admin_openapi.py` green
- [ ] `docs/PIPELINE_CONTRACTS.md` + `plans/060/todo.md` reconciled; ledger
      OK
- [ ] `git diff --name-only` only in-scope files

## STOP conditions

- Drift/baseline not clean.
- Any existing endpoint, contract field, repository method signature, or
  table schema must change (this phase is additive only).
- A status rule would require frontend-owned records to decide backend
  health (keep the split honest; that belongs to 5d).
- The admin OpenAPI regeneration produces diffs beyond the new route.

## Git workflow

- Branch: `advisor/060-phase-5c-dashboard-health-api` (off `main`).
- Commit: `feat(serving): expose dashboard health evidence from durable records`.
- Do NOT push/PR unless instructed.
