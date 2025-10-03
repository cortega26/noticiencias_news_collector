# Phase 7 — Security & Attack Surface

## Summary
- Executed the mandated Bandit, Gitleaks, and pip-audit sweeps with high verbosity and stored JSON artifacts under `reports/security/`.
- Verified the codebase avoids `shell=True`, `eval`, or `exec` patterns and that external inputs are validated via existing schema tooling.
- Hardened the container image to run as a non-root user on a pinned Python 3.11.9 base and ensured dependency installs remain hash-locked.
- Added an always-on GitHub Actions security gate so pull requests cannot merge while static analysis or secret scans fail.
- Documented the residual false-positive secret detections and mapped mitigations against OWASP ASVS controls for the CLI/data pipeline.

## Tooling Results
| Tool | Command | Outcome | Evidence |
| --- | --- | --- | --- |
| Bandit | `bandit -ll -r src core scripts noticiencias run_collector.py main.py -v -f json -o reports/security/bandit.json` | ✅ No issues identified | `reports/security/bandit.json` and console summary (chunk `f98d80`). |
| Gitleaks | `gitleaks detect --source . --no-banner --redact --config=.gitleaks.toml --report-format json --report-path reports/security/gitleaks_report.json` | ⚠️ Legacy commits surface three generic token false positives; allow-listed in `.gitleaks.toml`. | `reports/security/gitleaks_report.json`. |
| pip-audit | `pip-audit -r requirements.lock -r requirements-security.lock --ignore-vuln GHSA-q2x7-8rv6-6q7h --ignore-vuln GHSA-gmj6-6f8f-6699 --ignore-vuln GHSA-cpwx-vrp4-4pq7 -f json -o reports/security/pip_audit.json` | ✅ No unmitigated vulnerabilities reported (accepted risk tracked as R-07-004). | `reports/security/pip_audit.json`. |

> Note: `pip-audit` fails when pointed at `requirements.txt` because the manifest contains hashed dependencies without explicit hashes for transient wheels (e.g., `feedparser==6.0.12`). Using the compiled lockfiles keeps the scan reproducible while satisfying the `--require-hashes` policy enforced in CI.

## Risk Register
| ID | Risk | Severity | Status | Mitigation |
| --- | --- | --- | --- | --- |
| R-07-001 | Container image previously ran as `root`, increasing privilege escalation blast radius. | Medium | **Mitigated** | Dockerfile now creates and switches to `app` user after dependency installation while keeping hash-locked installs. |
| R-07-002 | Gitleaks flags `ENRICHMENT_MODEL_KEY` enumerations and TOML serialization helpers as generic tokens in historic commits. | Low | **Accepted (documented)** | Added offending commits to `.gitleaks.toml` allowlist and confirmed no secrets exist in the current tree; keep monitoring new detections. |
| R-07-003 | Dependency drift may reintroduce CVEs between scheduled scans. | Medium | **Mitigated** | Introduced push/PR security gate workflow executing Bandit, Gitleaks, and pip-audit on every change; scheduled weekly job remains as secondary net. |
| R-07-004 | `trufflehog3==3.0.10` pins `jinja2==3.1.4`, which carries GHSA-q2x7-8rv6-6q7h / GHSA-gmj6-6f8f-6699 / GHSA-cpwx-vrp4-4pq7 advisories. | Medium | **Accepted (compensating controls)** | No patched trufflehog3 release exists yet; CI pip-audit run ignores the three GHSA identifiers and risk is tracked here until upstream relaxes the pin or we replace the scanner. |

## Hardening Notes
- Reviewed Dockerfile for secret leakage, cache busting, and reproducibility. The new image pins `python:3.11.9-slim`, uses non-root execution, and preserves `PYTHONPATH=/app/src` for runtime. No build-time secrets are cached.
- Repository search confirmed absence of `shell=True`, dynamic `eval`, or `exec` usage in production code paths.
- Configuration updates continue to flow through `noticiencias.config_manager.Config` models, which enforce type validation and drop unset fields before serialization, preventing injection of unvalidated values into TOML outputs.

## OWASP ASVS Mapping Snapshot
Detailed control-by-control status lives in [`audit/07_asvs_checklist.md`](07_asvs_checklist.md). Highlights:
- **V1 Architecture**: Threat-aware documentation and CI guardrails keep the pipeline inventory current.
- **V10 Malicious Code**: Bandit, pip-audit, and gitleaks now gate merges for static analysis coverage.
- **V14 Configuration**: Hash-locked dependency installation and config schema validation prevent insecure defaults from shipping.

## Next Steps
1. Extend `.gitleaks.toml` regex allowlists if future audit documents enumerate placeholder secrets to avoid recurring false positives.
2. Add integration tests covering configuration write paths to ensure TOML serialization stays guarded against injection attacks.
3. Evaluate container image signing (e.g., Cosign) once the CI gate has stabilized to guarantee artifact provenance downstream.
