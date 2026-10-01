# TODO — self-healing publication

- [x] `TagNormalizer`: charset repair in `sanitize_tags` (+ `replaced` audit)
- [x] Unit tests: normalizer charset matrix, idempotency, validate-green
- [x] `validation/publication_repairs.py`: `ContentRepair`, registry, tag strategy
- [x] Unit tests: repair matrix (slash/plus/superscript, body preserved,
      unknown class, malformed, invariant restored)
- [x] `target_repo_publication`: `_attempt_self_repair` + one-per-phase loop
- [x] `target_repo_publication`: `_release_publishing_state` on pre-commit failures
- [x] `article_repository.release_article_publishing` + `DatabaseManager` dual-write
- [x] Tests: repair loop (success/bounded failure), release on write/validation
      failure, no release on PR failure
- [x] Storage tests for release (restore status, clear metadata, CAS attempt)
- [x] Docs: `PIPELINE_CONTRACTS.md` self-corrective section; taxonomy README
- [x] Gates: lint, test (3466 passed), test-boundaries, test-contracts
- [x] Live replay: run-59 artifact repaired (`ads/cft` -> `ads cft`, body
      identical, invariant green)
- [x] Live state heal: article 2671 released to `completed`, attempt 15
      `REJECTED`, publishing metadata cleared
- [x] Full coverage + ratchet (92.87% vs 91.25%, changed files passed)
- [x] e2e taxonomy/permalink scenario updated for the self-repair behavior
      (asserts the repair stage + the remaining classified failure); green
- [x] Inventory refresh after staging the new files (spec/todo, module, tests)
      — verified 2026-09-30: inventory lists `publication_repairs.py` and both
      docs; `make inventory-check` clean
- [x] User re-publishes article 2671 (live proof of the full pipeline) — done
      2026-09-30: run 61 refined 2671 with the tag self-repair, opened frontend
      PR #231 (merged), Pages deploy green; article live at
      `https://noticiencias.com/ciencia/2026-09-25-la-gravedad-como-proyector-holografico-del-universo/`;
      local attempt 16 completed via the replayed `publish_complete` callback
      (see ADR-0011 for the local↔hosted state split found while verifying)
