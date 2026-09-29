# Spec: internal adversarial review guardrails

Status: in progress · 2026-09-29
Trigger: PR #323 (`feat(review): internal adversarial guardrails`) — open
since 2026-09-22 with a failing Codacy check and three Codex P2 findings.

## Goal

Land the guardrails feature with its review findings resolved:

1. `docs/SELF_REVIEW_CHECKLIST.md` — findings distilled from real Codex
   rounds, mapped to deterministic vs judgment checks.
2. `scripts/adversarial_review.py` — unlimited offline reviewer on local
   Ollama with a closed-world rule; advisory (exit 0), not in CI.
3. `make review-local` + a PR-template checkbox.

## Fixes applied in this pass

Codacy (5 findings):

- `subprocess` import and partial executable path → explicit `# nosec B404`
  rationale and `shutil.which("git")` (full path), matching
  `scripts/generate_inventory.py`.
- `urlopen` audit → API scheme allowlist (`http`/`https` only) with a
  `# nosec B310` justification.
- `main` exceeded the 50-line / complexity-8 limits → extracted
  `build_parser`, `load_checklist`, `truncate_diff`, `emit_report`.

Codex P2s:

- **Working-tree coverage.** Default scope is now `git diff <ref>`
  (worktree vs ref, including staged and unstaged edits); `--staged`
  remains index-only. Previously `git diff <ref>...HEAD` silently ignored
  pending edits.
- **Path filter parity.** The `--name-only` file list now receives the same
  `--` `*paths` filter as the patch, so scoped reviews no longer claim
  files that were never shown.
- **Truncated diffs.** Truncation is surfaced: a stderr warning, an
  `INCOMPLETE REVIEW` banner prepended to the report, and an `INCOMPLETE
  INPUT` instruction telling the model not to issue a merge verdict and to
  name what it could not examine (computed from the missing `diff --git`
  sections).

## Tests

`tests/scripts/test_adversarial_review.py` (12 cases): default vs staged
scope, path filter on both commands, hunk-boundary truncation, omitted-file
detection, incomplete prompt/report, API scheme rejection, empty-diff and
complete-review paths.

## Verification

```bash
.venv/bin/python -m pytest tests/scripts/test_adversarial_review.py -q
make lint && make type && make test && make test-boundaries
python scripts/check_doc_drift.py
make inventory-refresh && make inventory-check   # new spec/todo pair
make review-local ARGS="--print-prompt"          # manual smoke (local Ollama)
```

## Out of scope

- Running the reviewer in CI (needs the 50GB model; advisory by design).
- Auto-chunking very large diffs (explicit incomplete result instead).
