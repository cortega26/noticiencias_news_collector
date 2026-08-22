# ADR-0008: Harden the Two-Repo Boundary Before Reconsidering Consolidation

**Date**: 2026-08-22
**Status**: Proposed
**Deciders**: Engineering team

---

## Context

Backend ADR-0003 already decided to keep two repositories (`noticiencias`
and `noticiencias_news_collector`) connected by a contract-mirror pattern.
Plan 060's evidence baseline documents real, measured operational pain:
v2 posts failing strict editorial validation, admin state lost on restart,
callback reconciliation gaps, and unqueryable operational state (the subject
of ADR-0006), plus a drift-prone hand-maintained contract layer (the subject
of ADR-0007).

None of that measured pain traces to the repository boundary itself — it
traces to unenforced contracts and missing durable state within each repo.
It would be premature to treat the two-repo split as the root cause and
reconsider consolidation before the actual root causes (contracts, state,
observability) have been addressed and their effect measured.

---

## Decision

This ADR does not reverse or supersede ADR-0003. It records an explicit
sequencing decision: harden contracts, durable state, and observability
first — all phases of plan 060 — and only then measure actual cross-repo
coordination overhead for at least one full release window before writing
an evidence-based keep-split-or-consolidate decision. That final decision is
master plan Phase 11's scope, not this ADR's.

Reconsidering consolidation before that measurement window is a listed
program-wide STOP condition in the master plan
(`plans/060/spec.md`, "Program-wide STOP conditions": "repository
consolidation is proposed without measured post-hardening cost"). Any
proposal to consolidate the repositories before Phase 11's measurement
exists should be treated as violating that STOP condition, not as a
legitimate architectural discussion to have on its own merits at this point
in the program.

---

## Consequences

**Positive**:
- Prevents a large, disruptive repository merge from being undertaken on
  the strength of symptoms that are actually caused by fixable contract and
  state problems, not by the boundary.
- Gives Phase 11 a real evidence baseline — measured coordination cost after
  hardening — instead of a decision made on current, unhardened pain.
- Keeps ADR-0003's runtime separation benefits (independent Node/Python
  toolchains, independent deploy cadence) intact for the duration of plan
  060.

**Negative**:
- Defers any relief that a repository merge might genuinely provide until
  Phase 11, even if some of plan 060's other phases turn out not to fully
  resolve the coordination overhead.
- Requires discipline across the whole program to not preemptively reach for
  consolidation as a shortcut when an individual phase's contract/state work
  turns out to be difficult.

---

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Consolidate into a monorepo now | Rejected — premature per the program-wide STOP condition above; also explicitly listed under the master plan's "Out of scope": "A big-bang monorepo move or framework/language rewrite" |
| Do nothing / leave ADR-0003 as the last word | Rejected — the evidence baseline shows real, measured reliability gaps (ADR-0006, ADR-0007) that need addressing regardless of eventual repository shape |
