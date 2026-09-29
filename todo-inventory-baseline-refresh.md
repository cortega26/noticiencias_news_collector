# Todo: deliberate inventory baseline refresh (issue #345)

Execution index for [`spec-inventory-baseline-refresh.md`](spec-inventory-baseline-refresh.md).

## Evidence

- [x] Reproduced issue #345 locally: `drift_count=74`, 17 changed keys,
      baseline `generated_at=2026-09-21T01:59:53Z` (`04bcdaa`), HEAD `ed328d3`.
- [x] Mapped every changed path to a merged PR in `04bcdaa..HEAD`
      (#303–#344); all 39 referenced PRs are `MERGED`.
- [x] Verified generator uses `git ls-files` only → no untracked/local file
      can leak into the snapshot; local run == clean-checkout run.
- [x] Checked suspicious entries: `.codacy.yaml` (Codacy generated-code
      exclusion, #327) and `.contract-snapshots/` removal (superseded by
      `export_admin_openapi.py`, #327) are intentional and documented.

## Refresh

- [x] Write spec + todo (this pair) and stage them
- [x] Regenerate `audit/00_inventory.json` with `--sample-size 10`
- [x] Confirm `drift_count=0` against the refreshed baseline
- [x] `pytest tests/test_generate_inventory.py` green (5 passed)
- [x] Clean-checkout sanitized compare identical (`True`)
- [x] `make lint` green
- [x] Commit / push / open PR closing issue #345 (dedicated branch, PR-only)
