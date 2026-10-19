# spec.md — plans/README.md ledger hygiene + validation

## Goals

1. `plans/README.md` becomes a thin, verifiable decision ledger:
   - accurate scope/header (third pass 2026-08-07, last-verified stamp),
   - explicit note that plan 052 was never allocated (prevents re-audit churn),
   - code references unambiguous (`apps/refinery/main.py`),
   - "findings considered and rejected" moved out of the ledger into `docs/audits/`,
   - "Recommended waves"/"Cross-plan integration rules" rewritten to reflect only remaining work.
2. DONE plans 050, 051, 053, 054, 055, 056 archived to `plans/archive/` per the ledger's own archival rule; their status rows collapsed to the "DONE and archived" convention.
3. The three open operator items (OLLAMA_MODEL resolution, NVIDIA slow-success latency policy, `SourceHealthTracker` FOUND/SAVED column semantics) raised as GitHub issues via `tools/audit_to_issues.sh`.
4. New `scripts/validate_plans_ledger.py` (with tests) that fails closed on:
   - DONE plans still in `plans/` root (unless explicitly marked "kept with reason"),
   - commit hashes cited in the ledger that don't resolve via `git cat-file -e`,
   - missing/out-of-date "Last verified" stamp,
   - status values outside the documented enum (TODO | IN PROGRESS | DONE | BLOCKED | REJECTED),
   - plan-file/status-table drift (a plan file on disk not present in the ledger table).
   Wired into a Makefile target and documented in `docs/ci.md`.

## Non-goals

- No changes to plan content or to the three open operator items' substance.
- No GitHub issue creation without a successful `gh auth` check (fail with a clear message instead).
- No rewriting of `plans/021/spec.md` or other per-plan working docs.

## Verification

- `make lint && make type && make test` green.
- New validator tests pass (targeted `pytest` invocation).
- `python scripts/validate_plans_ledger.py` exits 0 on the reconciled tree; exits non-zero on injected drift (a temp DONE file in `plans/` root; a bogus commit hash in the ledger).
- `plans/README.md` renders: no "Second pass (2026-07-21) supersedes" in header; 052 note present; waves section lists only 021/023/031/043/045/046/048 + open items.
- `plans/archive/` contains 050/051/053/054/055/056 (with spec folders where they exist).
