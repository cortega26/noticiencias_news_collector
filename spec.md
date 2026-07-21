# Spec: Implement the remaining plans in plans/README.md

## Goals

- Work through the 18 remaining TODO/PARTIAL plans (021, 023, 031–041, 043–049) in
  dependency order, not plan-number order.
- Each plan's own file (`plans/NNN-*.md`) is the authoritative spec for that plan's
  scope, design decisions, and STOP conditions — this document only tracks
  cross-plan sequencing and the invariants that apply to all of them. Do not
  duplicate a plan's content here.
- Finish one plan fully (implementation + its own verification + regression
  gates) before starting the next, unless a plan is explicitly a spike/ADR
  (047–049) that ends in a decision document rather than shipped code.
- Never mark a plan DONE in `plans/README.md` while any of its own Done
  Criteria are unmet.

## Cross-plan invariants (apply to every plan below)

- Repo boundary: this working directory is the Python backend
  (`noticiencias_news_collector`). Plans 031, 032, 035, 039, 044 touch the
  Astro frontend repo (`noticiencias`) instead — implement those from that
  repo's working directory, not from here.
- Local commits only. One commit per completed plan (or per safely-separable
  phase of a large plan). No `git push`, no opening frontend PRs, no
  publishing — those need explicit operator sign-off (publication is
  PR-only per `docs/AGENTS.md`).
- Regression gates before any commit: `make test` (or the narrower
  plan-specific test target when the full suite is impractically slow to
  iterate on) plus `make lint && make type` for touched Python; the plan's
  own "Verification" section always wins if it specifies something more
  targeted.
- `except Exception: pass` is banned (per `docs/AGENTS.md`); policy modules
  (scoring, validation, taxonomy, editorial) stay network-free; I/O stays at
  the edges.
- After finishing a plan: update its row in `plans/README.md` (status +
  one-line note), update this file's "Sequencing state" section, commit.

## Dependency-driven order (superseding plans/README.md's numeric listing)

Per the dependency column in `plans/README.md`, the plans immediately
startable (all deps archived/done) are 033, 021, 023, 046. Everything else
is gated behind those four (see `plans/README.md`'s "Recommended waves" and
"Cross-plan integration rules" for the full graph). Re-derive the next
startable set from `plans/README.md` after each plan completes — do not
hardcode a full ordering up front, since finishing one plan changes what's
unblocked.

## Sequencing state

(Updated as work proceeds — see `todo.md` for the live checklist.)

- **033 — Make configuration refresh live**: DONE. Finished Phase 2 (all 21
  consumers migrated), Phase 3 (Refinery `save_toml_config` truthful
  return contract), Phase 4 (audit/lint/type/test gates, zero regressions
  vs. pre-existing baseline). See `plans/033/todo.md` for details.
- **021, 023, 046**: not started — next up per the dependency-driven order.

## Verification

- Per-plan: follow that plan's own "Verification" / "Done Criteria" section
  exactly.
- Whole-workspace: `make prepush` (test-all + quality-gate) before treating
  a wave of plans as safe to leave uncommitted-work-free; run it at natural
  breakpoints (end of a plan), not after every file edit.
- Every ~20 iterations: spawn a fresh subagent to review this spec.md plus
  the current diff/`plans/README.md` state for gaps (scope drift, skipped
  Done Criteria, silently-broken tests) and loop on its feedback.
