# Continuous Integration

The CI system is designed to keep the feedback loop under 15 minutes while enforcing security and quality gates.

## Required status checks

| Name | Type | Default | Required | Description |
| --- | --- | --- | --- | --- |
| `test` | GitHub Actions job | PR & push | ✅ | Runs the unit suite under `pytest` with coverage reporting enabled. |
| `coverage` | GitHub Actions job | PR & push | ✅ | Downloads coverage artifacts and enforces the ratchet via `scripts/coverage_ratcheter.sh`. |
| `bandit` | GitHub Actions job | PR & push | ✅ | Executes Bandit with high-severity rules and blocks regressions through `scripts/security_gate.py`. |
| `gitleaks` | GitHub Actions job | PR & push | ✅ | Scans the repository for committed secrets using the repo’s `.gitleaks.toml`. |
| `pip-audit` | GitHub Actions job | PR & push | ✅ | Audits both runtime and security lock files for known vulnerabilities. |
| `docs/linkcheck` | GitHub Actions job | PR & push (docs scope) | ✅ | Validates README and `docs/` hyperlinks with `linkchecker`. |
| `healthcheck` | GitHub Actions job | PR & push | ✅ | Launches the collector health check (`run_collector.py --healthcheck`). |

> These checks should be marked as “Required” in the branch protection rules for `main`.

## Caching and concurrency

- Every Python job restores the `.venv` directory from an `actions/cache` key derived from `requirements.lock` and `requirements-security.lock`. Bootstrap is still invoked, but it becomes a no-op for cache hits, cutting setup to seconds.
- Workflows (`ci`, `docs`, `security`, and the weekly inventory audit) use `concurrency` blocks so that new pushes cancel superseded runs on the same ref.
- Artifact-heavy jobs (`test`, `coverage`, `bandit`, `gitleaks`, `pip-audit`, and `build-artifacts`) upload reports that downstream tooling consumes.

## Weekly inventory automation

The `audit inventory weekly` workflow regenerates `audit/00_inventory.json` using `scripts/generate_inventory.py`. If the sanitized snapshot drifts from the committed baseline, the workflow:

1. Uploads the generated JSON, diff, and summary as artifacts.
2. Opens (or comments on) an “Inventory drift detected” issue that summarizes the changes.

To run the same check locally:

```bash
python scripts/generate_inventory.py \
  --output reports/audit/00_inventory.generated.json \
  --compare-to audit/00_inventory.json \
  --diff-output reports/audit/00_inventory.diff \
  --summary-output reports/audit/00_inventory.summary.json
```

Review the diff and update `audit/00_inventory.json` when intentional changes occur.
