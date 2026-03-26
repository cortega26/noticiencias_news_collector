# Remediation — 2026-Q1 Deep Audit

**Created**: 2026-03-25
**Source**: End-to-end technical audit of Noticiencias (backend, pipeline, Streamlit, frontend)
**Findings**: F-0012 through F-0029 in [`../Findings_Ledger.md`](../Findings_Ledger.md)

## Documents

| File | Purpose | Update frequency |
|------|---------|-----------------|
| [plan.md](plan.md) | Strategy, horizons, sequence, risks, what-not-to-do | Stable after approval; update if strategy changes |
| [backlog.md](backlog.md) | **Source of truth** for tracking remediation work | Update Status/Owner as work progresses |
| [test-plan.md](test-plan.md) | Required tests and manual validations per fix | Update as tests are implemented |

## Reading order

1. **plan.md** — Understand the strategy and constraints before starting work.
2. **backlog.md** — Pick work items. This is the operational tracking file.
3. **test-plan.md** — Know what validation each fix requires before marking it done.

## How to use during execution

- When starting a fix: set Status to `in-progress` in backlog.md.
- When merging a fix PR: set Status to `done`, add PR link to Notes column.
- When closing a finding: update Status in `../Findings_Ledger.md` to `Closed`.
- Do NOT delete completed items from the backlog; keep them for audit trail.

## Quick status

| Horizon | Items | Done | Blocked |
|---------|-------|------|---------|
| A (Immediate) | 6 | 6 (A-01, A-02, A-03, A-04, A-05, A-06) | 0 |
| B (Structural) | 7 | 7 (B-01, B-02, B-03, B-04, B-05, B-06, B-07) | 0 |
| C (Maturity) | 3 | 3 (C-01, C-02, C-03) | 0 |

## Deferred findings

F-0024 (TOCTOU race, S2) is tracked in Findings_Ledger but has no dedicated backlog item. It is partially mitigated by B-01 (publishing state guards the critical path) and B-05 (atomic manifest writes). Add a standalone item if it becomes a problem in practice.
