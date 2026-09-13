# Operations runbook

Status: Active. Commands run from the backend root after `make bootstrap`.
For configuration, see [database_deployment.md](database_deployment.md) and
[collector_runbook.md](collector_runbook.md). Dashboard availability and
alert thresholds must be verified in the deployment; this repository does
not establish a live Grafana paging policy.

## Collection freshness or backlog

1. Run `.venv/bin/python scripts/run_collector.py --healthcheck` and capture
   its output and exit status. The default limits are 250 pending articles
   and 180 minutes since the latest ingest; see [runbooks/healthcheck.md](runbooks/healthcheck.md).
2. Check the scheduler, active collection run and source-specific errors.
   Compare the effective database path with the collector's configuration.
   An empty or different database can make a healthy process appear idle.
3. For SQLite lock failures, identify competing writers and stop the relevant
   process gracefully. SQLite is a file database, not a PostgreSQL service
   to restart. Do not delete state or add workers as a generic recovery step.
4. For source failures, inspect rate-limit responses, feed parsing and
   provider availability. A targeted dry-run can check connectivity but
   does not drain backlog or prove normal persistence.
5. Verify with an intended collection cycle, fresh persisted timestamps and
   another healthcheck. Preserve the original thresholds in incident evidence;
   increasing a threshold does not fix an incident.

## Stuck collection or publication runs

`workflow_runs` stores execution state. Inspect the run ID, run type, status,
`heartbeat_at`, `started_at` and error before retrying. Collection and
publication each permit one queued/running run at a time; the constraint is
per run type, not a guarantee that only one writer exists in the whole system.

A start request recovers expired running leases without requiring a restart,
then either starts a run or returns the existing active run as a conflict.
A queued row is preserved during this request-time recovery. Startup recovery
also interrupts queued rows under the current single-owner process assumption.
Fresh running leases are preserved. Missing-heartbeat rows become stale only
when their start time is older than the lease cutoff.

Recovery marks work interrupted; it does not resume an LLM/Git operation at
its last step. Inspect persisted publication identity and existing PRs before
retrying. See [PIPELINE_CONTRACTS.md](PIPELINE_CONTRACTS.md) for exact ownership
and tests. Do not promise exactly-once external effects or horizontal scaling
from the database uniqueness constraint alone.

## Duplicate or low-quality candidates

Capture representative article IDs, canonical URLs, source IDs and timestamps.
Reproduce against fixture-based tests such as `tests/test_dedupe_utils.py`
and `tests/unit/utils/test_dedupe.py`. Review the actual storage and dedupe
implementation before proposing a threshold change or data repair. Do not
query columns or run reclustering scripts copied from archived incident notes.
Validate a repair on disposable data before applying it to editorial state.

## PR created but publication state is stale

Check frontend Content Guard/deploy logs, the callback's `publication_ids`
and transport result, then the backend webhook logs and database identity.
A successful workflow run is not deployment proof. Events without matching
IDs do not complete/reject arbitrary attempts; a missing best-effort callback
can leave state stale after a successful deployment. Use the sibling
`docs/webhook-integration.md` for transport details.

Record incident evidence, mitigation and verification results. No production
incident, live alert or restoration was exercised by the documentation audit.
