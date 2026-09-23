# Spec — Frontend Wave 2 contract mirror (P0-01 / P0-02 / P0-06)

Date: 2026-09-23
Frontend branch: `audit/wave-02-editorial-contract` (noticiencias repo)
Backend branch: `contract/wave2-editorial-mirror`

## Goals

Mirror the frontend Wave 2 schema additions in
`news_collector/contracts/frontend_schema.py` so both parity gates pass:

- frontend `npm run check:contract-sync --strict`
- backend `make test-contracts` (+ `test_frontend_schema_field_parity`)

Acceptance:

- `SourceItem` accepts optional `role` (`primary` | `secondary`) and
  optional `doi` matching `^10\.\d{4,}/.+`; malformed DOI rejected.
- `AstroPost` accepts optional `evidence_subject_type` (8-value enum) and
  optional `evidence_detail` (1–280 chars).
- `why_it_matters` capped at 3 items (frontend allows 0–3, DEC-003).
- Absent/legacy fields still validate (no backfill required).
- `docs/PIPELINE_CONTRACTS.md` documents the new producer-side fields.

## Non-goals

- No producer logic changes (no prompts, no enrichment, no backfill).
- No publication-identity changes (LAW-B5 untouched).

## Implementation

1. `SourceRole` + `EvidenceSubjectType` str enums in `frontend_schema.py`.
2. `SourceItem.role`, `SourceItem.doi` (pattern-validated).
3. `AstroPost.evidence_subject_type`, `AstroPost.evidence_detail`,
   `why_it_matters` `max_length=3`.
4. Extend `test_astro_post_serialization` coverage with the new fields.
5. Note in `docs/PIPELINE_CONTRACTS.md`.

## Verification

- `make test-contracts` (164+ tests, coverage gate 80%).
- `make lint` on the touched file (ruff/black via repo tooling).
- `make docs-check`.
- Frontend `npm run check:contract-sync` from the sibling repo.
- Targeted python check: valid mirror post parses; malformed DOI raises.
