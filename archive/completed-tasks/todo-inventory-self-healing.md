# Todo: self-healing inventory baseline

Execution index for [`spec-inventory-self-healing.md`](spec-inventory-self-healing.md).

## Implementation

- [x] `scripts/generate_inventory.py`: `--fail-on-drift` + missing-baseline handling
- [x] `tests/test_generate_inventory.py`: drift/clean/missing-baseline cases
- [x] `Makefile`: `inventory-refresh`, `inventory-check`, `verify-ci` composition
- [x] `.github/workflows/inventory-autorefresh.yml`: heal + push + close issues
- [x] `docs/ci.md`: workflow, gate, local parity
- [x] `AGENTS.md` + `docs/AGENTS.md`: quick reference and validation bullet

## Verification

- [x] `pytest tests/test_generate_inventory.py` green (8 passed)
- [x] Gate green on current baseline (`drift_count=0`)
- [x] Drift simulation fails the gate with the `make inventory-refresh` hint
- [x] Heal is idempotent (regenerating twice yields no further diff)
- [x] Workflow heal body simulated against a bare remote, including a lost
      race (attempt 1 rebased and re-pushed; healed main reports drift 0)
- [x] Workflow YAML parses; `python scripts/check_doc_drift.py` green
- [x] `black --check` + `ruff check` + Makefile-tab check green
- [x] Refresh `audit/00_inventory.json` in this branch and re-verify

## Delivery

- [x] Commit, push `feat/inventory-self-healing`, open PR stacked on #346
- [x] First dispatch after merge; it exposed a timestamp-only auto-commit
      (`b568a47`) caused by a textual `git diff`, fixed via the semantic
      `drift_count` comparison in `inventory-autorefresh.yml`
- [x] After the semantic-diff fix merges (PR #349): re-dispatched
      `inventory autorefresh` (run 36577966393) — success, "No drift", `main`
      SHA unchanged (no new commit); the weekly audit should now stay quiet
      and the healer closes any recovered drift issue
