# Publication run lifecycle

Status: Derived.

Module: [news_collector/logic/workflows/publication_run_workflow.py](../../news_collector/logic/workflows/publication_run_workflow.py)

Owns durable run status, start/conflict behavior, heartbeat, terminal updates
and interrupted-run recovery for `publication`. Execution uses process-local
threads; the status row does not provide step replay.

Dispatch recovery preserves queued rows and fresh running leases. Startup
can interrupt queued rows under the current single-owner assumption. A missing
heartbeat requires an old start timestamp to be expired.

Verification: `tests/unit/logic/workflows/test_publication_run_workflow.py`.
Read [pipeline contracts](../../docs/PIPELINE_CONTRACTS.md) before changing
HTTP results, recovery timing or state transitions.
