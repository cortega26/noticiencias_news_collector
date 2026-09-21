# Todo — Admin stack resilient ports

- [x] `SERVING_PORT` honored by `news_collector/serving/__main__.py` (fail-closed)
- [x] Unit tests: `tests/unit/serving/test_main_port.py` (default/honor/strip/reject/propagate)
- [x] Auto-bump + strict-explicit + collision guard in `scripts/dev/admin_stack.sh`
- [x] `API_PORT=`/`GUI_PORT=` overrides (+ `SERVING_PORT` precedence) in `Makefile` serve/admin-dev
- [x] `docs/RUNBOOK_LOCAL_DEV.md` admin paragraph updated
- [x] Live e2e with :8000 occupied (bump, proxy, teardown, squatter untouched)
- [x] `make lint` + serving tests green
- [ ] Live e2e of the collision path (`API_PORT=4321 make admin` → GUI bumps)
- [ ] Merge after Codex P1/P2 threads resolved + CI green
