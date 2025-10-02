# Phase 4 — Runner & Flags Validation

## Summary
- Added end-to-end style pytest coverage for the `run_collector.py` CLI entry point focused on flag-driven flows.
- Captured expected exit codes, argument forwarding, and human-facing log lines for operational flags.

## Flag Test Matrix

| Flag Combination | Scenario | Expected Exit Code | Key Assertions |
| --- | --- | --- | --- |
| `--dry-run --show-articles 0` | Simulated collection without persistence | `0` | Output includes "🧪 MODO SIMULACIÓN"; `dry_run=True` passed to system |
| `--sources valid_source missing_source --show-articles 0` | Mixed valid/invalid source IDs | `0` | Warns about missing source and filters to valid list |
| `--list-sources` | Source catalog discovery | `0` | Prints "📚 FUENTES DISPONIBLES" with configured names |
| `--check-deps` | Dependency verification | `0` | Invokes dependency helper and prints success banner |
| `--healthcheck --healthcheck-max-pending 25 --healthcheck-max-ingest-minutes 10` | Operational health probe | `0`/`1` | Forwards thresholds to `scripts.healthcheck.run_cli` and exits with result |

## Execution Proof
- `pytest tests/e2e/test_runner_cli.py`

## Notes
- Tests patch heavy dependencies to keep execution fast while exercising the CLI argument parser and control flow.
- Healthcheck coverage validates both success and failure exit codes to ensure operators receive accurate status.
