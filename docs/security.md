# Security automation overview

The Noticiencias stack runs proactive dependency and source-code scanning so that high severity risks are surfaced without manual babysitting. This page documents how the automation behaves and how operators should react when it fires.

## Pull request security gate

The [`Security gate`](../.github/workflows/audit-security.yml) workflow runs on every push and pull request. It keeps the following checks blocking merges:

1. `bandit -ll -r src core scripts noticiencias run_collector.py main.py -v -f json -o reports/security/bandit.json`
2. `gitleaks detect --source . --no-banner --redact --config=.gitleaks.toml --report-format json --report-path reports/security/gitleaks_report.json`
3. `pip-audit -r requirements.lock -r requirements-security.lock --ignore-vuln GHSA-q2x7-8rv6-6q7h --ignore-vuln GHSA-gmj6-6f8f-6699 --ignore-vuln GHSA-cpwx-vrp4-4pq7 -f json -o reports/security/pip_audit.json`

The ignore list captures the three GHSA advisories currently pinned by `trufflehog3`. Track mitigation status in `audit/07_security_report.md` and remove the overrides once an upstream fix ships.

Artifacts are uploaded on failure so reviewers can inspect the JSON evidence. Fix or triage findings locally with `make security` before retrying the workflow.

## Weekly security workflow

The [`Scheduled security scan`](../.github/workflows/security.yml) GitHub Actions workflow executes every Monday at 06:00 UTC and can also be triggered manually via the *Run workflow* button. The job performs the same steps used in the main CI pipeline:

1. Checks out the repository and provisions Python 3.12 with cached dependencies.
2. Executes `make security`, which chains the following scanners:
   - [`pip-audit`](https://github.com/pypa/pip-audit) against `requirements.txt`.
   - [`bandit`](https://github.com/PyCQA/bandit) over `src/` and `scripts/` with the project ruleset.
   - `trufflehog3` secret scanning via `scripts/run_secret_scan.py` and `.gitleaks.toml`.
3. Uploads `reports/security/` as a workflow artifact whenever the scan fails so responders can download the JSON evidence.

> The scheduled and PR-triggered workflows share the same allowlist defined in [`.gitleaks.toml`](../.gitleaks.toml). Documented historical false positives are tracked there; new ones should be justified in `audit/07_security_report.md` before suppression.

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
