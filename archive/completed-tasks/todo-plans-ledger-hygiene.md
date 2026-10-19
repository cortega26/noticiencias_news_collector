# todo.md — plans/README.md ledger hygiene + validation

- [x] Reconcile plans/README.md: header/stamp, 052 note, 017 `apps/refinery/main.py` prefix
- [x] Rewrite "Recommended waves" + "Cross-plan integration rules" to remaining work only
- [x] Move "findings considered and rejected" (2nd/3rd pass) to `docs/audits/2026-08-plans-rejected-findings.md`; keep one-line pointer
- [x] Archive 017/032/035/039/041/044/047/049/050/051/053/054/055/056 to `plans/archive/` (folders included); collapse ledger rows
- [x] Verify `tools/audit_to_issues.sh` (inspected: hard-wired to `./audit/*.md`, requires GH_TOKEN — not a fit) + `gh auth` (ok); raise the 3 open items as issues #246/#247/#248
- [x] Write `scripts/validate_plans_ledger.py`
- [x] Write tests for the validator (9 cases: clean, DONE-in-root, KEEP, missing/stale stamp, bogus commit, unknown status, orphan file, row-without-file)
- [x] Wire into Makefile (`plans-ledger-check` target + `verify-ci`) and `docs/ci.md`
- [x] Run `make lint` (green after black), `make test` (1789 passed / 4 skipped), mypy targets (clean), validator tests (9 passed), `make plans-ledger-check` (OK)
