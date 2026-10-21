# Spec: Current task

This file is a **thin, living record for the current ad-hoc task only**. It is
filled in when a task starts and replaced or cleared when that task ends — it is
not a plan tracker and not a session log.

Where things live:

- Plan status and the planned backlog live in `plans/README.md`.
- Each tracked plan's authoritative spec is its own plan file or folder under
  `plans/` — `spec.md` + `todo.md` (+ `tests/`) for multi-file plans, the plan
  file itself for single-file plans (see `docs/AGENTS.md` §0.1).

## Current task — 2026-10-20: reader-report reconciliation runbook

**Goal**: the operator can run plan 186's R2 reconciliation locally without
reading the plan (docs-only change; no code paths move).

**Scope**: `docs/RUNBOOK_LOCAL_DEV.md` only — a "Reader report reconciliation
(R2 → local backend)" subsection mirroring the webhook-pull section: env
placeholders (already in `.env.example` since 186), `--dry-run` first pass,
`--since/--limit`, idempotency-by-UUID, exit codes 0/1/2, migration
`d2e3f4a5b6c7`.

**Verification**: `make docs-check` (validated commands/paths/calling
conventions) after the edit; cross-rollup `make test-refinery` is unrelated
and kept out of scope.
