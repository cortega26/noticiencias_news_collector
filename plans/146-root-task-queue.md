# Plan 146: Close the stale root task queue and refresh the inventory baseline

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- spec.md todo.md 'spec-*.md' 'todo-*.md' docs/AGENTS.md docs/INDEX.md docs/RUNBOOK_LOCAL_DEV.md docs/adr/ audit/00_inventory.json archive/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (doc references must be re-pointed in the same change)
- **Depends on**: none; **coordinates with plan 081** (docs reconciliation owner —
  read `plans/081/todo.md` before moving anything it is touching)
- **Category**: docs / tech-debt
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

`docs/AGENTS.md §0.1` mandates that every task keeps `spec.md` + `todo.md` "in the
task root", and both `AGENTS.md` (root) and `CLAUDE.md` send every agent there
first. Those files are a **closed work queue**: `spec.md:3-6` says to "work
through the 18 remaining TODO/PARTIAL plans (021, 023, 031–041, 043–049)" — all
of which are DONE and archived per `plans/README.md:61-64` — and it is otherwise a
dated session log. Alongside it sit 33 `spec-*.md` and 33 `todo-*.md` root files
(216 KB) of which 18 `todo-*.md` are fully checked with zero open items, plus a
`spec-fly-webhook-hosting.md` that prescribes a hosting path retired on
2026-09-26 (`spec-oci-hosting-migration.md:1`). The cost is not hypothetical: a
prior audit pass was misled by a stale `spec-*`/`todo-*` pair and burned a plan
on a dead premise (`plans/README.md`, plan 126 entry). There is also a live gate
debt: `audit/00_inventory.json` still lists `spec-alt-text-brief-flow.md` and
`spec-curation-desk-revamp.md`, both moved to `archive/superseded-specs/`, so
`make inventory-check` reports drift on HEAD until refreshed.

## Current state

- `spec.md:1-8` (goal block, quoted above); 37 289 bytes total.
- `todo.md` — 39 609 bytes; sections at `:31`, `:42`, `:52` still label plans 021,
  023 and 046 "PARTIAL" while the ledger records them DONE/REJECTED, and its tail
  (2026-10-09/10-10) holds live in-flight checklists.
- Root-level spec/todo inventory: `ls | grep -cE '^spec'` → 33; `^todo` → 33.
- Retirement precedent: `archive/superseded-specs/` (created by commit `1caf900`
  for two superseded specs) — the ledger entry is at `plans/README.md:450`.
- Active docs that cite root spec/todo files (re-point these in the same change):
  `docs/RUNBOOK_LOCAL_DEV.md:146,158`, `docs/adr/0010-llm-routing.md:13`,
  `docs/adr/0011-local-publish-hosted-webhook-split.md:10,58,95`,
  `docs/dev/TEST_SUITE_AUDIT.md:36`.
- `Makefile:442-449` — `inventory-refresh` regenerates `audit/00_inventory.json`;
  `inventory-check` compares a generated file against it.
- **Do not touch** `todo-webhook-inbox-deploy.md` — it is the operator's untracked
  in-flight work.

## Commands you will need

| Purpose            | Command                                                    | Provenance | Expected on success            |
|--------------------|------------------------------------------------------------|------------|--------------------------------|
| Install/baseline   | `make bootstrap`                                           | declared   | exit 0                         |
| Stale-ref proof    | `for f in spec-alt-text-brief-flow.md spec-curation-desk-revamp.md; do [ -e "$f" ] \|\| echo "MISSING $f"; done` | executed (advisor saw both missing) | both reported missing |
| Docs gates         | `make docs-check && make docs-review`                       | declared   | exit 0                         |
| Inventory          | `make inventory-refresh && make inventory-check`            | declared   | exit 0                         |
| Ledger             | `make plans-ledger-check`                                   | declared   | `validate_plans_ledger: OK`    |

Provenance: the stale-ref row was run by the advisor; the rest are `declared`.

## Scope

**In scope**:

- `spec.md`, `todo.md` (rewrite as a thin current-task file; the old text moves verbatim)
- Root `spec-*.md`, `todo-*.md` (move completed pairs; keep live ones)
- New: `archive/completed-tasks/README.md` (the index of what moved and why)
- `docs/AGENTS.md` §0.1 (and §5.1 item 3 if it names the pattern), `docs/INDEX.md`
  (one row), and the five active docs listed above (reference updates only)
- `audit/00_inventory.json` via `make inventory-refresh`

**Out of scope** (do NOT touch):

- `plans/**` (the ledger and plan archive are owned by the plans process; do not
  move plans).
- `todo-webhook-inbox-deploy.md` (untracked operator work).
- `docs/archive/**`, `docs/audits/**` (historical by definition).
- Any code file.

## Git workflow

- Branch: `advisor/146-root-task-queue`
- Conventional commits, e.g. `docs(plans): retire the closed root task queue (plan 146)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make docs-check`, `make plans-ledger-check` and record the
inventory-check result (expected: drift due to the two stale refs).

