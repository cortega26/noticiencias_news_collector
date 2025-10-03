# Phase 12 — DX & Maintainability Checklist

## Scope & Highlights
- Tightened shared formatting/type tooling via `pyproject.toml` with Ruff/Black/isort convergence and stricter mypy defaults for the actively typed modules.
- Added project-wide pre-commit automation (formatters, mypy, API docs regeneration) plus refreshed contributor docs and issue/PR templates.
- Automated API reference generation with `scripts/generate_api_docs.py`, using the repo virtualenv for dependency-aware builds.

## Completed Items
- [x] Ruff/Black/isort aligned on 88 char width; repo formatting normalized.
- [x] Incremental mypy enforcement on `scripts/generate_api_docs.py`, `src/utils/logger.py`, and `src/utils/url_canonicalizer.py` with strict optional checks.
- [x] Pre-commit now runs Ruff, Black, isort, mypy, large-file/merge checks, and API doc generation.
- [x] README + CONTRIBUTING updated with lint/type/test workflow; templates created under `.github/`.
- [x] API docs regenerated into `docs/api/`.

## Outstanding / Follow-ups
- [ ] Expand mypy coverage beyond the currently whitelisted modules; remove `ignore_errors` overrides incrementally (collectors, storage, scoring, serving, tests, etc.).
- [ ] Audit doc build to ensure optional dependencies (e.g., NLP/ML extras) are installed in CI runners before enabling stricter import resolution.
- [ ] Consider shrinking generated `docs/api/` artifacts or switching to CI-generated previews if repo size becomes a concern.
- [ ] Evaluate warning noise in pytest run (deprecated BeautifulSoup `.find_all(text=...)`, SQLAlchemy 2.0 migrations) and plan remediation.

## Verification Evidence
- Pre-commit (ruff/black/isort/mypy/pdoc) `./.venv/bin/pre-commit run --all-files` (pass).
- Type checking `make typecheck` (strict modules only).
- Tests `./.venv/bin/pytest` (145 passed, warnings noted).
- SAST `./.venv/bin/bandit -ll -r src scripts -f json -o reports/bandit-report.json` (0 findings).
- Secret scan `/tmp/gitleaks detect --source . --report-format json --report-path reports/gitleaks-report.json` (0 leaks).
- Dependency audit `./.venv/bin/pip-audit -r requirements.txt -f json -o reports/pip-audit.json` (no known vulnerabilities).

## Open Questions
- Do we want to gate doc generation on a lighter stub set (mock heavy external services) to shorten hook runtime?
- Missing: confirmation that GitHub-side issue/PR template rendering matches design expectations (requires portal check).
