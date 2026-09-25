# Plan 060 / Phase 5b — Publication-attempt events and stale-attempt reconciliation

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> annotate `plans/060/todo.md` Phase 5 items 3, 4 and 6 (5a already annotated
> item 2; dashboard evidence stays pending), update
> `docs/PIPELINE_CONTRACTS.md` and validate the plans ledger.
>
> **Drift check (run first)**:
> `git diff --stat 88dd9c4..HEAD -- news_collector/storage/lifecycle_repository.py news_collector/storage/database.py news_collector/serving/webhook_handler.py news_collector/serving/api.py news_collector/storage/webhook_receipt_repository.py news_collector/storage/models.py tests/unit/storage tests/integration/test_webhook_receipts.py docs/PIPELINE_CONTRACTS.md`
> On any in-scope drift, re-verify the "Current state" references; on a
> mismatch treat it as a STOP.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED (additive event rows + best-effort writes; callback wire
  behavior and transition semantics unchanged)
- **Depends on**: Phase 3a/3b/3c (lifecycle tables + repositories), Phase 4c
  (publication workflow), Phase 5a (durable webhook receipts). Second slice of
  Phase 5; dashboard evidence (5c) follows.
- **Category**: reliability (plan 060 critical path)
- **Planned at**: backend `88dd9c4`, 2026-09-25 (branches off the Phase 5a
  branch `advisor/060-phase-5a-webhook-receipts`; 5a must land first)

## Why this phase exists

Plan 060 Phase 5 items 3–4 and the acceptance criteria:

> 3. Map validation and publish-complete events to legal
>    `publication_attempts` transitions. Processing exceptions update the event
>    to retryable/failed and remain operator-visible.
> 4. Add a scheduled/manual reconciler for stale `pr_created`/`deployed`
>    attempts. It may query GitHub/deployment evidence and replay stored
>    events. It must not create duplicate PRs or mark published without
>    deployment evidence.
>
> **Acceptance:** lost callback, duplicate callback, out-of-order callback,
> backend restart, processing exception, and stale open PR all have
> integration tests; every fixture reaches a truthful terminal or actionable
> state; no duplicate PR is created.

Phase 5a made deliveries durable (receipts, duplicate replay, error
retention), covering lost/duplicate/restart/error. Two gaps remain:

1. **No per-attempt audit log.** `publication_events` exists since Phase 3a
   with zero writers. A transition is today only visible as the row's *current*
   state; when, why and by which callback it changed is unrecoverable. The
   state machine itself is implicit (any CAS from any state passes), and the
   existing race comments show at least `PUBLISHING → PR_CREATED`,
   `PUBLISHING → REJECTED` and `PUBLISHING → COMPLETED` must stay legal.
2. **No reconciler.** A `failed` receipt stays failed forever; a callback that
   arrived before its attempt row existed is lost to the attempt; an attempt
   can sit `PR_CREATED` after its article was completed/rejected through a
   legacy path whose dual-write half missed. Nothing detects or repairs this,
   and nothing distinguishes "stale, needs a human" from "evidence proves it
   deployed".

This slice adds the event audit + explicit legal-transition map, then a
manual reconciler that replays stored receipts and applies evidence-backed
transitions only — never creating a PR, never publishing without deploy
evidence.

## Current state (verified at `88dd9c4`)

- `storage/models.py:864-908` — `PublicationEvent`
  (`publication_attempt_id` FK RESTRICT, `event_type` CHECK on
  `pr_created|check_passed|deployed|rejected`, `occurred_at`, `details JSON`).
  Zero writers anywhere (grep over `news_collector/`, `scripts/`, `tests/`).
- `storage/lifecycle_repository.py:158-360` — `LifecycleRepository` has
  attempts (append + CAS) and decisions; no event methods, no legality map,
  no lookup by `refinery_id`, no stale query. `transition_publication_attempt`
  (:234) is a generic CAS with no legality check.
- `storage/database.py:378-428` `_dual_write_pr_created`,
  `:464-509` `_dual_write_transition` — best-effort (never raise), CAS from
  the row's *actual* state, no event rows. `:609-615`
  `mark_article_publishing` records PUBLISHING.
- `storage/database.py:430-462` — `reject_publication_attempts` /
  `complete_publication_attempts` fan out to `_dual_write_transition`.
- `serving/webhook_handler.py:115-213` — `process_validation_result` /
  `process_publish_complete`; validation **pass** is a pure no-op
  (`{"action": "noop", "reason": "validation_passed"}`); fail/complete call
  the facade methods above. Receipt-first orchestration (5a) stays in this
  module (`handle_webhook_event:36`, `_dispatch:91`).
