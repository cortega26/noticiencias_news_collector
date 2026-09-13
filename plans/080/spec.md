# Plan 080 — Targeted reliability, API contracts, and editorial evaluation

Status: TODO — implementation not started; planning package prepared 2026-09-04.
Owner: News Collector. Public frontend changes are outside the selected scope.
Risk: tests are High; dependency/API/CI work is Critical under `docs/AGENTS.md`.

## Objective

Make collection/publication lifecycle regressions easier to find, eliminate four
handwritten admin response mirrors, and provide a reproducible way to evaluate
captured editorial outputs. Each deliverable must be useful independently.

This is an implementation handoff for a model working in short, separate sessions.
It is not authorization to deploy, publish articles, run live generation, or change
production data. The present task produces documentation only. Implementation
begins when the user assigns a phase.

## Selection and consequential decisions

| Recommendation | Decision | Reason |
| --- | --- | --- |
| Hypothesis stateful tests | Implement first | Already in test dependencies; directly exercises Plan 078 lifecycle behavior. |
| OpenAPI TypeScript | Implement four-response pilot | Concrete duplicate contracts; bounded first slice of existing Plan 060 Phase 6. |
| Promptfoo | Implement offline replay pilot | Demonstrate reproducible comparisons before wiring live providers or changing editorial policy. |
| OpenTelemetry | Defer | A useful candidate, but current telemetry must be inventoried and an operational question/backend chosen first. |
| Retraction Watch | Defer | Requires DOI relationship handling, freshness policy, storage and editorial decisions; not a trivial metadata field. |
| Pagefind | Defer | Current search has budget checks; replacement requires comparative evidence. |
| DBOS | Defer | Lifecycle replacement is costly; SQLite-only is an explicit prior operator decision. |
| Sentence Transformers | Defer | No measured duplicate-detection gap or labeled cross-language benchmark yet. |

The deferred items are not additional tasks for this executor. See
[the decision gates](04-verification-and-deferred.md). No framework migration,
PostgreSQL, Redis, vector database, new UI framework, publication schema change,
model switch, or production prompt change is part of this plan.

### Relationship to existing work

- Plan 078 defines startup versus `start()` recovery. Preserve its semantics.
- Plan 060 Phase 6 already owns generated admin/publication contracts. Phase 2
  here implements only the first four admin response aliases plus generation and
  drift checks. It does **not** complete Plan 060, mandate `openapi-fetch`, or
  implement its publication JSON Schema work. Update its progress only with the
  exact slice actually delivered.
- Plan 048's `tests/data/enrichment_eval.jsonl` contains reviewed topic/entity
  labels. Do not reuse those labels as article-factuality gold or alter its
  candidate-promotion threshold.
- Plan 046 records SQLite-only production and rejection of PostgreSQL adoption.
- At planning time, unrelated working changes existed in `ai_editor.py`,
  `editorial/readability.py`, `editorial/hero_alt.py`, and Plan 079. Record the
  current worktree before each phase and preserve changes belonging to others.

## Execution contract

Work from the News Collector root. Paths in implementation tables are relative
to that root unless explicitly marked otherwise. A path marked **new** is an
intended output, not an existing example to import.

1. Read root `AGENTS.md`, `docs/AGENTS.md`, this spec, `todo.md`, and only the
   assigned phase. Read referenced APIs before using them.
2. Complete one phase per reviewable change. Separate generated artifacts from
   behavioral edits within the diff when practical. Do not bundle other phases
   to make a failing phase pass.
3. Follow the file allowlist. A newly discovered necessary dependency requires
   updating that phase's spec first. Routine fixes within the stated scope do
   not need repeated permission. A production behavior change is a new decision.
4. Write the specified behavioral tests before implementation. New tests live
   in the existing suite; [tests/README.md](tests/README.md) maps requirements to
   them. Do not add executable tests merely to verify these planning documents.
5. Record commands, exit codes, elapsed time where relevant, and known baseline
   failures under this plan's `tests/` directory. Never mark a failing check
   green because it appears unrelated. Prove any baseline failure on unchanged
   code without discarding the user's working changes.
6. Run targeted checks while iterating, then the phase's required gate union.
   Do not lower coverage, increase global timeouts, add blanket skips, or add
   broad type casts to obtain a pass.
7. Keep `todo.md` current. At each major phase boundary obtain the fresh review
   required by `docs/AGENTS.md §0.1`; reviewer checks spec/code alignment, test
   evidence, and scope. Fix findings before marking the phase complete.
8. End each session with files changed, checks performed, acceptance IDs passed,
   unresolved issues, and the exact next task. Do not claim future phases done.

## Phase map and dependencies

| Phase | Document | Prerequisite | Completion outcome |
| --- | --- | --- | --- |
| 0 | [Evidence and preflight](00-evidence.md) | None | Current assumptions, baseline and supported APIs recorded. |
| 1 | [Stateful lifecycle tests](01-stateful-workflows.md) | 0 | Real SQLite lifecycle sequences tested against independent expectations. |
| 2 | [Generated admin contracts](02-admin-contracts.md) | 0; run after 1 for smaller diffs | Deterministic offline schema and four generated aliases with CI drift detection. |
| 3 | [Editorial replay evaluation](03-editorial-evaluation.md) | 0; run after 2 | Offline comparison/reporting tool with positive and negative controls. |
| 4 | [Verification and deferred work](04-verification-and-deferred.md) | 1–3, or explicitly reported partial delivery | Evidence-backed handoff; no deferred technology silently adopted. |

The order limits cognitive load; phases 1–3 do not share runtime dependencies.
A justified no-go for the evaluation pilot does not invalidate phases 1–2.

## Program acceptance

- **W1–W5:** lease and lifecycle invariants pass, including exact expiry
  boundaries, fresh missing-heartbeat protection, run-type isolation and
  repeated terminal operations. Existing concurrency tests remain intact.
- **A1–A5:** real app schema exports without production access, output is stable,
  four response types derive from it, observed error bodies remain compatible,
  and CI detects stale schema and stale TypeScript independently.
- **E1–E5:** replay validates captured editorial artifacts without generation or
  network access; meaningful negative controls fail; comparisons identify
  missing/error cases and preserve provenance; reports do not claim factual
  correctness based on structural checks.
- **V1:** relevant repository gates pass and fresh review finds no material gap.

Completion means selected deliverables are verified, not that all technologies
from the research answer have been adopted. Record any deliberately rejected
pilot with its evidence rather than adding a dependency with no demonstrated use.

## Rollback and compatibility

- Phase 1 is test-only. A discovered production bug gets its own documented
  minimal fix and regression, not a relaxed oracle.
- Phase 2 can revert generated aliases/tooling together; wire payloads, routes,
  authentication and publication identity must never need rollback.
- Phase 3 is isolated development tooling; removal must not affect publishing,
  normal tests, the existing quality gate or Plan 048 evaluation.
- No phase needs production migrations or writes to the public frontend repo.

## Suggested handoff prompt

> Implement Phase N of `plans/080/spec.md`. Read `AGENTS.md`,
> `docs/AGENTS.md`, `plans/080/todo.md`, and its phase document first. Work only
> inside that phase's scope. Add the specified tests, run the required checks,
> update the checklist and evidence, obtain the required phase review, and stop
> after that phase. Preserve unrelated work. Do not execute deferred items or
> live model/publication operations. If an assumption is false, update the spec
> with repository evidence before continuing.
