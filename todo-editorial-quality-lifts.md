# Todo — Editorial quality lifts (no model change)

Follows `spec-editorial-quality-lifts.md`. Branch `bench/editorial-quality-lifts`.
No production routing changes; no merges (PR without merge).

## Setup

- [x] Worktree at `origin/main` (`/tmp/q-lifts`), clean base verified
- [x] Relevant code mapped (validation=pre-filter, editorial=pure policy,
      critic gate/stages/headline/enrichment seams, refinery advisory wiring)

## Implementation

- [x] L1 critic verdict provenance (stage-4 cache-hit records verdict)
- [x] L2 limitations cue (editor prompt, preprint + animal-model)
- [x] L3 voice-tic lint module + ai_editor/refinery advisory wiring + tests
- [x] L4 health guarantee-language module + wiring + tests
- [x] L5 headline exhaustion structured event + test
- [x] L6 enrichment single retry on total-failure path + test

## Verification

- [x] New unit tests pass; fail-without-change sanity
- [x] `make lint && make type && make test`
- [x] `make test-boundaries`
- [x] `make quality-gate`
- [ ] `make inventory-check` (refresh if stale)
- [ ] Open PR without merging
