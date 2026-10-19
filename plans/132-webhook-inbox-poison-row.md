# Plan 132: One bad webhook receipt must not block the inbox drain forever

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 836ecc1..HEAD -- scripts/ops/pull_webhook_receipts.py news_collector/storage/webhook_pull_repository.py tests/ spec-webhook-inbox-pull.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `836ecc1`, 2026-10-18 (refreshed after the first
  executor run STOPped correctly; see the refresh note below)

### Refresh note (2026-10-18)

The first execution attempt STOPped as designed: `webhook_pull_receipts.status`
carries a **CHECK constraint** (`news_collector/storage/models.py:1024-1028`,
baked into history by `alembic/versions/c6d1a4e8f203_add_webhook_pull_state.py:21,59`),
so writing `status='dead'` raises `sqlite3.IntegrityError` — verified empirically
against a fresh DB. Adding a status value would require editing `models.py` and
shipping an Alembic table-rebuild migration (SQLite cannot alter a CHECK in
place), neither of which belongs in this plan.

**Design change (this refresh): the "dead letter" becomes a DERIVED state, not a
stored one.** A receipt is *exhausted* when `status == 'failed'` **and**
`attempts >= MAX_DELIVERY_ATTEMPTS`. Exhausted rows stop being claimable, the
drain steps over them and reports them in the summary. No schema change, no new
status value, no migration — and the operator keeps the existing admin view plus
the `attempts` counter as the evidence of what happened.

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
  failed rows in the retry pass. The row carries an `attempts` counter (incremented
  on each claim/settle) — that counter is this plan's exhaustion signal.
- Exit code (`:540-545`):

```python
    if summary.failed or summary.malformed:
        return 1
    if summary.pending or summary.truncated or summary.business_attention:
        return 2
    return 0
```

- `news_collector/storage/models.py:970-973` — the closed set
  `WEBHOOK_PULL_STATUS_VALUES = ("received", "processing", "processed", "failed")`,
  enforced by `CheckConstraint("status IN ('received', 'processing', 'processed',
  'failed')", name="ck_webhook_pull_receipts_status")` (`:1024-1028`). **Do not
  change this** — see the refresh note.
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

- `news_collector/storage/models.py` and `alembic/versions/**` — **no schema
  change, no new status value, no migration.** The CHECK constraint is a hard
  boundary of this plan.
- `news_collector/serving/api.py` and the hosted-inbox endpoints — the receipt
  ingestion path is fine; this plan fixes the *drain*.
- `news_collector/contracts/webhook.py` — parse strictness is deliberate
  (unknown event = malformed, reported). Do not loosen it.
- `todo-webhook-inbox-deploy.md` (untracked operator file) — do not edit it.

## Git workflow

