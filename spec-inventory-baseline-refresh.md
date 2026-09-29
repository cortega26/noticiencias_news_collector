# Spec: deliberate inventory baseline refresh (issue #345)

Status: in progress · 2026-09-29
Trigger: weekly audit issue #345 "Inventory drift detected" — 74 drift
lines / 17 changed keys between `audit/00_inventory.json` (generated
2026-09-21, commit `04bcdaa`) and a fresh run on `main` (`ed328d3`).

## Goal

1. Prove every drift entry maps to work already reviewed and merged
   between `04bcdaa..ed328d3` (issue window), not to local/untracked state.
2. If legitimate, deliberately refresh the committed baseline instead of
   fixing entries one by one.
3. Acceptance: after the refresh, the same generator+compare invocation
   reports `drift_count=0`; inventory tests pass; the refreshed baseline is
   byte-equivalent when regenerated from a clean checkout.

## Drift classification (all 74 lines)

Every changed path traces to a merged PR; none is untracked/local:

| Drift entry | Origin (merged) |
|---|---|
| `make_targets`: `serve`/`admin-dev`/`admin` descriptions | #321 (`c7f3fc1`, `f3d52da`) |
| `make_targets`: `admin-contracts-generate`, `admin-contracts-check` | #327 (`3944d6f`) |
| `markdown_files`: `docs/adr/0010-llm-routing.md`, `plans/080/tests/phase-2-results.md`, `reports/evaluation/llm-routing-2026-09.md` | #322, #327, #322 |
| `markdown_files`: `plans/060/phase-{5a,5b,5c,5d,5e,7a,7b,7c1,7c2,7c3,7c4}/*` (22 files) | #331–#336, #340–#343 |
| `markdown_files`: top-level `spec-*`/`todo-*` pairs (`admin-stack-ports`, `alt-text-brief-flow`, `collection-recovery-and-scoring`, `curation-desk-revamp`, `llm-routing-benchmark`, `oci-hosting-migration`) | #321, #320, #344, #318, #322/#324, #337 |
| `markdown_files`: `spec/frontend-wave2-contract-mirror.md`, `spec/frontend-wave3-contract-mirror.md` | #324, #325 |
| `top_level_inventory.scripts/`: `export_admin_openapi.py` (renamed from `generate_admin_openapi_snapshot.py`), `llm_routing_dataset.py`, `llm_routing_replay.py` | #327, #324/#322 |
| `top_level_inventory`: `.codacy.yaml` added, `.contract-snapshots/` removed | #327 — Phase 2 contracts supersede the Phase 0 snapshot script/artifact |
| `top_level_inventory.reports/`: `evaluation` child | #322/#326/#328 benchmark/evaluation outputs |

No file entered the snapshot from the local worktree: the generator lists
only `git ls-files` tracked paths, and a clean-checkout run at the same
commit is identical to the local run (`clean-checkout identical: True`).
Stale `.contract-snapshots/`/`generate_admin_openapi_snapshot` references
are historical plans or the frontend repo's own snapshot (sparse checkout
in `publication-smoke.yml`), not live backend dependencies.

## Implementation

- Regenerate `audit/00_inventory.json` with the CI-equivalent invocation:
  `python scripts/generate_inventory.py --sample-size 10`.
- Nothing else changes; no fix-up of individual entries.
- Add this spec plus `todo-inventory-baseline-refresh.md` so the new files
  are themselves part of the snapshot (they are committed together).

## Verification

```bash
# 1. Fresh generation + compare against the refreshed baseline → drift 0
python scripts/generate_inventory.py \
  --output /tmp/inventory.generated.json --sample-size 10 \
  --compare-to audit/00_inventory.json \
  --diff-output /tmp/inventory.diff --summary-output /tmp/inventory.summary.json

# 2. Unit tests for the generator (tracked-path filtering, determinism)
python -m pytest tests/test_generate_inventory.py -q

# 3. Clean-checkout equivalence (no workdir/runtime noise in baseline)
#    from a detached worktree of the commit with the same two new docs:
python scripts/generate_inventory.py --output /tmp/clean.json --sample-size 10
#    sanitized compare → identical
```

## Rollback

Revert the single `audit/00_inventory.json` refresh commit; the weekly
audit then reports the same 74-line drift until a new refresh lands.
