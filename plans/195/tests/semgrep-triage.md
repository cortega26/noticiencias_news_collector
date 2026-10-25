# Official Semgrep audit triage — 2026-10-25

Official Python/security-audit/secrets profiles:7matches,0scanner errors.
All seven are the SQLAlchemy text audit rule, not confirmed injection paths.
No source suppression or applied-migration edits were made.

| Location | Values and support | Decision |
| --- | --- | --- |
| news_collector/storage/models.py:629,642,656 | Partial-index predicates use module-owned queued/running status tuples and fixed column names. | No external data reaches SQL. |
| alembic/versions/84cf98a379c1_extend_workflow_runs_durable_dispatch.py:210,220 | The local check helper receives literal status and its module-owned tuple. | No external data reaches SQL. |
| alembic/versions/84cf98a379c1_extend_workflow_runs_durable_dispatch.py:268 | Partial index uses the module's fixed running constant. | No external data reaches SQL. |
| alembic/versions/effe4ec70d6d_add_durable_lifecycle_tables.py:93 | Partial index uses the module's fixed running constant. | No external data reaches SQL. |

The implementing agent and an independent review agent checked these data flows.
This is a dated source assessment, not a permanent exemption: future findings
and changes still require review. Findings remain visible in the JSON report.

The replaced starter rule matched any string assignment and generated603
undifferentiated notices; its include key did not activate the intended official
profiles. Local and CI now use those explicit profiles through the same target.
Scanner errors (including strict parse failures) fail; finding exit1 retains the
existing advisory policy. Metrics are disabled.

Real scanner controls use explicitly synthetic source that is never executed:
direct interpolated SQL is detected and plain constant strings are not. A first
indirect text(variable) probe was not detected; these community pattern rules do
not establish comprehensive taint analysis. Strict malformed source returns3;
a missing scanner makes the Makefile fail. See semgrep-controls.json.