- Branch: `advisor/132-webhook-inbox-poison-row`
- Conventional commits, e.g. `fix(webhook): stop poisoned receipts from blocking the drain (plan 132)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then the remaining table commands on the unmodified
checkout. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Make an exhausted receipt leave the head of the queue

1. In `webhook_pull_repository.py`, add a module-level constant
   `MAX_DELIVERY_ATTEMPTS = 5` (owner: the module that owns row state; the CLI
   imports it — no config knob) and a tiny predicate
   `is_exhausted(row) -> bool` = `row.status == "failed" and row.attempts >= MAX_DELIVERY_ATTEMPTS`.
   Reuse the existing `attempts` counter; do not add a column.
2. Make an exhausted row unclaimable in **both** passes: extend
   `_is_claim_eligible` and `_claimable_filter` so a `failed` row at or over the
   cap is skipped; ensure `_oldest_pending` ignores it too. `grep -n "status"` in
   both files and check every status-filtering site.
3. In `pull_webhook_receipts.py`, after a replay/settle returns unacknowledged:
   - if the row is now exhausted → `summary.exhausted += 1`, log it with the
     receipt id, `attempts` and the last error reason, then **continue the drain**
     (do not return `False`);
   - otherwise keep today's behaviour (stop, so ordering is preserved for the
     retryable case).
4. Add `exhausted: int = 0` to the summary dataclass and include it in
   `_print_summary` (and in any JSON/summary payload the CLI emits).
5. Keep the row exactly as it is otherwise: `status` stays `failed`, `payload`
   untouched, `attempts` visible. The dead-letter state is derived, never stored.

**Verify**: `.venv/bin/pytest tests/ -q --no-cov -k "webhook"` → all pass;
`grep -n "MAX_DELIVERY_ATTEMPTS\|is_exhausted" news_collector/storage/webhook_pull_repository.py scripts/ops/pull_webhook_receipts.py` → wired in both;
`grep -c "dead" news_collector/storage/models.py` → 0 (unchanged).

### Step 2: Align the exit code with the documented contract

6. Make the CLI return `1` **only** for unexpected failures (`PullError`,
   auth/connection) and `2` for pending/truncated/business-attention, exactly as
   `spec-webhook-inbox-pull.md:83-85` states. Malformed and exhausted rows are a
   report, not a failure.
7. If you believe exit 1 is the better signal for exhausted rows, STOP and report
   the trade-off instead of changing it unilaterally — the operator's timer
   semantics depend on this choice.

**Verify**: `.venv/bin/pytest tests/ -q --no-cov -k "webhook"` → all pass; the
new test asserting the exit code for a completed pass with one exhausted row → 0.

### Step 3: Keep the operator surface honest

8. Check whether the receipts surface exposes the `attempts` counter to the
   operator (`grep -rn "attempts" news_collector/serving apps/admin/src | head`;
   and read the admin receipts endpoint's response model). If it does, exhausted
   rows are already distinguishable and no change is needed — say so.
9. If it does **not**, do not edit `serving/` — record it in the ledger row as a
   follow-up ("exhausted receipts are counted by the CLI but not surfaced in the
   admin payload") and move on.

**Verify**: `grep -rn "attempts" news_collector/serving apps/admin/src | head` → your finding recorded.

### Step 4: Reconcile the spec text

10. `spec-webhook-inbox-pull.md` currently promises the exit-0 contract the code
    did not implement. Update the "Wiring" / outcome section to describe the new
    behaviour: exhaustion after `MAX_DELIVERY_ATTEMPTS`, retained payload, derived
    state (no new status), summary counter, exit codes. Keep the file's existing
    tone and structure; do not rewrite it.

**Verify**: `grep -n "exhaust\|exit" spec-webhook-inbox-pull.md` → the new text is present and agrees with the code.

## Test plan

New tests (real SQLite, no network; model after the existing webhook-pull tests):

- **The bug**: stage an unparseable receipt (unknown event type) *ahead of* a
  valid one, with the poison row already at `attempts == MAX_DELIVERY_ATTEMPTS - 1`
  so one more claim exhausts it; run the drain → assert the valid receipt **is
  applied in that same run**, the poison row stays `status='failed'` with
  `attempts == MAX_DELIVERY_ATTEMPTS`, its `payload` is unchanged, and
  `summary.exhausted == 1`.
- **Ordering preserved below the cap**: a failing-but-retryable row with
  `attempts < cap` still stops the drain this pass and is retried next pass.
- **Claim exclusion**: an exhausted row is never claimed by either pass and does
  not block `_oldest_pending` ordering for later rows (prove with a second valid
  receipt behind it).
- **No schema change**: assert the ORM status set is unchanged
  (`WEBHOOK_PULL_STATUS_VALUES` is the original four values) — a cheap guard
  against a future "just add a status" regression.
- **Exit codes**: completed pass with exhausted rows → 0; `PullError` → 1;
  pending → 2 (assert directly on `main()`'s return, no subprocess needed).

**Verify**: `.venv/bin/pytest tests/ -q --no-cov -k "webhook"` → all pass,
including N new tests; `make test && make test-integration` → green.

## Done criteria

All must hold:

- [ ] `make lint` exits 0; `make type` exits 0
- [ ] `make test` and `make test-integration` exit 0
- [ ] New regression test proves: poison row + valid row in one queue → valid
      row applied in that same run (fails on the original code)
- [ ] `grep -n "MAX_DELIVERY_ATTEMPTS" news_collector/storage/webhook_pull_repository.py scripts/ops/pull_webhook_receipts.py` → present in both
- [ ] **No schema change**: `git diff --name-only main...HEAD` contains no
      `news_collector/storage/models.py` and no `alembic/**`, and
      `WEBHOOK_PULL_STATUS_VALUES` is unchanged
- [ ] `spec-webhook-inbox-pull.md` agrees with the implementation (diff shown)
- [ ] `git diff --name-only main...HEAD` lists only the in-scope files
- [ ] `plans/README.md` row 132 updated; `make plans-ledger-check` → OK

## STOP conditions

- The excerpts above do not match the live code (drift) — especially if
  `_drain_pending`/`_claimable_filter` already contain an exhaustion path.
- Anything pushes you toward a schema change (a new status value, a new column,
  a migration) → **STOP and report**; that decision is not yours and the plan
  forbids it.
- The `attempts` counter turns out not to be incremented on the settle path you
  need (verify by reading `_settle_claimed` and the claim path) → report; do not
  add a counter column.
- The exit-code change would break an existing CI workflow that asserts a
  non-zero exit (grep the workflows first; report if found).
- You find evidence the operator's timer depends on exit 1 for malformed rows
  (report instead of changing semantics).

## Maintenance notes

- Exhaustion is derived (`failed` + `attempts >= cap`), so the invariant to
  protect is the counter: if a future change stops incrementing `attempts`, the
  drain silently goes back to blocking forever. The regression test above is the
  guard.
- If the operator later wants a stored `dead` state (for reporting), that is a
  separate plan with a migration — record the intent, do not smuggle it in.
- Reviewer should scrutinise: that the drain still *stops* on retryable failures
  (ordering guarantee) and only steps over exhausted rows; and that `payload` is
  never nulled.
- **Deferred:** a reconciler-side sweep that retries exhausted rows after a
  contract upgrade lands (unblocked by: a future contract change; not needed now).
