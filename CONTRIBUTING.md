# Contributing to Noticiencias News Collector

Thanks for supporting the Noticiencias pipeline! This guide summarises the expectations for code quality, collaboration, and fixture maintenance so that every change ships safely.

## Development workflow
1. **Bootstrap once per machine**
   ```bash
   make bootstrap
   ```
2. **Work inside the virtual environment**: activate `.venv/bin/activate` (or `Scripts/activate.ps1` on Windows).
3. **Prefer small, focused branches**: isolate behavioural changes, update docs alongside code, and keep feature flags in `config/features.yaml` when applicable.

## Coding standards
- **Python ≥ 3.10** with modern typing (`TypedDict`, `Protocol`, `Final`) for public interfaces.
- **Style**: follow Ruff defaults + PEP 8; prefer dataclasses for structured payloads and keep functions <50 lines where possible.
- **Logging**: emit structured dictionaries using the fields documented in [`docs/collector_runbook.md`](docs/collector_runbook.md); include `trace_id`, `source_id`, and latency metrics.
- **Time handling**: normalise to `datetime.datetime` with `timezone.utc`. Only convert to `America/Santiago` within the presentation layer.
- **Idempotency**: collectors, enrichment jobs, and storage writes must accept retries. Use canonical URL hashes as stable keys as described in `AGENTS.md`.

## Quality gates before opening a PR
Run the following from the repo root; CI enforces the same checks:
```bash
make lint      # Ruff static analysis (fix issues locally if needed)
make typecheck # mypy across src/ and tests/
make test      # pytest with coverage reports in reports/coverage/
```
For security-sensitive work also execute `make security` (pip-audit, bandit, secrets scan).

## Commit and PR conventions
- Use **Conventional Commits** (`feat:`, `fix:`, `docs:`, `chore:`, etc.) to ease changelog generation.
- Reference incidents, tickets, or audit findings in the PR description when they drive the change.
- Update `CHANGELOG.md` when user-facing behaviour or operational guidance evolves.
- Attach relevant runbook links (`docs/runbook.md`, `docs/collector_runbook.md`) for operational changes.

## Refreshing fixtures
When behaviour changes, refresh fixtures so regression suites stay trustworthy:
- **Scoring golden set** (`tests/data/scoring_golden.json`): run `python scripts/score_delta.py --dataset tests/data/scoring_golden.json` to review diffs, then regenerate using the snippet in [`docs/fixtures.md`](docs/fixtures.md) to freeze timestamps.
- **Collector/outage fixtures** (`tests/data/monitoring/*.json`): replay with `python scripts/replay_outage.py <fixture>` and update the fixture once the new behaviour is verified.
- **Performance baselines**: follow the guardrails in [`docs/performance_baselines.md`](docs/performance_baselines.md) and capture new metrics before committing.

Happy shipping! 🚀
