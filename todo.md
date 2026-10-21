# Todo: Current task

Running checklist for the **current ad-hoc task only** (spec: `spec.md` next to
this file). Plan-level checklists live with their plans under `plans/`; plan
status lives in `plans/README.md`.

## Current task

- [x] Add the "Reader report reconciliation (R2 → local backend)" section to
      `docs/RUNBOOK_LOCAL_DEV.md` (env vars token, `--dry-run` first, `--since`,
      `--limit`, idempotency-by-UUID, exits 0/1/2, migration `d2e3f4a5b6c7`)
- [x] Verify the webhook-pull section stayed intact after the insertion
      (§5.1 rule 5: verify diffs of script-free doc edits)
- [x] `make docs-check` green on the edited doc set
- [ ] Clear this pair when the task ends (next task start)

## When a task ends

Replace this file's "Current task" section with the next ad-hoc task, or reset
it to the placeholder below (plan status stays in `plans/README.md`):

- [ ] (none — add items when ad-hoc work starts)