**Verify**: the recorded results; docs/ledger green, inventory drift reproduced.

### Step 1: Classify every root spec/todo file

1. Build the list: `ls spec*.md todo*.md` (exclude `spec.md`/`todo.md` for now).
2. For each pair, classify:
   - **closed**: the `todo-*.md` has zero unchecked boxes (`grep -c "\[ \]"` → 0)
     and the work is verifiably landed (the file's own plan/commit references, or
     `plans/archive/`) → move to `archive/completed-tasks/`;
   - **live**: has open items and is referenced from an active doc or the ledger
     → keep at the root and list it in the index;
   - **unknown**: leave in place, list under "needs an owner" in the index and in
     the ledger row — do not guess.
3. Record the three counts before you move anything.

**Verify**: the classification table is written in `archive/completed-tasks/README.md`.

### Step 2: Move, index, and re-point

4. `git mv` the closed files into `archive/completed-tasks/` (keep their names).
5. Write `archive/completed-tasks/README.md`: one table with file, what it
   delivered, and the evidence (commit or archived plan number).
6. Re-point the five active-doc references listed in "Current state" (use
   `grep -rn "spec-<name>\|todo-<name>" docs/ README.md CONTRIBUTING.md AGENTS.md CLAUDE.md`
   for each moved file, and fix every hit in the same commit).
7. `docs/INDEX.md`: add one row pointing at `archive/completed-tasks/README.md`
   and at whatever remains live at the root. **Coordinate with plan 081**: if
   `plans/081/todo.md` shows it is currently editing `docs/INDEX.md`, note the
   conflict in the ledger row and make the minimal addition only.

**Verify**: `grep -rn "spec-alt-text-brief-flow\|spec-curation-desk-revamp" docs/ README.md AGENTS.md CLAUDE.md Makefile .github/`
→ no hits (or only archive/index references).

### Step 3: Replace the root queue with a thin, true file

8. Rewrite `spec.md` to ≤ 60 lines: state that plan status lives in
   `plans/README.md`, that this file describes **the current task only**, and
   leave an empty "Current task" section (the operator fills it). Move the old
   file verbatim to `archive/completed-tasks/spec-root-2026-session-log.md`.
9. Rewrite `todo.md` the same way (≤ 60 lines), moving the old content verbatim
   next to the archived spec.
10. Update `docs/AGENTS.md` §0.1 so "in the task root" points at the plan's own
    file/folder (`plans/NNN/spec.md`+`todo.md` or the plan file itself) and at the
    thin root files for ad-hoc work. Keep the section's intent — no rule change.

**Verify**: `wc -l spec.md todo.md` → both ≤ 60; `make docs-check` → exit 0;
`grep -n "task root" docs/AGENTS.md` → the new wording.

### Step 4: Heal the inventory gate

11. `make inventory-refresh`, inspect the diff (`git diff --stat audit/00_inventory.json`),
    then `make inventory-check` → exit 0.

**Verify**: the two refs are gone from `audit/00_inventory.json`
(`grep -c "spec-alt-text-brief-flow" audit/00_inventory.json` → 0).

## Test plan

- Docs/inventory only; no code tests. The gates are the tests:
  `make docs-check`, `make docs-review`, `make inventory-check`,
  `make plans-ledger-check`.

**Verify**: all four exit 0.

## Done criteria

All must hold:

- [ ] `make docs-check`, `make docs-review`, `make inventory-check`, `make plans-ledger-check` exit 0
- [ ] `make lint` still exits 0 (Makefile-tab check included)
- [ ] Every root `todo-*.md` with zero open items is under `archive/completed-tasks/`
      or listed with a reason why not
- [ ] `archive/completed-tasks/README.md` lists every moved file with evidence
- [ ] No active doc references a moved root file
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (+ inventory baseline)
- [ ] `plans/README.md` row 146 updated; `make plans-ledger-check` → OK

## STOP conditions

- More than ~5 files are classified "unknown" → STOP after Step 1 and report the
  list; do not move work whose ownership you cannot establish.
- A moved file turns out to be referenced from `plans/` or from code → re-point or
  leave it in place; report which.
- Plan 081 is actively editing the same files in a way you cannot reconcile →
  land Steps 1-2 and 4 only, and record the conflict.

## Maintenance notes

- After this lands, the rule is: a root `spec-*.md`/`todo-*.md` pair is either
  live (and indexed) or archived. New pairs should be created inside the plan's
  own folder instead — that is what §0.1 now says.
- Reviewer should scrutinise: that no historical content was lost (moves are
  `git mv`, rewrites archive the original verbatim) and that the ledger's
  references to moved files still resolve.
- **Deferred:** deleting the ~740 KB of generated debris at the root
  (`latest-log.txt`, `openai_debug.html`, `output/`, `security_status.txt`,
  `temp_*_data/`, the tracked `gitleaks` blob is plan 150's item). Unblocked by
  an operator decision; not done here to keep this plan's blast radius in docs.
