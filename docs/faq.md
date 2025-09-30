# Troubleshooting FAQ

## Why do I see `sqlite3.OperationalError: database is locked` during ingestion?
- The local SQLite file is single-writer. Ensure no other process (another collector run, manual SQL session, or GUI client) is holding the lock.
- Run `python run_collector.py --healthcheck` to verify queue depth after the contention clears.
- In CI or concurrent dev runs, point `DATABASE_URL` to a throwaway Postgres instance or use the WAL mode documented in [`docs/runbook.md`](docs/runbook.md).

## The collector returns HTTP 429 or `rate limit exceeded`. What now?
- Confirm the source-specific pacing in `config/sources.py` (`min_delay_seconds`) matches provider guidance.
- If the limit is domain-wide, adjust `RATE_LIMITING_CONFIG["domain_overrides"]` in `config/settings.py`.
- Review the structured logs described in [`docs/collector_runbook.md`](docs/collector_runbook.md) to ensure retries include `trace_id` and `source_id` for observability.
- After tuning, re-run `python run_collector.py --dry-run --sources <id>` and watch Grafana or local metrics for lingering throttling.

## Enrichment fails with `ModelNotFoundError`. How do I recover?
- Verify the expected model artefacts exist under `models/` or the configured cache directory; consult [`docs/fixtures.md`](docs/fixtures.md) for canonical locations.
- Run `make bootstrap` to pull optional extras listed in `requirements-security.lock` if you are on a fresh environment.
- If the model version advanced in production, update the local copy and regenerate any dependent fixtures via the steps in [`docs/fixtures.md`](docs/fixtures.md).
- For persistent issues, escalate via the enrichment section of [`docs/runbook.md`](docs/runbook.md) so on-call can restore the managed model store.
