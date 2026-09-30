# Spec — self-healing publication (preventive + corrective repair)

## Context

Run 59 (article 2671, 2026-09-30) reached the final frontend gate and died on
`check:tags`: the tag `ads/cft` contains `/`, which the frontend contract
(`^[a-z0-9áéíóúüñ\s]+$`) rejects. The backend had **already detected** the
invalid tag (`TagNormalizer.validate_tags` → "Tags require review:
['Invalid characters in tag: ads/cft']") but only logged it, wrote it anyway,
and failed 9 minutes later at the last gate — leaving the article stuck in
`publishing`, a local branch with no commit, and no PR. The same class of
failure had already happened with `h²maf` and `mit sa+p`.

## Goal

Make the publication pipeline **self-healing and self-corrective** in a
bounded, deterministic, observable way:

1. **Preventive repair** — mechanical sanitization enforces the cross-repo
   tag contract at generation time; invalid characters can no longer reach
   the written post.
2. **Corrective repair** — when the frontend validation still classifies a
   *mechanically repairable* failure (first strategy: tag charset), the
   workflow repairs the written post, re-runs validation once, and continues
   to commit/push/PR if green. Bounded, stage-recorded, deterministic.
3. **State resilience** — a clean pre-PR failure (write or validation) must
   not leave the article stuck in `publishing`; the workflow releases the
   article back to `completed` and closes the attempt row, so the next
   publish starts clean instead of hitting the crash-recovery path.

Non-goals: no LLM-driven repairs (non-deterministic, unbounded cost), no
retry loops (single repair attempt per phase), no frontend changes, no
auto-retry of whole runs.

## Architecture

### Layer 1 — Preventive: `taxonomy/normalizer.py`

`sanitize_tags` now runs a charset repair after `_basic_sanitize`: every
character that does not individually match the configured
`allowed_chars_regex` (default `^[a-z0-9áéíóúüñ\s]+$`, same contract as the
frontend) is replaced with a space, whitespace collapsed. Repairs are
recorded in `NormalizeResult.replaced` for audit. `validate_tags` remains the
invariant check.

### Layer 2 — Corrective: `validation/publication_repairs.py` (new, pure)

- `ContentRepair` dataclass: `content`, repaired `fields`, human
  `descriptions`.
- `repair_post_content(content, failure_class) -> ContentRepair | None`:
  registry of deterministic strategies keyed by `PublicationFailureClass`.
  First strategy `taxonomy_contract_violation`:
  parse frontmatter (yaml), sanitize `tags` with `TagNormalizer`, re-validate
  with `validate_tags` (only accept a strategy that restores the invariant),
  re-serialize frontmatter preserving body. Returns `None` when no strategy
  applies, nothing changed, or input is malformed — deployment never crashes
  on a repair attempt. Pure: no network, no DB, never raises on odd input.

### Layer 3 — Wiring: `logic/workflows/target_repo_publication.py`

- `_attempt_self_repair(request, output_filename, failure_class, record_stage)`:
  reads the written post, calls the pure repair, atomically writes it back,
  logs a warning and records stage `validation_self_repair`
  (`failure_class`, `fields`, `descriptions`). Returns whether a repair was
  applied.
- `_validate_post_frontend`: fast guard failure → one repair attempt →
  re-run fast guard; full validation failure → one repair attempt → re-run
  full validation. Only one repair per phase, then the outcome is final
  (LAW-B6/B7: explicit failure, never a hidden loop).
- `_release_publishing_state(request, deps, reason, failure_class=None)`:
  on pre-commit failure (writer `ValueError`, fast/full validation failure)
  calls `db.release_article_publishing(...)` when available; records stage
  `publishing_state_released`. PR-creation failures are deliberately
  excluded: once commit/push happened, the existing crash-recovery path
  owns the retry.

### Layer 4 — State: storage

- `article_repository.release_article_publishing(article_id, *, reason)`:
  restores `processing_status = "completed"` (the publishable state the
  article had when selected) and clears `publishing_started_at` /
  `publishing_branch` metadata. Idempotent; `False` when the article does
  not exist or is not publishing.
- `DatabaseManager.release_article_publishing(..., failure_class=None)`
  delegates and dual-writes the latest still-`PUBLISHING`
  `publication_attempts` row to `REJECTED` (`finished_at` on the row; the
  reason/failure class land on its `publication_events` audit row, which is
  where this state machine stores transition details), using the existing
  CAS transition — no new states, no new legal transitions.

## Files

- `news_collector/taxonomy/normalizer.py`
- `news_collector/validation/publication_repairs.py` (new)
- `news_collector/logic/workflows/target_repo_publication.py`
- `news_collector/storage/article_repository.py`
- `news_collector/storage/database.py`
- `docs/PIPELINE_CONTRACTS.md`
- Tests: `tests/unit/taxonomy/test_normalizer.py`,
  `tests/unit/validation/test_publication_repairs.py` (new),
  `tests/decompose_refinery/test_target_repo_publication.py`,
  `tests/unit/storage/test_article_repository_coverage.py` (or the closest
  existing storage suite)

## Acceptance

1. `sanitize_tags(["ads/cft", "h²maf", "mit sa+p"])` yields tags that all
   pass `validate_tags`; audit `replaced` records each fix; idempotent.
2. `repair_post_content` repairs `ads/cft` → `ads cft` in frontmatter,
   leaves body byte-identical, returns `None` for unknown classes / valid
   content / malformed frontmatter, and the repaired output passes
   `validate_tags`.
3. Workflow: full validation returns `taxonomy_contract_violation` →
   repair → re-validation green → commit/push/PR proceed; the stage
   `validation_self_repair` is recorded. If the second validation fails, the
   run fails with the second class and no commit.
4. Writer/validation failure after `mark_article_publishing` releases the
   article to `completed`, clears publishing metadata, closes the
   `PUBLISHING` attempt as `REJECTED`; PR-creation failure keeps the
   publishing state for recovery.
5. End-to-end regression: the exact run-59 shape (`ads/cft` tag) no longer
   blocks at the frontend gate.

## Verification

- `.venv/bin/python -m pytest tests/unit/taxonomy/test_normalizer.py tests/unit/validation/test_publication_repairs.py tests/decompose_refinery/test_target_repo_publication.py -q --no-cov`
- `make lint && make test`
- `make test-boundaries && make test-contracts`
- Coverage ratchet on the full run (92.87% vs 91.25% baseline).
- E2E `test_frontend_validation_failure_is_classified_for_taxonomy_and_permalink`
  updated: the repairable tag now produces a `validation_self_repair` stage and
  the run stops on what remains unrepairable (real frontend build →
  `frontend_build_failure`; mock fixture → `taxonomy_contract_violation`).
  Its timeout marker moved to 600 s because a repair re-runs the gate once.
- Manual replay: apply `repair_post_content` to the run-59 file (temp/target)
  and confirm tags pass `validate_tags`; optionally re-publish article 2671.

## Risks / notes

- Bounded: at most one repair per validation phase; a repair strategy is
  accepted only if the invariant check passes afterwards.
- YAML re-serialization is normalized by the frontend's prettier step
  (`format_post`) which runs again on the re-validation, so formatting is
  not a regression source.
- `completed` is the restore status because that is the publishable state
  candidates carry when selected (documented at the repository method).
