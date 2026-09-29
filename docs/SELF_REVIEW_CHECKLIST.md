# Self-Review Checklist — internal adversarial guardrails

Status: active. This is the internal counterpart to external (Codex)
review: every item below is distilled from a real finding Codex made on
a Noticiencias PR, so that routine review rounds stop spending daily
Codex quota on catches we can make ourselves.

Two layers: deterministic gates (scripts, block CI) and judgment checks
(human or local-model review, advisory). The mapping table at the end
shows which is which. Nothing here replaces Codex on High/Critical
changes — it reduces the rounds Codex needs to find anything.

## A. Spec-vs-code consistency (Codex P1 class)

- [ ] Every behavior claim in the spec/todo matches the diff. No
      aspirational statements, no TBD identifiers in live paths, no
      dataset declared without a consuming task, no task without a
      recorded metric. (PR #322: enrichment corpus, token counts.)
- [ ] Every metric/threshold references telemetry that exists where
      claimed. Open the schema/store and confirm each field; never
      assert observability by naming it. (PR #322: `llm_calls` has no
      token columns.)
- [ ] Every command quoted in docs runs as written. Make targets forward
      arguments only through their documented mechanism (`ARGS`, env);
      never invent flag pass-through. (PR #322: `make llm-report --days`.)
- [ ] Cross references resolve: files, line numbers, make targets,
      workflow names. (`make docs-check` covers declared invariants;
      this item covers prose claims it cannot see.)

## B. Provider-chain semantics (Codex P1 class)

- [ ] A new `[[llm_endpoints]]` entry: list every chain it joins by
      default. The factory default order includes ALL endpoints, so a
      "harness-only" entry joins live traffic unless pinned out — prove
      with `dry-run`/resolved-primary output, not by reading intent.
      (Benchmark harness: Ultra/GLM entries.)
- [ ] A `purpose_chains` edit: confirm the consumer actually passes that
      purpose string (grep the `get_provider(purpose=...)` call sites).
- [ ] Any multi-provider path: how is mixed serving detected, counted,
      and kept out of means? Failures visible in the denominator?
      (Benchmark: mixed-run rule, attempt caps, revisit passes.)
- [ ] Judge independence: does any grader share a model with what it
      grades? Self-grading invalidates comparative thresholds; use fixed
      graders or a cross matrix. (PR #322: critic self-grading.)
- [ ] Groundedness: does the judge see the ground truth (source text),
      or only the artifact plus a pointer to it? A judge without source
      access measures caution, not correctness. (PR #322: auditor.)

## C. Process entrypoints and env precedence

- [ ] Precedence is explicit and honored at every layer: direct env >
      CLI/make override > default. Test each level, especially the
      negative (explicit garbage must fail closed, not fall through).
      (PR #321: `SERVING_PORT` overwritten by the recipe.)
- [ ] No value hardcoded in two places that can drift (port in `.py` +
      `.sh` + `Makefile` + docs). One source, the rest derived.
- [ ] Explicit pins are strict; defaults are resilient. Silent relocation
      of an explicitly requested port/path/key is a bug. (PR #321.)

## D. Bash traps (from real incidents, all observed in this repo)

- [ ] No `die`/`exit` inside `$(...)`: the subshell swallows it and the
      parent continues with empty output. Fail in the parent.
- [ ] `pgrep -f`/`pkill` patterns use the `[b]`racket trick — otherwise
      they match the invoking shell itself.
- [ ] No variable shadowing across scopes (the `resolved_ok` re-run
      incident). Resume/skip state must survive the whole script.
- [ ] Resume logic proven by re-running: second invocation must skip
      completed work visibly (log the skips) and never duplicate rows.
- [ ] Signal semantics: background jobs ignore INT; test teardown with
      TERM. Never "verify" cleanup from the same shell that launched it
      without accounting for job-control semantics.
- [ ] `bash -n` clean; every new trap/loop reviewed line by line.

## E. Content and translation (frontend mirror)

- [ ] `npm run check:translation-residue` green (automated: PT fails,
      EN suspects warn). Proper names stay clean by construction.
- [ ] Every number in body AND `fact_check` traces to a cited source.
      `uncertain` status does not cure an unsourced quantity — replace
      or remove it. (PR #197: Roman yield.) Human check, always.
- [ ] No leftover source-language terms in rendered prose. The residue
      gate catches the known classes; read the diff once for the rest.

## F. Quota discipline (protects the Codex budget itself)

- [ ] Batch fixes per push. Each push to an open PR spends one Codex
      review round: accumulate all known fixes, then push once.
- [ ] Green-before-push: full local gate (`make lint`, targeted tests,
      affected validators) passes BEFORE the push that requests review.
- [ ] Keep PR scope tight. Split unrelated changes; a second small PR
      costs less quota than a second round on a sprawling one.
- [ ] Draft PRs for work-in-progress so review (and quota) fires once,
      on mark-ready — not on every intermediate push.
- [ ] Resolve threads with code + reply, then resolve. Never leave a PR
      BLOCKED on a thread whose fix already merged.

## Coverage map (what catches what)

| Codex finding (real) | Internal guardrail | Type |
|---|---|---|
| Imageless search grid (#196) | Responsive-layout checklist + visual smoke (manual) | judgment |
| Missing spec/todo (#321) | This checklist §A + PR template checkbox | judgment |
| Port collision (#321) | Threat-model the override matrix (this checklist §C) | judgment |
| SERVING_PORT ignored (#321) | Env-precedence tests per level (this checklist §C) | deterministic* |
| Roman quantity (#197) | Source-trace rule (this checklist §E) | judgment |
| descoberta/youth (#197) | `check-translation-residue` (frontend lint) | deterministic |
| Self-grading critic (#322) | Fixed-grader/cross-matrix rule (this checklist §B) | judgment |
| Auditor without sources (#322) | Groundedness rule (this checklist §B) | judgment |
| Missing token telemetry (#322) | Schema-first metric claims (this checklist §A) | judgment |
| Make ARGS syntax (#322) | Docs-command verification (this checklist §A) | deterministic* |
| 080 substitution error (#322) | Scope-fidelity re-read of cited plans (this checklist §A) | judgment |
| Unused dataset (#322) | Declared-data-must-be-consumed rule (this checklist §A) | judgment |
| Bash/process incidents | This checklist §D | deterministic* |

Items marked deterministic* are human-verifiable in seconds and belong
in the pre-push routine; the rest need judgment — yours, or the local
reviewer (`scripts/adversarial_review.py`, unlimited, offline) before
spending Codex quota on them.
