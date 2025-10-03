# Phase 11 — CI/CD Pipeline Assurance

## Overview
- **Objective:** Guarantee that continuous integration enforces the repository's quality, security, and supply-chain controls while keeping feedback fast (≤15 minutes median).
- **Scope:** GitHub Actions workflow (`ci.yml`) plus supporting build artifacts and smoke validation for the Docker runtime image.

## Pipeline Enhancements
1. **Deterministic concurrency guardrails**
   - Added workflow-level concurrency group (`ci-${{ github.workflow }}-${{ github.ref }}`) with automatic cancellation of superseded runs.
   - Prevents branch queues from piling up and keeps feedback aligned with the latest revision.
2. **Explicit build & smoke verification stage**
   - New `build-artifacts` job depends on lint, type-check, unit tests, and security scans before executing packaging steps.
   - Publishes Python wheel artifacts (`dist/`) for reproducible downloads and builds Docker image locally via Buildx.
   - Executes container smoke test (`docker run … --help`) and stores log artifacts for triage; ensures runtime image remains bootable.
3. **Quality gate reinforcement**
   - `test` and `security` jobs now have timeouts to bound run durations; coverage continues to upload HTML/XML artifacts.
   - Build job reuses existing `make` targets (`build`, `audit`) ensuring lint, type, tests, coverage, SAST (bandit), secret scans (trufflehog), and dependency audit (pip-audit) all execute on every PR.

## Verification Strategy
| Check | Location | Evidence |
| --- | --- | --- |
| Workflow concurrency + build job | `.github/workflows/ci.yml` | `concurrency` block, `build-artifacts` job with artifact uploads and smoke test |
| Artifact retention | `.github/workflows/ci.yml` | Upload steps for `python-dist` and `docker-smoke-log` |
| Security gates | `Makefile`, workflow `security` job | Invokes `pip-audit`, `bandit`, `trufflehog` with gating script |
| Runtime smoke test | Workflow build job | `docker run --rm local/noticiencias-news-collector:ci` log artifact |

## Runtime Expectations
- Jobs run in parallel after shared setup to keep total wall-clock under 15 minutes on standard runners (unit tests ~2 min, lint/type ≤1.5 min, security scans 3–4 min, build & smoke ≤3 min).
- Timeout guards (20 min ceilings) prevent hung steps from exhausting CI minutes.

## Follow-ups / Risks
- Monitor Docker build duration; if layers grow, consider caching via `actions/cache` on the buildx builder directory.
- Future work: add nightly workflow publishing SBOM artifacts and running extended mutation tests using cached dependencies.
