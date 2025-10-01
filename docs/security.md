# Security automation overview

The Noticiencias stack runs proactive dependency and source-code scanning so that high severity risks are surfaced without manual babysitting. This page documents how the automation behaves and how operators should react when it fires.

## Weekly security workflow

The [`Scheduled security scan`](../.github/workflows/security.yml) GitHub Actions workflow executes every Monday at 06:00 UTC and can also be triggered manually via the *Run workflow* button. The job performs the same steps used in the main CI pipeline:

1. Checks out the repository and provisions Python 3.12 with cached dependencies.
2. Executes `make security`, which chains the following scanners:
   - [`pip-audit`](https://github.com/pypa/pip-audit) against `requirements.txt`.
   - [`bandit`](https://github.com/PyCQA/bandit) over `src/` and `scripts/` with the project ruleset.
   - `trufflehog3` secret scanning via `scripts/run_secret_scan.py` and `.gitleaks.toml`.
3. Uploads `reports/security/` as a workflow artifact whenever the scan fails so responders can download the JSON evidence.

The helper script [`scripts/security_gate.py`](../scripts/security_gate.py) enforces a **HIGH** severity threshold for every tool. If any scanner reports a HIGH (or higher) finding, the workflow exits non-zero and the GitHub status is marked as failed. Address the finding, regenerate the reports locally with `make security`, and re-run the workflow to confirm the fix.

## Dependency monitoring

Automated dependency updates are configured through [Dependabot](../.github/dependabot.yml). Every Monday at 06:00 UTC it scans all `pip` ecosystems in the repository, including:

- Root `requirements*.txt` manifests.
- The `pyproject.toml` build metadata.

Dependabot raises `chore:`-prefixed pull requests for the affected manifest and relies on the existing CI pipeline to validate compatibility before merging.

## Responding to alerts

1. Download the latest `security-reports` artifact from the failing workflow run for detailed findings.
2. Prioritize HIGH severity items. Use the JSON payload to locate the vulnerable package, file, or secret.
3. Implement the fix (e.g., upgrade the dependency, suppress a false positive in `.gitleaks.toml`, or remediate the vulnerable code).
4. Run `make security` locally to confirm the pipeline passes.
5. Push the fix and re-run the scheduled workflow (or wait for the next schedule) to clear the alert.

Keeping the scheduled scan and Dependabot PRs green ensures our SBOM stays current and no known HIGH severity issues reach production.
