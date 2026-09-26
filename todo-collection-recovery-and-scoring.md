# Todo: collection-run recovery, scoring durability, and fresh-article visibility

Execution index for [`spec-collection-recovery-and-scoring.md`](spec-collection-recovery-and-scoring.md).

## Evidence (run 49, 2026-09-26)

- [x] 195 articles inserted 16:22:03–16:23:09 UTC, all `processing_status='validated'`, `final_score NULL`.
- [x] Heartbeat stopped 16:24:56 UTC; worker PID 879277 gone (uvicorn reload);
      row stayed `running` (lease 3600 s) and blocked single-flight.
- [x] `LLM chain exhausted (purpose=scoring)` (groq 429, openrouter/nvidia/gemini
      timeouts, cloudflare budget) then heuristic fallback; no scores persisted.
- [x] `Error reading prod metrics: bad parameter or other API misuse`.
- [x] Run 49 transitioned `running → interrupted` manually (unblocked).

## Fixes

- [x] 2. `CollectionRunWorkflow`: `worker_pid` stamp + dead-worker reap
  - [x] `start()` records `worker_pid`; `recover_expired_leases()` also reaps
        rows whose recorded pid is dead (fresh heartbeat or not)
  - [x] tests: dead pid → `interrupted` (detail carries the pid); live pid
        stays `running`; pid stamp asserted on `start()`
- [x] 3. `ScoringCoordinator`: per-sub-batch score persistence
  - [x] `_PERSIST_BATCH_SIZE = 25`; `_process_page` persists each sub-batch;
        a later failure stops the walk but keeps committed counts
  - [x] tests: bounded sub-batches (2+1 for 3 items at size 2); failure keeps
        the committed sub-batch counted
- [x] 4. `ProductionReadonlyStore`: lock + reconnect on error (+ injectable path)
  - [x] `_lock`, `_reset_connection`, guarded cursor/execute; `db_path` injectable
  - [x] tests: injected path reads; missing DB; poisoned connection recovers;
        `close()` resets
- [x] 5. Admin: `validated` status accepted + triage chip; interrupted banner
  - [x] `_ADMIN_VALID_STATUSES` + `ArticleStatus`/`ARTICLE_STATUSES` + triage
        chip `Recolectadas`; API test fixture seeds a `validated` article
  - [x] Python status-filter tests (17 passed); admin vitest 35 passed +
        `npm run check` clean (interrupted banner already existed)

## Independent review (fresh context)

- [x] Reviewer found the sub-batch failure path inflated uncommitted counters;
      fixed by keeping batch counters local until the persist succeeds
- [x] Guarded `_PERSIST_BATCH_SIZE <= 0` (`max(1, ...)`), documented the
      same-machine PID assumption, added the `validated` chip style and the
      article-page label, and strengthened the sub-batch tests (full stats,
      `filters.status`)
- [x] Accepted with rationale: `_score_payloads` re-raise (no sequential
      fallback) still propagates — committed sub-batches remain persisted;
      rare and unchanged from the pre-fix behavior

## Gates

- [x] `make lint`; `make type` (3391 passed, ratchet 92.73% vs 91.25%);
      `make test` (3378 passed); `make test-boundaries`; `make quality-gate`;
      plans ledger
- [x] Admin: vitest 35 passed + `npm run check` clean
- [x] Real-run evidence:
  - run 50 stamped `worker_pid=1352584`; a forced source-edit reload killed
    the worker and the next startup reaped the row to `interrupted` with
    `error_code=process_restarted` and the dead pid in the detail (~16 s
    start→reap, way inside the 1 h lease);
  - run 51 then started (`worker_pid=1404081`) and succeeded in 435 s;
    the 195-article validated backlog scored and persisted (582 `score_logs`
    rows today, `validated` count 0, `status=validated` filter empty).
