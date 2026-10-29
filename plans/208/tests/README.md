# Plan 208 verification record

## Environment and scope

- Isolated worktree: `/tmp/codex-wt-publish-image-20261029`
- Base SHA: `753ad7c3bc61ee06888ba5cb3b1e64867a0d8921`
- Python: `3.13.12`
- No credentials, external GitHub operations, PR creation, deployment, or live
  publication were used.
- The original checkout remained at `main` with its pre-existing
  `data/exports/latest_articles.json` and untracked `uv.lock` preserved. The
  article branch under `temp/target` also remained untouched with its modified
  hero image preserved.

## Results

- Focused command, including the publisher cleanup-cause regression and local
  bare-Git operational test:
  `python -m pytest -q --no-cov tests/unit/publishing/test_github_publisher_mock.py tests/unit/logic/workflows/test_refinery_engine.py tests/decompose_refinery/test_target_repo_publication.py tests/decompose_refinery/test_target_repo_writer.py tests/integration/test_publication_image_staging.py`
  Result: `172 passed`.
- `make verify-ci PYTHON=/home/carlos/.local/bin/python3.13`: passed after
  refreshing `audit/00_inventory.json` for the new plan artifacts. Results:
  4,608 unit tests passed / 5 skipped; 117 integration passed / 1 skipped;
  192 marked E2E passed; 14 pipeline E2E passed; 310 contracts passed; 3
  boundary tests passed. Lint, type, security, documentation, inventory,
  plan ledger, toolchain, lock parity, and import-linter checks passed.
- Security output: pip-audit found no known vulnerabilities; Bandit found no
  findings above HIGH; Gitleaks found no leaks.
- `make quality-gate PYTHON=/home/carlos/.local/bin/python3.13`: passed all
  three snapshots.
- `git diff --check`: passed.

The single integration skip and five unit skips require opt-in network or
external-model settings. They were not run. The local bare-Git operational
test verified a clean checkout at branch creation, then verified the pushed
local branch contains both the exact image bytes and the article.
