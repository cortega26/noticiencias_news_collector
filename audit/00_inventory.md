# Repository Inventory

## Top-Level Layout
- `AGENTS.md`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `Dockerfile`
- `Makefile`
- `README.md`
- `config/`
- `config.toml`
- `core/`
- `docs/`
- `main.py`
- `news_collector_structure.py`
- `noticiencias/`
- `pyproject.toml`
- `reports/`
- `requirements-security.lock`
- `requirements.lock`
- `requirements.txt`
- `run_collector.py`
- `scripts/`
- `setup.py`
- `src/`
- `tests/`
- `tools/`

## Key Runtime Facts
- **Python compatibility:** Project metadata and tooling target Python 3.10+, enforced via `requires-python >= 3.10` and mypy/ruff settings for 3.10. Docker image builds on Python 3.11-slim. Config metadata exposes the same floor (`>=3.10`).
- **Primary orchestrator:** `main.py` defines `NewsCollectorSystem` with CLI flags for sources, dry-run, top articles, and stats display.
- **Operator convenience script:** `run_collector.py` wraps `create_system()` with richer CLI, health checks, and dependency validations. Supports flags for source selection, dry-run, quiet/verbose modes, top article display, listing sources, and operational healthchecks.
- **Library exports:** `src/__init__.py` surfaces collectors, scoring, storage, logging, metrics, and serving factories for programmatic use.

## Entry Points & CLI Commands
| Command | Description |
| --- | --- |
| `python run_collector.py [options]` | Friendly CLI wrapper for initializing and running a collection cycle, listing sources, checking dependencies, and running health checks. |
| `python main.py [options]` | Direct entry into `NewsCollectorSystem` for batch runs, optionally filtering sources or printing stats. |

## Dependency Snapshot
- `requirements.txt` pins top-level libraries for feed ingestion, NLP, persistence, scheduling, API serving, logging, testing, ML helpers, and optional async HTTP support.
- `requirements.lock` is a hash-locked export compiled with Python 3.12, ensuring reproducible installs for runtime dependencies.
- `requirements-security.lock` locks security extras (bandit, pip-audit, trufflehog3, etc.) with hashes for compliance workflows.
- Optional `security` extras declared in `pyproject.toml` align with the dedicated lockfile for governance tooling.

## Supporting Notes
- Tooling configuration (`pyproject.toml`) enables Ruff, mypy, and pytest defaults for Python 3.10 targets.
- Container builds (`Dockerfile`) base on Python 3.11, keeping runtime within the supported interpreter range.
