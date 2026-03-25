# Audit Master Plan (Workspace)
Last updated: 2026-01-02

## Scope
- Repos in scope:
  - c:\Users\corte\VS Code Projects\noticiencias_news_collector
  - c:\Users\corte\VS Code Projects\noticiencias
- Out of scope:
  - External services not owned by this workspace (unless directly referenced by code)
  - Legacy translation repo (removed from workspace)

## Deliverables (single location)
- All audit outputs live in:
  - c:\Users\corte\VS Code Projects\noticiencias_news_collector\docs\audits
- Shared findings ledger:
  - c:\Users\corte\VS Code Projects\noticiencias_news_collector\docs\audits\Findings_Ledger.md

## Critical journeys (sampling anchor)
### noticiencias_news_collector
1) Collector run: RSS fetch -> enrichment -> scoring -> persist -> data/exports/latest_articles.json
2) Refinery publish: admin selects article -> LLM refinement -> write _posts -> PR creation

### noticiencias (site)
1) PR merge -> Jekyll build -> deploy -> live page render
2) Frontmatter/slug/date -> archive/category/tag pages render correctly

## Program sequence (adapted)
### Lane 1 (ship safety)
1) A-1 Architecture & System Context (shared, both repos)
2) A2 Security quick scan (both repos, prioritize news_collector first)
3) A6 Release, config, change safety (both repos)
4) A1 Business logic correctness (news_collector)

### Lane 2 (quality and velocity)
5) A0 Structure and modularity (lite)
6) A4a Engineering quality and perf baseline
7) A5 Process, ops, DevEx
8) A3 Data and AI (news_collector, high priority)
9) A4b UX/accessibility (site + refinery, after gates)
10) A7/A8 only if needed (regulated, enterprise, or cost spikes)

## Execution notes
- Single ledger: each finding has one home audit; cross-references only.
- Focus on S0/S1 first; do not start UX churn (A4b) until A2/A6/A1 gates are met.
- Evidence standard: file paths, line refs, logs, tests, or minimal PoC steps.

## Completed audit rounds

### 2026-Q1 (Jan) — Initial audit
- Lanes 1 & 2 executed. Findings F-0001 through F-0011. All closed.

### 2026-Q1 (Mar) — E2E deep audit
- Full pipeline audit: backend, ingestion, enrichment, publication, Streamlit, frontend.
- Findings F-0012 through F-0029 logged in [Findings_Ledger.md](Findings_Ledger.md).
- Remediation tracked in [`remediation/`](remediation/README.md):
  - [plan.md](remediation/plan.md) — Strategy, horizons, risks
  - [backlog.md](remediation/backlog.md) — **Source of truth for work tracking**
  - [test-plan.md](remediation/test-plan.md) — Required tests per fix

## Next actions
1) Execute Horizon A fixes (6 items, all `ready`). See [backlog.md](remediation/backlog.md).
2) Unblock B-01 by merging A-04 first.
3) After Horizon B, write C-01 and C-02 tests.
