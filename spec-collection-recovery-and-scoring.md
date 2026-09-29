# Spec: collection-run recovery, scoring durability, and fresh-article visibility

Status: in progress · 2026-09-26
Trigger: admin "Buscar noticias" run 49 (2026-09-26 16:21 UTC) — see
`todo-collection-recovery-and-scoring.md` for the evidence record.

## Symptoms (as reported)

1. The fetch seemed to find no new articles.
2. Scores did not change (recency should have moved them).
3. The run output/log carries several WARNINGS and ERRORS.

## Diagnosis (verified against run 49 and the live DB)

- The collector **did** insert 195 articles (16:22:03–16:23:09 UTC) — they are
  invisible because they stopped at `processing_status='validated'` (scoring
  never finished) and:
  - the triage queue defaults to `publishable` (the scored export shortlist),
    and `_ADMIN_VALID_STATUSES` does not even accept `validated`
    (`news_collector/serving/api.py:186`);
  - the run banner shows nothing because the run never reached a terminal
    state.
- The run was **killed by a uvicorn autoreload** (`make serve` runs
  `reload=True`; source edits during the run restarted the worker and killed
  the in-process daemon thread). The durable `workflow_runs` row stayed
  `running` with a stale heartbeat:
  - `recover_expired_leases()` only reaps heartbeats older than
    `DEFAULT_LEASE_TIMEOUT_SECONDS = 3600`, so the row blocked single-flight
    (`409 already_running`) for up to an hour after a 3-minute run;
  - no worker identity is recorded, so recovery cannot tell a dead worker
    from a live long run.
- **Scoring** started but every provider failed (`groq` 429,
  `openrouter`/`nvidia`/`gemini` timeouts, `cloudflare` budget-skipped) →
  `LLM chain exhausted (purpose=scoring)` → heuristic fallback; the worker
  died before the page was persisted. `score_logs` is unchanged since
  2026-09-20. Scoring persists once per page (`_process_page` →
  `update_articles_score_bulk`), so one kill loses up to `page_size` (200)
  scores.
- `ProductionReadonlyStore.get_metrics` logged
  `Error reading prod metrics: bad parameter or other API misuse`
  (`news_collector/observability/enrichment_metrics_store.py:800`): one
  shared sqlite connection, no lock, and no reconnect after a failure — a
  single misuse poisons every later read until process restart.
- Remaining warnings are operational noise (dev admin-key warning, 2 sources
  failing, feed/HTML and 403/429 fetches, empty-content validation).

## Fix scope

1. **Unblock run 49** (done manually, 2026-09-26): CAS-style transition
   `running → interrupted` with `error_code='process_restarted'`, mirroring
   `recover_expired_leases`' own fields.
2. **Dead-worker run recovery** (`CollectionRunWorkflow`):
   - stamp `run_metadata.worker_pid` on `start()`;
   - `recover_expired_leases()` also reaps `running` collection rows whose
     recorded worker pid is no longer alive (same-machine topology), not just
     rows past the 1 h lease;
   - keeps the live-PID row untouched (a healthy long run must not be reaped).
3. **Per-sub-batch score persistence** (`ScoringCoordinator`):
   - `_process_page` scores and persists in bounded sub-batches instead of one
     page-wide persist, so a worker kill loses at most one sub-batch;
   - a later sub-batch persist failure stops the walk (as today) but the
     already-committed sub-batches are counted in the cycle stats.
4. **ProductionReadonlyStore**: lock the shared connection and reset it on a
   read error so a transient misuse cannot poison all later reads; allow
   injecting the DB path for tests.
5. **Fresh-article visibility** (admin):
   - accept `validated` in `_ADMIN_VALID_STATUSES` and add the triage status
     chip, so collected-but-unscored articles are visible;
   - confirm the run banner renders `interrupted` + `error_detail` (it already
     renders failed runs; add the interrupted label if missing).

Out of scope: changing LLM provider quotas/routing, subprocess-isolating the
collection run, disabling uvicorn autoreload, re-scoring policy changes.

## Verification

- `python -m pytest tests/unit/logic/workflows/test_collection_run_workflow.py`
- `python -m pytest tests/unit/scoring/` (coordinator + cognitive)
- `python -m pytest tests/unit/observability/`
- `python -m pytest tests/ -k "admin or articles"` (API status filter)
- `cd apps/admin && npm test && npm run check` (status chip)
- Baseline gates: `make lint && make type && make test && make test-boundaries`;
  `make quality-gate`; plans ledger (untouched root-spec files need no row).
- Real-run evidence: after the fix, trigger "Buscar noticias" with the dev
  server running and a source edit mid-run; the run must end `interrupted`
  (not block the next start), and a re-run must score the 195 validated
  articles (heuristic fallback fast-path) and persist them.

## STOP conditions

- Any change to publication identity, scoring weights, or provider routing.
- A live run is reaped while its worker PID is alive.
- Scoring stats double-count committed sub-batches.
