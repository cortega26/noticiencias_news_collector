# Source-Of-Truth Backlog

## Critical

### Cross-repo publication contract gate

Problem: The backend mirrors the frontend publication schema, but both repos can still drift independently without a single shared CI gate.  
Impact: Publication failures and schema mismatches can be discovered late, after changes land in only one repo.  
Recommendation: Add a coordinated contract-validation step spanning `news_collector/contracts/frontend_schema.py` and `../noticiencias/src/content/config.ts`.  
Affected repo(s): backend, frontend  
Suggested priority: critical

## High

### Remove current-date fallback from canonical publication identity

Problem: `RefineryEngine` still falls back to current date when `published_date` and `collected_date` are unavailable.  
Impact: Canonical identity is weaker than the docs ideally want it to be, and retries can become harder to reason about in edge cases.  
Recommendation: Make source date or explicit editorial date mandatory before publication, or quarantine articles that cannot provide one.  
Affected repo(s): backend  
Suggested priority: high

### Decompose `RefineryEngine`

Problem: `news_collector/logic/workflows/refinery_engine.py` currently owns orchestration, image handling, manifest logic, file I/O, Git operations, and recovery.  
Impact: The module is difficult to reason about, harder to test in isolation, and prone to further architectural drift.  
Recommendation: Extract focused collaborators for publication identity, target-repo writes, image-brief handling, and PR orchestration.  
Affected repo(s): backend  
Suggested priority: high

### Retire duplicate collector entrypoints

Problem: `scripts/run_collector.py`, `main.py`, and older workflow surfaces overlap.  
Impact: Docs and automation drift more easily, and contributors are less certain which path is authoritative.  
Recommendation: Choose one primary collector entrypoint, migrate automation to it, and explicitly deprecate the others.  
Affected repo(s): backend  
Suggested priority: high

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
