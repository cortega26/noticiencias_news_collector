# Plan 132: One bad webhook receipt must not block the inbox drain forever

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- scripts/ops/pull_webhook_receipts.py news_collector/storage/webhook_pull_repository.py news_collector/contracts/webhook.py tests/ spec-webhook-inbox-pull.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

`scripts/ops/pull_webhook_receipts.py` replays hosted frontend callbacks into the
local system of record (ADR-0011). It drains **strictly in order** and stops at
the first receipt it cannot acknowledge. A receipt whose payload the local
contract cannot parse is re-claimed on every pass (its row is marked `failed`,
and `failed` is exactly what the retry pass claims) and never leaves the head of
the queue. The script then exits non-zero forever. Consequences: every later
`check_passed` / `deployed` delivery for other articles stays unapplied
(articles stuck in `publishing`, no `COMPLETED`/`REJECTED` transition), and any
scheduler wired to the exit code alarms on every run. The tool's own design doc
says the opposite of what it does — `spec-webhook-inbox-pull.md:83-85`: "Exit 0
on a completed pass (malformed rows are a report, like the reconciler), 1 on an
unexpected failure (auth/connection)". The operator's deploy checklist
(`todo-webhook-inbox-deploy.md`, untracked) plans a systemd timer every 15
minutes, which turns a single poison row into a permanent 15-minute alarm loop.

## Current state

- `scripts/ops/pull_webhook_receipts.py` — the CLI: fetch → claim → replay →
  settle → summary → exit code. Key excerpt (`:330-369`):

```python
def _apply_claimed(receipts, db, summary) -> bool:
    """Apply leased rows in order; stop at the first unacknowledged event."""
    for receipt in receipts:
        summary.attempted += 1
        if not _apply_one_claimed(receipt, db, summary):
            return False
    return True


def _drain_pending(db, endpoint_key, summary, *, max_attempts) -> None:
    """Retry the oldest event first and never pass an unacknowledged ID."""
    repo = db.webhook_pull_receipts
    for _ in range(max_attempts):
        batch = repo.claim_pending(endpoint_key, limit=1, lease_seconds=DEFAULT_LEASE_SECONDS, retry_only=True)
        if not batch:
            batch = repo.claim_pending(endpoint_key, limit=1, lease_seconds=DEFAULT_LEASE_SECONDS, retry_only=False)
        if not batch or not _apply_claimed(batch, db, summary):
            break
```

- `_replay_receipt` (`:194-207`) returns `(False, "malformed:<type>")` for an
  unparseable payload and increments `summary.malformed` **and** `summary.failed`.
- `_apply_one_claimed` (`:309-325`): docstring says "keep failures retryable".
- `news_collector/storage/webhook_pull_repository.py` — row states and claim
  eligibility: `_is_claim_eligible` (`:173-183`) makes `status == "failed"`
  claimable when `retry_only=True`; `_claimable_filter` (`:184-201`) includes
  failed rows in the retry pass.
- Exit code (`:540-545`):

```python
    if summary.failed or summary.malformed:
        return 1
    if summary.pending or summary.truncated or summary.business_attention:
        return 2
    return 0
```

- `news_collector/contracts/webhook.py:165-178` — `parse_webhook_payload` raises
  `ValueError` for any event type other than the two known ones, so an unknown
  future event or a schema drift is permanently unparseable by design.

Conventions: storage owns persistence and row state; the CLI owns reporting and
exit codes (LAW-B4/B6). Batch/queue paths must report per-item outcomes and
must not silently drop items (LAW-B6). Test convention: real SQLite via the
existing `DatabaseManager` fixtures; see `tests/unit/storage/` and any existing
webhook-pull tests (`grep -rn "webhook_pull" tests/` first).

## Commands you will need

| Purpose             | Command                                                             | Provenance | Expected on success         |
|---------------------|---------------------------------------------------------------------|------------|-----------------------------|
| Install/baseline    | `make bootstrap`                                                    | declared   | exit 0                      |
| Lint                | `make lint`                                                         | declared   | exit 0                      |
| Types + coverage    | `make type`                                                         | declared   | exit 0                      |
| Unit suite          | `make test`                                                         | declared   | all pass                    |
| Integration         | `make test-integration`                                             | declared   | all pass                    |
| Boundaries          | `make test-boundaries`                                              | declared   | exit 0                      |
| Focused tests       | `.venv/bin/pytest tests/ -q --no-cov -k "webhook"`                   | declared   | all pass                    |
| Ledger              | `make plans-ledger-check`                                           | declared   | `validate_plans_ledger: OK` |

Provenance: all rows `declared` (read from `Makefile`/CI by the advisor; the
advisor did not execute the suite). A `declared` command failing on an
unmodified checkout is a broken baseline — STOP, do not repair.

## Scope

**In scope**:

- `scripts/ops/pull_webhook_receipts.py`
- `news_collector/storage/webhook_pull_repository.py`
- `tests/` — new tests for the pull path (find the existing home with
  `grep -rln "webhook_pull_receipts\|pull_receipts" tests/`)
- `spec-webhook-inbox-pull.md` — keep the doc and the code in agreement (see
  Step 4)

**Out of scope** (do NOT touch):

- `news_collector/serving/api.py` and the hosted-inbox endpoints — the receipt
  ingestion path is fine; this plan fixes the *drain*.
- `news_collector/contracts/webhook.py` — parse strictness is deliberate
  (unknown event = malformed, reported). Do not loosen it.
- `todo-webhook-inbox-deploy.md` (untracked operator file) — do not edit it.

## Git workflow

