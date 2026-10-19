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

## Collector failure incidents

`.github/workflows/collector-incident-watcher.yml` reacts to every completed
`Daily News Collection` run on the default branch. It is the scheduled
collector's automated failure signal; `daily_collector.yml` itself no longer
opens a dated issue per failure.

What the operator sees:

- A `failure` or `timed_out` run opens one stable issue titled
  `Collector incident: Daily News Collection <conclusion> (<UTC date>)`, reopens
  the most recent closed issue carrying the watcher marker, or updates the
  existing open incident.
- The issue body records the run URL, branch, fingerprint
  (`<conclusion>/<failed job names>`) and observation time. The watcher updates
  that issue at most once per 24 h per identical fingerprint; a repeated
  identical failure inside that window is intentionally silent.
- A later `success` comments the recovery run and closes the incident. A
  `cancelled` run only opens or updates an incident when no successful run is
  recorded or the last success is older than 30 h; a recent cancellation is
  silent. Other conclusions are a no-op.

How to acknowledge:

1. Open the run link in the issue and capture the failing job's log.
2. Comment on the incident with the triage and owner. The watcher closes the
   issue on the next successful default-branch run; closing it by hand does not
   prevent it from reopening on the next failure.
3. Do not retitle the issue or edit the `<!-- watcher-fingerprint: ... -->`
   marker. The watcher finds its issue through the `Collector incident` title
   search and refuses to touch an issue whose body lacks its marker.

Fail-closed branches (the watcher stops instead of guessing):

- More than one open issue matches `Collector incident in:title` — the watcher
  fails and asks the owner to triage the duplicates.
- The single matching issue has no fingerprint marker — treated as a possible
  human-titled collision; the watcher fails without editing it.
- Historical dated failure issues are never touched.

The watcher runs with `issues: write`, `actions: read` and `contents: read`,
serialized by a `collector-incident-watcher` concurrency group.

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
`../noticiencias/docs/webhook-integration.md` for transport details.

Record incident evidence, mitigation and verification results. No production
incident, live alert or restoration was exercised by the documentation audit.
