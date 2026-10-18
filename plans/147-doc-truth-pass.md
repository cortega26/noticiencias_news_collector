# Plan 147: Correct four documents that are actively wrong

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- docs/contracts_inventory.md docs/ci.md docs/adr/0006-durable-workflow-lifecycle-state.md docs/api/ docs/INDEX.md .github/workflows/ news_collector/contracts/ news_collector/storage/models.py plans/060/ plans/081/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW-MED (ADR-0006 is history — prefer an in-place "as shipped" update
  over a rewrite)
- **Depends on**: none; **coordinates with plan 081** (docs reconciliation owner) —
  read `plans/081/todo.md` first and note any overlap in the ledger row
- **Category**: docs
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Four documents are worse than missing because they assert completeness or facts
the code contradicts:

1. **`docs/contracts_inventory.md`** opens with "All boundaries below are typed
   and enforced. This inventory reflects the current implementation state"
   (`:3-4`) and `docs/INDEX.md:37` advertises it as "Contract inventory (all typed
   boundaries)" — but the 53-line file never mentions `contracts/admin.py`
   (42 classes), `contracts/webhook.py`, `contracts/publication_validation.py`,
   `contracts/enrichment.py`, `contracts/source_health.py`, `contracts/image_brief.py`,
   `contracts/frontend_publication.py`, or `contracts/social_publication.py`. Somebody
   applying LAW-B1/B2 ("is there already a contract for this?") reads "no" and
   re-derives a shape the repo owns. It is also outside both docs gates
   (`scripts/check_doc_drift.py`'s 14 files, `scripts/check_doc_review.py`'s
   `ACTIVE_DOCS`), so it can make false claims indefinitely.
2. **The collector incident watcher is documented nowhere.**
   `.github/workflows/collector-incident-watcher.yml` (plan 115 Phase A,
   `gh issue create`/`reopen`, fail-closed branches) is the daily collector's only
   automated failure signal — the per-run alert step was deliberately removed
   (`daily_collector.yml:15-16`). It appears in **zero** of `docs/ci.md`,
   `docs/INDEX.md`, `README.md`, `docs/runbook.md`, `docs/operations.md`, while
   `docs/INDEX.md:24,45` bills `docs/runbook.md` as "Ops runbook (alerts and
   incidents)". On-call has no documented path from a failed collection to a
   response.
3. **ADR-0006's schema does not exist.** The ADR (and `plans/060/spec.md:158-163`,
   which repeats it for phases still to be built) specifies `kind`, `active_key`,
   `requested_payload`, `summary` and a `version` optimistic counter. The shipped
   `workflow_runs` table has `run_type` (`storage/models.py:572`), `run_metadata`
   (`:592`), `idempotency_key` (`:579`), `heartbeat_at`, and single-flight by a
   partial unique index on `run_type` (`:615-626`) — `grep` for
   `active_key|requested_payload` across `news_collector/`, `alembic/`, `scripts/`
   returns nothing. `docs/SOURCE_OF_TRUTH.md` already rules that code wins on
   field names, so this is correction debt, not a design question.
4. **The committed generated API reference is three weeks stale and ungated.**
   `docs/api/` (1.8 MB HTML + 397 KB search index) was last regenerated in
   `28271c6` (2026-09-25); the hosted webhook-inbox surface landed afterwards
   (`04016ca`, `2852f5d`) and appears nowhere in it. Nothing links or checks it:
   `make docs-api` is the only producer, and no workflow references it.

## Current state

- `docs/contracts_inventory.md` — 53 lines; grep for any of the missing module
  names returns nothing.
- `.github/workflows/collector-incident-watcher.yml` — the workflow (read its
  header comment for the dedupe/reopen/silence rules to summarise).
- `docs/ci.md:25-38` — the "Current jobs" list (12 entries) omits the live
  `admin-contracts` job (`ci.yml:127`, described later in the same file at `:87`),
  and the file never names `collector-incident-watcher.yml`.
- `docs/adr/0006-durable-workflow-lifecycle-state.md:45-52` — the table with
  `kind`/`active_key`/`requested_payload`/`summary`/`version`.
