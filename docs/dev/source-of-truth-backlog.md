# Source-Of-Truth Backlog

## Critical

### ~~Cross-repo publication contract gate~~ **CLOSED**

Implemented in CI (2026-08-13 verification): `.github/workflows/ci.yml` runs a
`contract-parity` job that sparsely checks out `../noticiencias/src/content.config.ts`
and runs the same `scripts/check-contract-sync.js` the frontend's Content Guard
uses, and `.github/workflows/publication-smoke.yml` runs
`scripts/validate_frontend_publication.py` against the front-end schema on
publication-touching paths. Both repos are gated on the same contract in CI.

## High

### ~~Remove current-date fallback from canonical publication identity~~ **CLOSED**

Implemented in plan 058 (2026-08-13): `_derive_date` now derives
deterministically from `published_date` → `collected_date`, and quarantines
dateless articles with `UndatedArticleError` (`E_IDENTITY_NO_DATE`) instead
of using the runtime clock. `ai_editor` also refuses a missing
`override_date` (no clock in frontmatter). See
`plans/058-deterministic-publication-date/spec.md`.

### Decompose `RefineryEngine`

Problem: `news_collector/logic/workflows/refinery_engine.py` currently owns orchestration, image handling, manifest logic, file I/O, Git operations, and recovery.  
Impact: The module is difficult to reason about, harder to test in isolation, and prone to further architectural drift.  
Recommendation: Extract focused collaborators for publication identity, target-repo writes, image-brief handling, and PR orchestration.  
Affected repo(s): backend  
Suggested priority: high

### ~~Retire duplicate collector entrypoints~~ **CLOSED**

`main.py` has been removed. `scripts/run_collector.py` is the sole collector entrypoint. If older workflow surfaces still reference `main.py`, they should be migrated to `run_collector.py`.

## Medium

### Replace legacy `docs/ops/RUNBOOK.md` compatibility path with eventual removal

Problem: The stale path has now been demoted, but it still exists to preserve references.  
Impact: Future contributors may re-expand it instead of updating the focused current runbooks.  
Recommendation: After existing links are migrated, remove the compatibility file and keep a single runbook index page.  
Affected repo(s): backend  
Suggested priority: medium

### Add docs drift tests for active governance files

Problem: Link checking exists, but there is no targeted drift check for the active governance stack.  
Impact: README and governance docs can quietly diverge from Make targets, workflow job names, and repo boundaries again.  
Recommendation: Add a lightweight docs consistency test for active commands, workflow names, and authority-order references.  
Affected repo(s): backend  
Suggested priority: medium