- `storage/webhook_receipt_repository.py:63-166` — `record_receipt`,
  `mark_processing`, `mark_processed`, `mark_failed`, `get_receipt`; no
  list-by-status, no payload search.
- Legacy projection: `articles.processing_status` (`publishing`,
  `completed`, `rejected`) plus `published_url`; `article_metadata
  ["publication"]` (`article_repository.py:285-472`). `complete_publication_attempts`
  sets `published_url` only when a deploy URL was provided.
- `PROrchestrator.attempt_recovery` (`logic/workflows/pr_orchestrator.py:160`)
  recovers only `PUBLISHING` during a refinery run; no `PR_CREATED`
  reconciler exists. No scheduler infrastructure — ops scripts are manual
  (`scripts/ops/prune_workflow_runs.py` docstring).
- `WorkflowRun.run_type` is free-form `String(50)` (models.py:568); the
  master spec names `publication_reconciliation` as a legitimate kind.
- Baselines: `pytest tests/unit/storage tests/integration/test_webhook_receipts.py tests/integration/test_publication_callback_contract.py --no-cov -q` (record the count at Step 0).

## Scope

**In scope**:

- `news_collector/storage/lifecycle_repository.py` — legality map +
  `is_legal_publication_transition`; `PublicationEventView`;
  `record_publication_event`; `get_publication_events_for_attempt`;
  `apply_publication_transition` (legality + CAS + event in one
  transaction); `find_latest_publication_attempt_by_refinery_id`;
  `list_stale_publication_attempts`.
- `news_collector/storage/database.py` — the three dual-write paths record
  `pr_created` / `rejected` / `deployed` events via
  `apply_publication_transition`; behavior otherwise unchanged (still
  best-effort, still CAS from actual state, still never raises).
- `news_collector/storage/webhook_receipt_repository.py` —
  `list_unprocessed_receipts(limit)` (status `received`/`failed`, oldest
  first) for the reconciler.
- NEW `news_collector/logic/workflows/publication_callbacks.py` — typed
  `apply_validation_result` / `apply_publish_complete` (bodies moved from
  `serving/webhook_handler.py`); validation pass records a best-effort
  `check_passed` event when the attempt can be identified by `refinery_id`.
- `news_collector/serving/webhook_handler.py` — `process_validation_result` /
  `process_publish_complete` become thin delegates to the workflow module
  (same names, same signatures, so existing direct-call and `patch(...)`
  tests keep working); receipt orchestration untouched.
- NEW `news_collector/logic/workflows/publication_reconciliation.py` —
  `PublicationReconciliationWorkflow.run(...)`, typed result dataclasses,
  replay + evidence-backed transitions + `workflow_runs` audit row.
- NEW `scripts/ops/reconcile_publication_attempts.py` — manual CLI wrapper
  (`--stale-minutes`, `--limit`, `--dry-run`).
- Tests: lifecycle events/legality/reconciler/receipt-list unit tests;
  out-of-order and stale-PR integration tests; script test.
- `docs/PIPELINE_CONTRACTS.md`; `plans/060/todo.md`.

**Out of scope**:

- Dashboard health (5c) and any admin HTTP surface for the reconciler.
- GitHub/deployment network queries: the reconciler's evidence sources are
  stored receipts and the legacy DB projection; an injected GitHub evidence
  provider is deferred until a concrete caller needs it (master spec says
  "may query", not "must").
- New event types / schema migration: `publication_events` already has the
  columns and four event types this phase needs.
- Frontend sender changes, receipt schema changes, `PROrchestrator`
  `PUBLISHING` recovery, `publication_attempts` state vocabulary changes.
- Changing callback wire behavior (always 202 after durable receipt, 422 on
  invalid payload, auth) or transition semantics for existing callers.

## Design

### Legal transitions (storage-level, explicit)

`LEGAL_PUBLICATION_TRANSITIONS` (frozen map in `lifecycle_repository.py`):

| from | to |
|---|---|
| `PUBLISHING` | `PR_CREATED`, `REJECTED`, `COMPLETED` |
| `PR_CREATED` | `REJECTED`, `COMPLETED` |
| `REJECTED` | — terminal |
| `COMPLETED` | — terminal |

`PUBLISHING → REJECTED/COMPLETED` is deliberate: `test_reject_reads_actual_
current_state_not_assumed_pr_created` (plan 3c) proves a callback can race
ahead of `mark_article_published`'s dual-write. No other transition is legal;
`is_legal_publication_transition(from, to)` is pure and importable by policy
callers.

