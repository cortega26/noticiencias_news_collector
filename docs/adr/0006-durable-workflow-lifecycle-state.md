# ADR-0006: Durable Workflow Lifecycle State

**Date**: 2026-08-22
**Status**: Proposed
**Deciders**: Engineering team

---

## Context

Operational lifecycle state — collection runs, publication attempts, editorial
decisions, and callback reconciliation — currently lives in
`Article.processing_status` plus free-form JSON in `article_metadata`. This
has been measured, not speculated, as a reliability gap (plan 060's evidence
baseline, "Operational history" row): the state cannot be queried reliably
(no typed columns to filter or join on), cannot be reconciled after a crash
or restart (no lease/heartbeat concept, no "this run was interrupted"
signal), and provides no append-only audit trail for editorial or publication
decisions — a JSON blob can be silently overwritten with no history.

Every later phase of plan 060 that touches operational state (durable
collection/publication jobs, callback reconciliation, admin observability)
depends on a queryable, typed foundation existing first. Building each of
those phases directly against ad-hoc JSON would either re-derive this schema
piecemeal or lock in the current unqueryable shape.

---

## Decision

Add five new, additive SQLite tables as the source of truth for operational
lifecycle state, to be built out in Phase 3 of the master plan
(`plans/060/spec.md`). These tables are additive: they do not remove or
rename any existing `Article` column in this ADR's scope. Existing `Article`
columns are kept as a dual-written compatibility projection during migration,
following the master plan's rollout/rollback discipline: expand → dual-write
→ compare → cut over → clean up. Cleanup (dropping the compatibility
projection) is explicitly future work, not part of what this ADR authorizes.

### `workflow_runs`

| Field | Required behavior |
|---|---|
| `id` | opaque stable ID returned by the API |
| `kind` | typed value; initially `collection` and `publication_reconciliation` |
| `idempotency_key` | nullable external/request identity; unique with kind when present |
| `status` | `queued`, `running`, `succeeded`, `failed`, `interrupted`, `cancelled` |
| `active_key` | nullable key, set to `collection` only while queued/running; unique SQLite partial index enforces single-flight |
| `requested_payload` / `summary` | versioned JSON contracts, not arbitrary hidden state |
| `error_code` / `error_detail` | stable machine code plus bounded operator detail |
| timestamps | created, started, heartbeat, finished, updated |
| `version` | optimistic transition counter |

Rules: insert before dispatch; compare-and-set transitions; a runner acquires
a lease/heartbeat; startup recovery marks expired active rows `interrupted`;
retention removes terminal rows only (default 90 days, configurable), never
queued/running rows.

### `workflow_stage_attempts`

Append-only rows keyed to `workflow_run_id`, with typed stage, attempt
number, status, input/output identity or hashes, provider/model metadata
when relevant, timestamps, error code, and bounded diagnostic JSON. A unique
`(workflow_run_id, stage, attempt_number)` constraint prevents duplicates.

### `editorial_decisions`

Append-only audit/fact-check/correction decisions keyed to article/refinery
ID, with decision type, outcome, actor class, content revision, rationale,
provenance references, and timestamps. Secrets or reader contact data never
enter this table.

### `publication_attempts`

One row per attempt, keyed to article/refinery identity, with `stage`,
`status`, branch, commit SHA, PR URL/number, deploy identity/URL, content
revision, last error, and timestamps. `status` is `pending`, `running`,
`succeeded`, `failed`, or `cancelled`. Legal stage advancement:

`prepared → pushed → pr_created → validation_passed → deployed → acknowledged`

Failures retain the current stage and set attempt status/error; a safe retry
resumes or creates a linked successor according to the stage's idempotency
rule. They do not erase prior evidence. The existing article
`processing_status` is a compatibility projection during the migration.

### `publication_events`

Persist every authenticated callback before processing. Store event kind,
schema version, delivery/idempotency key, payload hash, source SHA, received
and processed timestamps, processing status/error, and linked publication
attempts. The unique delivery key makes retries safe. Payload retention must
remain bounded and must exclude secrets.

`source_snapshots` and `media_assets` are deliberately deferred until phases
8 and 9 prove concrete consumers. They are not prerequisites for durable
jobs.

Phase 3 of the master plan implements exactly what this ADR records — the
table definitions above are not a sketch to be redesigned at implementation
time.

---

## Rollback

If a table proves unnecessary or wrongly shaped after Phase 3 implementation
experience, it can be dropped or altered in a follow-up migration without
affecting the other four — the tables are independent and additive, not a
single monolithic schema change. The `Article` compatibility projection
remains the fallback read path until an explicit future cleanup phase removes
it, so a rollback of the new tables does not strand any consumer.

---

## Consequences

**Positive**:
- Operational state becomes queryable and joinable (typed columns, indexes)
  instead of opaque JSON.
- Crash/restart recovery gets a defined mechanism (lease/heartbeat +
  startup recovery marking expired `active_key` rows `interrupted`).
- Editorial and publication history becomes append-only and auditable —
  decisions are never silently overwritten.
- Retry semantics are explicit per stage instead of ad hoc.

**Negative**:
- Five new tables add schema surface and migration burden (dual-write during
  transition, eventual cleanup phase).
- `workflow_runs`' single-flight partial index constrains collection runs to
  one active run at a time by design — any future need for concurrent
  collection runs requires revisiting `active_key`'s semantics.
- Dual-writing to both the new tables and the existing `Article` columns
  during migration is temporary extra write cost and code complexity.

---

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Keep the JSON-blob approach on `Article.article_metadata` | Rejected — unqueryable, already measured as a reliability gap (plan 060 evidence baseline) |
| Move to PostgreSQL for operational state | Rejected — already settled and out of scope; plan 046, operator decision 2026-08-11, SQLite-only |
| External state store (Redis, Kafka, etc.) | Rejected — explicitly out of scope per master plan; no new infrastructure |
