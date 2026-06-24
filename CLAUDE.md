# CLAUDE.md

> **Pointer.** The authoritative AI agent governance documents are:
> - [`AGENTS.md`](./AGENTS.md) — quick reference, commands, project map, contracts
> - [`docs/AGENTS.md`](./docs/AGENTS.md) — full engineering governance law
>
> Read `docs/AGENTS.md` before making any change. It contains the mandatory
> spec-driven workflow (§0.1), architectural laws, and change matrix.

## Quick commands

```bash
make bootstrap        # first-time setup
make test             # unit suite   |   make test-all  # full suite
make lint             # ruff + black + isort
make lint-fix         # auto-format
make type             # mypy strict
make quality          # lint + type + bandit + pip-audit + semgrep
make prepush          # test-all + quality-gate

python scripts/run_collector.py --dry-run  # collector dry run
```

## Key facts

- I/O stays at edges; policy modules (scoring, validation, taxonomy, editorial) are network-free
- Contracts (`contracts/frontend_schema.py`) are cross-repo — changes affect the frontend
- Publication goes through PRs only; never write to the frontend repo directly
- `except Exception: pass` is banned everywhere
- `main.py` is removed; use `python scripts/run_collector.py`
