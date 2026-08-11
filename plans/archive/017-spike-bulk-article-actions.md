# Plan 017: Spike — bulk despublicar/reset actions in the published-content tab

> **Executor instructions**: A **design/spike plan**. Deliverable = an investigation
> note + a thin multi-select slice with a confirmation + progress + partial-failure
> handling — NOT an unbounded batch feature. Honor STOP conditions. Update
> `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- apps/refinery/admin_panel.py`

## Status

- **Priority**: P3
- **Effort**: M–L (spike-scoped)
- **Risk**: MED (state-changing + slow GitHub operations per article)
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

The published-content tab offers only **per-row** despublicar/reset. When an editor needs
to revert a batch (e.g. an auditor flags a rigor issue across a source's output), they
click and wait through one slow GitHub operation at a time. The backend already supports
per-article operations; the gap is a safe batch surface. "Safe" is the whole spike: bulk
deletes are state-changing and slow, so they need confirmation, progress, and
partial-failure handling — not a naive loop.

## Grounding evidence

- `apps/refinery/admin_panel.py:2570-2725` — the published-content tab ("Gestión de
  Contenido Publicado") renders a `for article in articles:` loop with per-row
  **"🗑️ Despublicar"** (`:2620`) and **"♻️ Reset"** (`:2648`) buttons; the reset path
  ends with `st.success("Reset OK")` (`:2720`). No multi-select / "select all" / bulk
  action exists (`grep -n "multiselect\|Select All\|bulk" apps/refinery/admin_panel.py` → none).
- The per-article operations these buttons call (delete/reset, which touch the DB and the
  GitHub/frontend repo) are the unit the bulk action would iterate.

## Spike deliverables

1. **Investigation note** `docs/spikes/bulk-article-actions.md` answering the open questions.
2. **A thin bounded slice**: multi-select on the published list + ONE bulk action
   (despublicar OR reset) behind a confirmation that lists the count, executed with a
   visible progress indicator and **per-item error capture** (one failure doesn't abort
   the rest; the result reports which succeeded/failed). Cap the batch size (e.g. ≤ N).
3. **Recommendation**: whether to extend to both actions / Tab 3 candidates, and whether
   the per-article GitHub op needs queueing/rate-limiting for larger batches.

## Open questions the note must answer

- **What exactly does one despublicar/reset do** (DB only? a GitHub commit/PR per
  article?) and roughly how long? This sets the batch cap and whether a progress bar
  suffices or a queue is needed. Read the handlers the per-row buttons call.
- **Partial failure semantics**: if item 7 of 20 fails, what state is the system in?
  Define and implement "continue + report", never "abort halfway silently".
- **Auth**: reuse the same gate the destructive Reset-Total flow uses (`admin_panel.py:1690`).
- **Streamlit rerun safety**: a long bulk loop blocks the rerun; confirm the existing
  `op_in_progress` session flag pattern (used elsewhere in this file) is applied so the UI
  can't double-submit.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| AST parse | `.venv/bin/python -c "import ast; ast.parse(open('apps/refinery/admin_panel.py').read()); print('ok')"` | `ok` |
| Lint | `make lint` | exit 0 |
| Refinery tests | `.venv/bin/pytest tests/decompose_refinery -q` | pass |

## Scope

**In scope:** `docs/spikes/bulk-article-actions.md`; a multi-select + one bounded bulk action in the published-content tab; reuse of the existing per-article handler + auth gate + `op_in_progress` flag.

**Out of scope:** new backend batch endpoints (reuse the per-article path); bulk actions on other tabs (Tab 3 candidates) — recommend, don't build; changing what a single despublicar/reset does; the frontend repo.

## Git workflow

- Branch: `advisor/017-bulk-actions-spike`; commits: note, then slice. Do NOT push.

## Steps

### Step 1: Investigate + write the note
Trace the per-row despublicar/reset handlers; document what one operation does and its cost; define partial-failure semantics and the batch cap. Answer the open questions with `file:line`.

### Step 2: Thin bounded slice
Add a checkbox/multiselect to the published list and ONE bulk action behind a confirmation showing the selected count. Execute via the existing per-article handler in a loop that: sets `op_in_progress`, shows progress (`st.progress`), captures each item's success/failure, and renders a summary (N succeeded, M failed with reasons). Enforce the batch cap.

**Verify:** AST parse + `make lint` + `make test` green. If full Streamlit execution isn't feasible, factor the loop body into a pure helper (takes a list of ids + a per-item callable, returns a success/failure report) and **unit-test that helper** (a callable that fails on the 3rd item → report shows 1 failure, others succeeded, loop didn't abort). Model after `tests/decompose_refinery/`.

## Done criteria

- [ ] `docs/spikes/bulk-article-actions.md` answers all open questions with evidence + recommendation
- [ ] Multi-select + one bounded, auth-gated bulk action with confirmation, progress, and per-item failure capture (continue-on-error)
- [ ] A testable helper encapsulates the batch loop and has a partial-failure unit test
- [ ] `op_in_progress` (or equivalent) prevents double-submit; batch size capped
- [ ] AST parse + `make lint` + `make test` green; only in-scope files changed
- [ ] `plans/README.md` row updated

## STOP conditions

- One despublicar/reset turns out to open a GitHub PR / heavy op such that even a capped batch is too slow for a synchronous Streamlit loop → deliver the note recommending a queue/async approach and a smaller cap; do not ship a UI that hangs.
- Reusing the per-article handler for a loop requires refactoring it → report rather than reshaping it inside this spike.

## Maintenance notes

- Bulk destructive actions are the highest-risk UI addition here — a reviewer should
  scrutinize the confirmation, the cap, continue-on-error, and that the auth gate matches
  the per-row actions.
- If extended later to Tab 3 candidates or to "revert an entire source's output", revisit
  the cost/queueing question from the note.