- Branch: `advisor/132-webhook-inbox-poison-row`
- Conventional commits, e.g. `fix(webhook): dead-letter unprocessable receipts (plan 132)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then the remaining table commands on the unmodified
checkout. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Make a permanently-failing receipt leave the head of the queue

1. In `webhook_pull_repository.py`, add a terminal state for rows that have
   exhausted their attempts (e.g. `status = "dead"`), settable by a single
   repository method (`mark_dead(receipt_id, reason)`), storing the reason and
   keeping `payload` intact for audit. `attempts` already exists on the row —
   reuse it, do not add a counter column.
2. Ensure a `dead` row is **not** claimable by either claim pass
   (`_is_claim_eligible` and `_claimable_filter`) and that `_oldest_pending`
   ignores it. Check every place that filters on `status` in that module and in
   `scripts/ops/pull_webhook_receipts.py` (`grep -n "status"` in both).
3. In `pull_webhook_receipts.py`, after a replay returns
   `malformed:`/unacknowledged **and** the row has reached `MAX_DELIVERY_ATTEMPTS`
   (module constant, default 5 — no config knob), mark it `dead` and continue the
   drain instead of returning `False`. Rows below the cap keep today's
   behaviour (stop, so ordering is preserved for the retryable case).
4. Add `summary.dead_lettered: int` and include it in `_print_summary`.

**Verify**: `.venv/bin/pytest tests/ -q --no-cov -k "webhook"` → all pass;
`grep -n "dead" scripts/ops/pull_webhook_receipts.py news_collector/storage/webhook_pull_repository.py` → the new state is wired in both.

### Step 2: Align the exit code with the documented contract

5. Make the CLI return `1` **only** for unexpected failures (`PullError`,
   auth/connection) and `2` for pending/truncated/business-attention, exactly as
   `spec-webhook-inbox-pull.md:83-85` states. Malformed and dead-lettered rows
   are a report, not a failure.
6. If you believe exit 1 is the better signal for dead rows, STOP and report the
   trade-off instead of changing it unilaterally — the operator's timer
   semantics depend on this choice.

**Verify**: `.venv/bin/pytest tests/ -q --no-cov -k "webhook"` → all pass; the
new test asserting the exit code for a completed pass with one dead row → 0.

### Step 3: Keep the admin surface honest

7. Check whether any consumer whitelists receipt statuses
   (`grep -rn "\"processed\"\|'processed'" apps/admin/src news_collector/serving | head`)
   and, if one does, add the new state so dead receipts remain visible to the
   operator. If none does, say so in the ledger row.

**Verify**: `grep -rn "dead" apps/admin/src news_collector/serving | head` → your finding recorded.

### Step 4: Reconcile the spec text

8. `spec-webhook-inbox-pull.md` currently promises the exit-0 contract the code
   did not implement. Update the "Wiring" / outcome section to describe the new
   behaviour: dead-letter cap, retained payload, summary counter, exit codes.
   Keep the file's existing tone and structure; do not rewrite it.

**Verify**: `grep -n "dead\|exit" spec-webhook-inbox-pull.md` → the new text is present and agrees with the code.

## Test plan

New tests (real SQLite, no network; model after the existing webhook-pull tests):

- **The bug**: stage an unparseable receipt (unknown event type) *ahead of* a
  valid one; run the drain → assert the valid receipt is applied, the poison row
  is `dead` after the cap, its payload is unchanged, and `summary.dead_lettered == 1`.
- **Ordering preserved below the cap**: a failing-but-retryable row with
  `attempts < cap` still stops the drain this pass and is retried next pass.
- **Claim exclusion**: a `dead` row is never claimed by either pass and does not
  block `_oldest_pending` ordering for later rows.
- **Exit codes**: completed pass with dead rows → 0; `PullError` → 1; pending →
  2 (assert directly on `main()`'s return, no subprocess needed).

**Verify**: `.venv/bin/pytest tests/ -q --no-cov -k "webhook"` → all pass,
including N new tests; `make test && make test-integration` → green.

## Done criteria

All must hold:

- [ ] `make lint` exits 0; `make type` exits 0
- [ ] `make test` and `make test-integration` exit 0
- [ ] New regression test proves: poison row + valid row in one queue → valid
      row applied in that same run (fails on the original code)
- [ ] `grep -n "MAX_DELIVERY_ATTEMPTS" scripts/ops/pull_webhook_receipts.py` → present
- [ ] `spec-webhook-inbox-pull.md` agrees with the implementation (diff shown)
- [ ] `git diff --name-only main...HEAD` lists only the in-scope files
- [ ] `plans/README.md` row 132 updated; `make plans-ledger-check` → OK

## STOP conditions

- The excerpts above do not match the live code (drift) — especially if
  `_drain_pending`/`_claimable_filter` already contain a dead-letter path.
- Adding a terminal state requires a schema migration you did not expect
  (`status` is a plain string column today; if a CHECK constraint exists, report
  before altering it).
- The exit-code change would break an existing CI workflow that asserts a
  non-zero exit (grep the workflows first; report if found).
- You find evidence the operator's timer depends on exit 1 for malformed rows
  (report instead of changing semantics).

## Maintenance notes

- The dead-letter cap is a correctness knob, not a product knob: if it ever
  needs configuring, it belongs in the pull CLI's flags, not `config.toml`.
- Reviewer should scrutinise: that no code path can *silently* mark a row dead
  without counting it, and that `payload` is never nulled.
- **Deferred:** a reconciler-side sweep that retries dead rows after a contract
  upgrade lands (unblocked by: a future contract change; not needed now).
