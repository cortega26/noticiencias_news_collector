# Spec: self-healing inventory baseline

Status: in progress · 2026-09-29
Trigger: issue #345 (74-line inventory drift). The manual refresh (PR #346)
clears the backlog, but nothing prevents the same class of drift from
recurring: any merged PR that adds/removes top-level files, markdown files,
Make targets or dependency entries silently ages the committed baseline
until the weekly audit opens another issue.

## Goal

Make the inventory baseline self-correcting so the weekly audit stays quiet
in normal operation, and only raises an issue when the healing path itself
fails.

Acceptance criteria:

1. On a weekly cadence (and on demand), drift is healed by an automated
   commit that touches only `audit/00_inventory.json`.
2. The weekly audit remains an independent detector/alarm; it opens or
   comments an issue only when no heal landed.
3. Any open "Inventory drift detected" issue is closed automatically once
   the baseline is current again.
4. Local parity: `make inventory-check` fails with an actionable message on
   drift; `make inventory-refresh` regenerates the baseline; both are wired
   into `make verify-ci`.
5. No new PR-time friction: authors never have to refresh the baseline by
   hand (the baseline has no other consumer, so a PR gate would only add
   noise to every inventory-touching PR).

## Design

### Layers

| Layer | Mechanism | Cadence | Failure mode |
|---|---|---|---|
| Heal | `.github/workflows/inventory-autorefresh.yml` regenerates and pushes `audit/00_inventory.json` (path-limited add) | Mondays 05:00 UTC + `workflow_dispatch` | Push/commit fails → job red; next weekly audit opens the issue (alarm) |
| Detect | `audit-inventory-weekly.yml` (unchanged) compares and opens/comments the issue | Mondays 06:00 UTC | Issue stays open until a heal lands; autorefresh closes it |
| Local | `make inventory-check` (`--fail-on-drift`) / `make inventory-refresh` | on demand | Developer/agent gets an actionable message |

### Decisions

- **No PR gate.** The baseline is an audit artifact with no consumer; gating
  it would force a baseline hunk into nearly every PR (any `.md` addition),
  trading a weekly alarm for per-PR noise. Healing is deferred to the
  scheduled workflow instead.
- **Heal before detect.** Autorefresh at 05:00 runs one hour before the
  06:00 audit, so normal-operation drift never reaches the detector.
- **Path-limited commit.** The healer stages only `audit/00_inventory.json`,
  so an unexpected file can never ride along into the auto-commit. The
  snapshot only catalogs already-tracked files; unexpected files were
  already merged by their own PR.
- **GITHUB_TOKEN push, no loops.** Pushes made with the default token do not
  trigger new workflow runs, so the auto-commit cannot re-enter the push
  workflows. No PAT/secrets required.
- **Retry on race.** Three attempts: `fetch origin main` → `checkout -B` →
  regenerate → amend → push; concurrent merges during the run are absorbed.
- **Independent alarm kept.** The audit workflow is not folded into the
  healer: if the healer breaks (permissions, disabled workflow, API outage)
  the audit still opens the issue.
- `docs/ci.md` guidance "run a new gate report-only first" is satisfied
  without a report-only phase: the full backlog was triaged in #346, and the
  local gate only fails on drift introduced by the current worktree.

## Implementation

- `scripts/generate_inventory.py`
  - `--fail-on-drift` (exit 1 + stderr message pointing to
    `make inventory-refresh`).
  - Missing `--compare-to` baseline fails when the flag is set instead of
    silently reporting zero drift.
- `Makefile`
  - `inventory-refresh` — regenerate `audit/00_inventory.json`.
  - `inventory-check` — CI-equivalent check with `--fail-on-drift`.
  - `verify-ci` composition gains `inventory-check`.
- `.github/workflows/inventory-autorefresh.yml` (new)
  - Schedule Mon 05:00 UTC + dispatch; `contents: write`, `issues: write`.
  - Regenerate; if diff: commit and push to `main` (retry loop).
  - Close open drift issues via `github-script` when the baseline is
    current, with a comment naming the heal commit when one was pushed.
- `tests/test_generate_inventory.py`
  - `--fail-on-drift` exits 1 on drift, 0 on current baseline, 1 on missing
    baseline.
- Docs: `docs/ci.md` (workflow + gate), `AGENTS.md` (quick reference),
  `docs/AGENTS.md` §5 (validation bullet).
- Refresh `audit/00_inventory.json` in this PR (dogfooding: it must include
  the new Make targets and this spec/todo pair).

## Verification

```bash
# Gate semantics
python -m pytest tests/test_generate_inventory.py -q          # 5 + 3 tests pass

# Current baseline passes; drifted baseline fails with the remedy message
make inventory-check
# Simulate heal: touch a tracked markdown file count without refreshing
# (add a new tracked .md, then) => inventory-check exits 1

# Self-heal behavior (local simulation of the workflow body)
python scripts/generate_inventory.py --output audit/00_inventory.json --sample-size 10
git diff --quiet -- audit/00_inventory.json && echo "heal idempotent"

# Docs
python scripts/check_doc_drift.py
make lint
```

CI evidence after merge: one dispatch of `inventory autorefresh` (Actions →
Run workflow) shows either "No drift" or the heal commit, and the weekly
audit stops opening new issues.

## Post-merge correction (2026-09-29)

The first live dispatch (run 36576354585) exposed a defect in the heal step:
it decided with a textual `git diff` on the regenerated JSON, but
`generated_at` changes on every run, so the diff was never empty. The healer
pushed a timestamp-only commit (`b568a47`) with semantic drift 0.

Fix (same workflow file): compare through the script's sanitized output
(`--compare-to` + `--summary-output`, `drift_count`), copy the generated file
only when `drift_count > 0`, and rebuild the commit from fresh `origin/main`
on every retry instead of amending a stale tree. The local simulation now
covers three branches: stale-timestamp with zero semantic drift (exit 0, no
commit), real drift (commit + push), and a lost push race (retry heals).