### `apply_publication_transition` (audited CAS)

One session: validate legality (invalid → log error, return `False`, no
write), `UPDATE ... WHERE id AND state = from_state`; on rowcount 1 insert a
`publication_events` row in the same transaction; on CAS miss log and return
`False`. `event_type` is pre-validated against the model's
`PUBLICATION_EVENT_TYPE_VALUES` so a bad type can never roll back a valid
state change. The existing generic `transition_publication_attempt` stays
untouched (its callers/tests use it as a raw CAS).

### Event recording at the dual-write seams

- `_dual_write_pr_created` → `apply_publication_transition(...,
  event_type="pr_created", details={"pr_url", "refinery_id"})`; the fallback
  insert (`record_publication_attempt`) also appends a `pr_created` event via
  `record_publication_event` (best-effort, same outer `try`).
- `_dual_write_transition` → `apply_publication_transition(..., event_type=
  "rejected"|"deployed", details={"reason"|"deploy_url", "refinery_id"})`.
- Validation pass (`apply_validation_result`) looks up the latest attempt by
  `refinery_id` and appends `check_passed` with `{commit_sha, branch,
  delivery_key?}`; unknown attempt or any failure is logged, never raised
  (the legacy pass path stays a no-op in its return value).

Bounded details only: no full payloads, no tokens, no reader data.

### Callback module move (dependency direction)

`logic/workflows/publication_callbacks.py` owns the callback *effects*;
`serving/webhook_handler.py` keeps the receipt-first orchestration and
re-exports `process_validation_result` / `process_publish_complete` as thin
delegates. Reason: the reconciler is a workflow consumer of the same effects
and must not import `serving/` (ARCHITECTURE.md: edges depend inward;
serving owns dispatch, state transitions stay in workflows/storage).

### Reconciler (`PublicationReconciliationWorkflow`)

Inputs: `stale_minutes` (default 60), `limit` (default 100), `dry_run`.

1. Candidates: rows in `PR_CREATED` with `started_at` older than the cutoff,
   oldest first, `limit`.
2. Replay: `list_unprocessed_receipts`; parse each payload with
   `parse_webhook_payload`; if any `publication_ids` matches a candidate's
   `refinery_id`, replay through `apply_*` (mark receipt `processing` →
   `processed` with the result, or `failed` with the error). Malformed stored
   payloads are reported (`malformed_payload`), never guessed.
3. Evidence-backed repairs for candidates still `PR_CREATED`:
   - legacy article `completed` **and** deploy evidence
     (`published_url` set, or a processed `publish_complete` receipt with a
     deploy URL) → `COMPLETED` + `deployed` event;
   - legacy article `completed` without deploy evidence →
     `missing_deploy_evidence` (stays `PR_CREATED`);
   - legacy article `rejected` → `REJECTED` + `rejected` event (reason from
     legacy metadata);
   - otherwise → `stale_pr_open` (actionable, unchanged).
4. Never calls `create_pr`/`create_pull_request`; never sets `published_url`
   directly (only `complete_publication_attempts` does, via the callback
   effects).
5. Non-dry runs persist a `workflow_runs` row `run_type=
   'publication_reconciliation'` (queued→running→succeeded/failed,
   `run_metadata.summary`); dry runs write nothing.

Typed frozen result: `ReconciliationSummary(scanned, completed, rejected,
replayed, stale_pr_open, missing_deploy_evidence, malformed_payload,
unmatched_receipts, dry_run)` and per-attempt `ReconciliationAction`.

### Ops script

