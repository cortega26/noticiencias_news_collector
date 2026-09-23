# Spec — Frontend Wave 3 contract mirror (P0-03 / P0-09 / P2-02 / P2-07)

Date: 2026-09-23
Frontend branch: `audit/wave-03-evidence-accountability` (noticiencias repo)
Backend branch: `contract/wave3-accountability-mirror`

## Goals

Mirror the frontend Wave 3 schema additions in
`news_collector/contracts/frontend_schema.py` so both parity gates pass:

- frontend `npm run check:contract-sync --strict`
- backend `make test-contracts` (+ `test_frontend_schema_field_parity`)

Acceptance:

- `AstroPost` accepts optional `institution` (1–160), `publication_status`
  enum, `reviewer_name`/`reviewer_role` (1–120), `reviewer_profile_url`,
  `review_date` (YYYY-MM-DD), `known_points`/`open_questions` (≤3),
  `corrected_at` (YYYY-MM-DD) + `correction_summary` (1–500).
- Half-correction (one of the pair without the other) raises.
- Legacy payloads without the new keys still validate.
- `docs/PIPELINE_CONTRACTS.md` documents the producer-side fields.

## Non-goals

- No producer logic changes (no prompts, no enrichment, no backfill).
- No publication-identity changes (LAW-B5 untouched).

## Verification

- `make test-contracts`, ruff/black on touched files, `make docs-check`.
- Frontend `npm run check:contract-sync` from the sibling repo.
