# Todo: Refinery GUI — source editor (Phase 4 addendum)

Status: `[ ]` pending · `[x]` done · `[~]` in progress

## Contract

- [x] `AdminSourceUpsert` in contracts/admin.py (fields + validation + category/freq literals)

## API

- [x] `POST /v1/admin/sources` — upsert (merge preserves existing keys; create seeds defaults; yaml + DB)

## Repository

- [x] `SourceRepository.upsert_source` (or reuse initialize_sources path)

## API tests

- [x] create (yaml + DB + defaults)
- [x] update preserves existing keys
- [x] validation 422s (missing name/url, bad category, bad range)

## GUI

- [x] Client `upsertSource` + types + vitest
- [x] Sources page: Add source button + inline editor; Edit per row

## Validation

- [x] Backend gates: lint, type, test, test-contracts, test-boundaries
- [x] Admin gates: admin-test, admin-build
- [x] Live browser e2e (add → edit → delete round-trip)
- [x] Commit + push