`scripts/ops/reconcile_publication_attempts.py` follows
`scripts/ops/prune_workflow_runs.py`: sys.path bootstrap, argparse, prints
the summary, exit 0 on success (stale findings are a successful report, not
an error), exit 1 on unexpected failure. No scheduler; wiring an external
timer is out of scope (same rationale as plan 4a's prune script).

## Test plan

- Repository (`tests/unit/storage/test_lifecycle_publication_events.py`):
  event append/read round-trip; legality map truth table;
  `apply_publication_transition` appends exactly one event on success, none on
  CAS miss/illegal/invalid type; `find_latest_..._by_refinery_id`;
  `list_stale_publication_attempts` respects state/age/limit.
- Dual-write events (extend `tests/unit/storage/test_lifecycle_dual_write.py`):
  `mark_article_publishing` → `mark_article_published` →
  `complete`/`reject` produce `pr_created`/`deployed`/`rejected` events;
  failures stay swallowed and leave no event.
- Receipts (`tests/unit/storage/test_webhook_receipt_repository.py`):
  `list_unprocessed_receipts` returns `received`+`failed` oldest-first,
  excludes `processed`.
- Callbacks (`tests/unit/logic/workflows/test_publication_callbacks.py`):
  validation pass records `check_passed` when the attempt exists, no-op
  otherwise; serving delegates preserve 5a behavior (patch target test still
  green).
- Reconciler (`tests/integration/test_publication_reconciliation.py`):
  failed `publish_complete` receipt replay completes the attempt + event;
  stale open PR with no evidence stays `PR_CREATED` and reports actionable;
  out-of-order legacy `completed` + `published_url` fixes a `PR_CREATED`
  attempt; legacy `completed` without deploy evidence is not published;
  legacy `rejected` transitions; already-terminal attempts skipped; dry-run
  mutates nothing; malformed payload reported; no PR creation API is ever
  touched.
- Script (`tests/unit/ops/test_reconcile_publication_attempts.py`): dry-run
  and real run summaries, exit codes.
- Endpoint/callback suites (`tests/test_webhook.py`,
  `tests/integration/test_webhook_receipts.py`,
  `tests/integration/test_publication_callback_contract.py`) stay green
  unmodified except for receipt-event assertions that are additive.

## Steps

### Step 0: Baseline + drift

Record the baseline count; STOP on drift/non-green.

### Step 1: Storage — legality + events + queries + tests

`LEGAL_PUBLICATION_TRANSITIONS`, `PublicationEventView`,
`record_publication_event`, `get_publication_events_for_attempt`,
`apply_publication_transition`, `find_latest_publication_attempt_by_refinery_id`,
`list_stale_publication_attempts`; unit tests.

### Step 2: Dual-write event recording + tests

Rewire `_dual_write_pr_created` / `_dual_write_transition` /
`mark_article_publishing` fallback through the audited method; assert events;
all existing dual-write tests stay green.

### Step 3: Callback move + check_passed + tests

NEW `logic/workflows/publication_callbacks.py`; serving delegates; tests.

### Step 4: Reconciler + ops script + tests

Receipt list method; workflow module; evidence rules; audit row; CLI; unit +
integration tests incl. out-of-order and stale-PR.

### Step 5: Gates + docs

`make lint && make type && make test && make test-contracts && make
test-boundaries`; `make quality-gate`; `docs/PIPELINE_CONTRACTS.md`;
`plans/060/todo.md` items 3/4/6 annotations; ledger.

## Done criteria (machine-checkable)

- [ ] Baseline + full gates exit 0 (`test-contracts` + `test-boundaries`
      included — storage/serving/workflow change class)
- [ ] Every audited transition appends exactly one `publication_events` row;
      illegal transitions and CAS misses append none (tests)
- [ ] Validation pass records `check_passed` when an attempt matches, and
      never raises (test)
- [ ] Failed `publish_complete` receipt replay completes its stale attempt
      and marks the receipt processed (integration test)
- [ ] Stale `PR_CREATED` attempt with no evidence stays `PR_CREATED` and is
      reported actionable; no `create_pull_request` call and no
      `published_url` write anywhere in the reconciler (test)
- [ ] Legacy `completed` without deploy evidence is never transitioned to
      `COMPLETED` (test)
- [ ] Out-of-order case (legacy article terminal, attempt still `PR_CREATED`)
      reaches the matching terminal state when evidence exists (test)
- [ ] Dry run mutates no rows; real run records one
      `publication_reconciliation` `workflow_runs` row (test)
- [ ] `docs/PIPELINE_CONTRACTS.md` + plan checkboxes reconciled; ledger OK
- [ ] `git diff --name-only` only in-scope files

## STOP conditions

- Drift/baseline not clean.
- Any change to callback wire behavior (202/422/auth), receipt semantics,
  existing `transition_publication_attempt` behavior, or legacy
  `reject`/`complete` transition semantics.
- A legality rule that would reject any transition an existing caller/test
  performs (e.g. `PUBLISHING → REJECTED` is legal by design).
- Any new migration needed (the phase must be schema-additive-free).
- A test requires network, a GitHub token, or the frontend checkout.

## Git workflow

- Branch: `advisor/060-phase-5b-attempt-events-reconciler` (stacked on
  `advisor/060-phase-5a-webhook-receipts`).
- Commits: `feat(storage): audit publication-attempt transitions with events`,
  `refactor(serving): move callback effects into a workflow module`,
  `feat(publication): reconcile stale attempts from stored evidence`.
- Do NOT push/PR unless instructed.