- `plans/060/spec.md:158-163` — the same table repeated.
- `docs/api/` — regenerated 2026-09-25 (`git log -1 --format="%h %ci" -- docs/api/`).

## Commands you will need

| Purpose          | Command                                                        | Provenance | Expected on success            |
|------------------|----------------------------------------------------------------|------------|--------------------------------|
| Install/baseline | `make bootstrap`                                               | declared   | exit 0                         |
| Docs gates       | `make docs-check && make docs-review`                          | declared   | exit 0                         |
| Lint             | `make lint`                                                    | declared   | exit 0                         |
| Ledger           | `make plans-ledger-check`                                      | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared` (the advisor ran `python3 scripts/check_doc_drift.py`
directly during the audit: "OK - 14 docs checked").

## Scope

**In scope**:

- `docs/contracts_inventory.md`
- `docs/ci.md` (job list + the incident-watcher entry)
- `docs/runbook.md` (a short "Collector failure incidents" section)
- `docs/adr/0006-durable-workflow-lifecycle-state.md` (in-place "as shipped" update)
- `plans/060/spec.md` (the repeated table — correction only, no scope change)
- `docs/api/` (delete or gate — see Step 4)
- `docs/INDEX.md` (one row for the API-reference decision)
- `scripts/check_doc_drift.py` / `scripts/check_doc_review.py` (add
  `docs/contracts_inventory.md` to the checked set — see Step 1)

**Out of scope** (do NOT touch):

- Any code, workflow, or schema — this plan changes documents only.
- `plans/081/**` (another agent's file — read it, do not edit it).
- `docs/archive/**`, `docs/audits/**`.
- The ADR's historical decision text beyond the "as shipped" update.

## Git workflow

- Branch: `advisor/147-doc-truth-pass`
- One commit per document; conventional commits, e.g.
  `docs(contracts): complete the typed-boundary inventory (plan 147)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make docs-check`, `make docs-review`, `make lint`. Record
the results. Red baseline → STOP.

**Verify**: all exit 0.

### Step 1: Complete and gate the contract inventory

1. Regenerate the inventory **from the code**: list every module under
   `news_collector/contracts/` (`ls news_collector/contracts/*.py`) with its
   primary models (class names) and the owning test file(s)
   (`grep -rln "<ModuleName>" tests/contracts tests/ | head`). Keep the existing
   sections' style; replace the "All boundaries below are typed and enforced"
   opener with a sentence that says the list is generated from
   `news_collector/contracts/` and names the generation date/SHA.
2. Add `docs/contracts_inventory.md` to `scripts/check_doc_drift.py`'s file list
   and to `scripts/check_doc_review.py`'s `ACTIVE_DOCS` so a contract change
   keeps it current. If either script's invariants cannot express "every module
   in contracts/ appears", add the smallest invariant that can (e.g. a path
   existence sweep) — do not rewrite the gate.

**Verify**: `make docs-check` exits 0; `make docs-review` exits 0;
`grep -c "admin\|webhook" docs/contracts_inventory.md` > 0.

### Step 2: Document the incident watcher

3. Add a "Collector failure incidents" section to `docs/runbook.md` (or extend the
   existing collection section — read the file first): what raises an incident
   (a completed Daily Collection run that failed), what the operator sees (one
   stable GitHub issue, one update per 24 h per fingerprint), how to acknowledge,
   why a second failure stays silent, the 30 h cancellation rule, and what the
   watcher's own fail-closed branches mean. Source these rules from the
   workflow's header comment — do not invent them.
4. `docs/ci.md`: add `collector-incident-watcher.yml` to the workflow coverage and
   fix the "Current jobs" list to include `admin-contracts` (`ci.yml:127`).
5. `docs/INDEX.md`: one row pointing at the runbook section.

**Verify**: `grep -rn "collector-incident-watcher" docs/ | wc -l` ≥ 2;
`grep -n "admin-contracts" docs/ci.md | head` shows it in the job list too.

### Step 3: Bring ADR-0006 and plan 060 in line with the shipped schema

6. Add an "Update: as shipped (2026-10, commit `<short SHA>`)" section to
   ADR-0006 that states the actual column names (`run_type`, `run_metadata`,
   `idempotency_key`, `heartbeat_at`, `status`), the actual single-flight
   mechanism (partial unique index on `run_type` for `collection`), the actual
   `run_type` values (`collection`, `publication`, `publication_reconciliation`,
   `source_catalog_reconciliation`), and that `kind`/`active_key`/
   `requested_payload`/`version` are the ADR's original proposal and are **not**
   in the schema. Follow the precedent of an in-place update (ADR-0004 has one),
   rather than marking the ADR superseded.
7. Fix the repeated table in `plans/060/spec.md:158-163` with a one-line pointer
   to the ADR's as-shipped section (do not redesign 060's remaining phases here).

**Verify**: `grep -n "as shipped" docs/adr/0006-*.md` → present;
`grep -n "active_key" plans/060/spec.md` → only inside the correction note.

### Step 4: Decide the generated API reference's fate

8. Pick one and state it in `docs/ci.md` + `docs/INDEX.md`:
   - **Option A (preferred, smaller):** stop committing it — `git rm -r docs/api`,
     keep `make docs-api` as an on-demand generator, and add one line to
     `docs/ci.md` saying the reference is generated, not committed.
   - **Option B:** keep it and add a freshness check to a workflow (regenerate and
     `git diff --exit-code`), analogous to `admin-contracts-check`.
   Rationale must be written down; do not leave it undecided.

**Verify**: for Option A, `git ls-files docs/api | wc -l` → 0 and `make docs-api`
still works; for Option B, the new check exists in a workflow and passes.

### Step 5: Verify the whole pass

9. Run every gate: `make docs-check && make docs-review && make lint && make plans-ledger-check`.
   If the inventory/ADR edits added or removed tracked files, run
   `make inventory-refresh && make inventory-check`.

**Verify**: all exit 0.

## Test plan

- Documents only. The gates are the tests. Where the change adds a doc-drift
  invariant (Step 1), add/extend the gate's own test if it has one
  (`grep -n "check_doc_drift" tests/ scripts/` to find it) — otherwise record that
  the gate is validated by `make docs-check` exiting 0 on a correct tree and
  failing on a removed contract module (prove by temporarily deleting a line).

**Verify**: the temporary-deletion proof is recorded.

## Done criteria

All must hold:

- [ ] `make docs-check`, `make docs-review`, `make lint` exit 0
- [ ] Every module under `news_collector/contracts/` appears in `docs/contracts_inventory.md`
- [ ] The inventory is inside at least one docs gate (proof: the temporary-removal test fails)
- [ ] `collector-incident-watcher.yml` is described in `docs/ci.md` + the runbook
- [ ] ADR-0006 carries the as-shipped section; `plans/060/spec.md` no longer asserts the wrong columns
- [ ] `docs/api/` decision recorded and implemented
- [ ] `make inventory-refresh` run if files changed; `make inventory-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (+ inventory baseline)
- [ ] `plans/README.md` row 147 updated; `make plans-ledger-check` → OK

## STOP conditions

- Plan 081 is mid-edit on the same file and the edits conflict → land the
  non-overlapping documents and record the overlap.
- The incident watcher's behaviour cannot be summarised from its own header +
  steps without guessing → document only what you verified and leave a `TODO(operator)`
  line rather than inventing a runbook.
- Adding the inventory to a docs gate turns the gate red for pre-existing reasons
  unrelated to this change → fix only the inventory, and if the gate still fails,
  STOP and report what else it catches.

## Maintenance notes

- The contract inventory is now a gate: any new module under
  `news_collector/contracts/` must be added in the same PR (that is the point).
- Reviewer should scrutinise: the ADR update is additive (history preserved), and
  the runbook section matches the workflow's actual branches.
- **Deferred:** generating `docs/contracts_inventory.md` from the AST (Option B
  for Step 4-style freshness). Unblocked by nothing; the manual list + gate is
  enough for now.
