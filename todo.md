# Todo: Implement the remaining plans (see spec.md)

Previous pass (plans 001–016) is complete and archived under `plans/archive/`;
this file now tracks the current pass over the 18 remaining plans.

## Plan 033 — Make configuration refresh live (DONE)

- [x] Phase 1: `RuntimeConfigSnapshot`, `get_runtime_config()`,
      `refresh_runtime_config()` atomic rebuild + tests (`tests/unit/config/`,
      23 passing).
- [x] Phase 2.1–2.5: migrate base/html/reddit/rss collectors + rate_limit_utils.
- [x] Phase 2.6–2.21: migrate remaining consumers (scoring x4, storage x3,
      infrastructure x2, enrichment, system x3, utils/logger, contracts,
      logic/workflows). Also fixed two decorator-baked tenacity retry
      policies (requests_client.py, http_client.py) that would otherwise
      have stayed stale despite the migration, and 2 stale test mocks that
      patched the old by-value config names.
- [x] Phase 3: Refinery truthfulness — `save_toml_config()` now validates
      (both pydantic shape and business rules) before writing to disk,
      returns `{success, version, changed_keys, restart_required_keys}`,
      and every "Guardar" button in admin_panel.py surfaces that truthfully
      via a shared `render_save_result()` helper.
- [x] Phase 4: import audit clean (only intentionally-live ALL_SOURCES
      remains), black/ruff/mypy show zero new findings vs. pre-existing
      baseline, full test run (`pytest tests --ignore=tests/e2e_pipeline`)
      matches the 13 pre-existing failures exactly with 29 more tests
      passing (new coverage), `plans/README.md` updated to DONE.
- [x] Commit plan 033 (f14862b, d5faba4 fix-up after subagent review caught
      a return-type regression).

## Plan 021 — Rebuild the publication callback contract (PARTIAL)

- [x] Recon: confirmed Steps 1-5 need coordinated backend+frontend work
      (see `plans/021/spec.md`) — landing backend-only would strand real
      callbacks, a regression not progress.
- [x] Step 0 (not an original plan step, required by its own STOP
      condition): fixed refinery_id identity resolution in
      `refinery_engine.py` (`_resolve_article_identity`).
- [x] Committed (3e3408e), `plans/README.md` updated to PARTIAL with full
      handoff including a dedup-guard hazard for whoever does Step 2.

## Plan 023 — Connect and harden the report pipeline (PARTIAL)

- [x] All 5 steps implemented + tested in the frontend repo (contract
      mapping, honest form behavior, request bounds, durable-sink
      tracking, KV rate limiting/idempotency, CI gates).
- [x] Committed in both repos (frontend dbb12db, backend index b8d84e0).
- [ ] Remaining: operator provisions R2 bucket + RATE_LIMIT_KV namespace,
      then flips `config.yaml`'s endpoint — see
      `../noticiencias/docs/report-pipeline-setup.md`.

## Plan 046 — Prove and automate production migrations

- [ ] Read `plans/046-prove-and-automate-production-migrations.md` in full.
- [ ] Implement per its spec.
- [ ] Run its verification section.
- [ ] Update `plans/README.md`, commit.

## Reassess after each completion

- [ ] After 033/021/023/046 each land, recompute the newly-startable set from
      `plans/README.md`'s dependency column (031/032 unblock after 023;
      034/036/037/038/048 unblock after 033; 041/043 need the full
      021+023+... set; 047 needs 021+023).
- [ ] Frontend plans (031, 032, 035, 039, 044) belong in the Astro repo
      (`noticiencias`), not here — flag when reached instead of implementing
      from this working directory.
- [ ] Spike plans (047, 048, 049) end in an ADR/decision doc, not shipped
      code — don't over-build.
- [ ] Every ~20 iterations: fresh subagent review of spec.md + implementation
      for gaps; loop on feedback.
