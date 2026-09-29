# Todo: internal adversarial review guardrails

Execution index for [`spec-internal-review-guardrails.md`](spec-internal-review-guardrails.md).

## Findings resolved

- [x] Codacy B404/B607: `# nosec` rationale + `shutil.which("git")` full path
- [x] Codacy B310: API scheme allowlist + `# nosec` justification
- [x] Codacy complexity: `main` split into focused helpers
- [x] Codex P2: default scope includes the working tree (`git diff <ref>`)
- [x] Codex P2: `--paths` also filters the changed-file list
- [x] Codex P2: truncated diff → explicit `INCOMPLETE REVIEW` result
- [x] Tests: `tests/scripts/test_adversarial_review.py` (12 cases)

## Verification

- [ ] Targeted pytest green
- [ ] `make lint` + `make type` green
- [ ] `make test` + `make test-boundaries` green
- [ ] `check_doc_drift` green
- [ ] Inventory baseline refreshed (new spec/todo pair)
- [ ] `make review-local ARGS="--print-prompt"` smoke on the local diff

## Delivery

- [ ] Commit and push to `feat/internal-review-guardrails` (updates PR #323),
      confirm Codacy turns green, merge
