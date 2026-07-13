# Spec: Sequential implementation of plans 001-010

## Goals

- Implement the fixes in `plans/` one at a time, following their documented order and STOP conditions.
- Verify targeted behavior and required regression gates after every plan before starting the next.
- Keep each change within the scope and architectural boundaries defined by `docs/AGENTS.md`.
- Record plan status accurately, including operator actions or residual risks that cannot be completed in code.

## Completed: Plan 001

### Scope

- Blank `github.token` and `nvidia.api_key` in `config.toml` without changing any other configuration.
- Document the existing `GITHUB_TOKEN` environment alias in `.env.example`.
- Keep the existing NVIDIA nested environment variable documentation unchanged.
- Update `plans/README.md` with implementation status and the required credential-rotation warning.

### Design decisions

- Reuse the existing layered configuration loader; no Python code changes are needed.
- Do not rewrite git history or rotate credentials. Those are operator actions.
- Treat the code/config portion as complete only after config loading, environment override, and lint checks pass.

## Verification

- Confirm no `ghp_` or `nvapi-` secret remains in `config.toml`.
- Confirm the two config values are exactly empty strings.
- Run the dummy NVIDIA environment override snippet and require `RESOLVED`.
- Run `make config-validate` and `make lint`.
- Inspect the diff to ensure no secret value is exposed and no unrelated source file changed.

## Current implementation: Plan 002

### Scope

- Remove the wall-clock fallback from the filesystem recovery branch in `PublicationIdentityResolver.resolve()`.
- Raise a clear `ValueError` when a recovered filename lacks a parseable `YYYY-MM-DD-` prefix.
- Preserve dated filesystem recovery and the creation-mode clock behavior.
- Add regression tests for both malformed and well-formed recovered filenames.

### Design decisions

- The resolver's existing DB interface exposes canonical slugs but no stored article dates.
- The supplied article payload is not a guaranteed persisted-date contract, and `_derive_date()` deliberately uses the current publication date.
- Failing before `backfill_slug()` is safer than persisting a malformed canonical identity.

### Verification

- Run the focused publication identity tests.
- Confirm the only remaining `datetime.now` use is in Priority 3 creation mode.
- Run `make lint`, `make type`, `make test`, `make test-boundaries`, and `make quality-gate` because this changes workflow and publication identity behavior.

### Verification result

- Focused identity tests: 27 passed.
- `make lint`: passed.

## Follow-up: resolve Plan 007 blocker

- Preserve the baseline wheel package roots: `news_collector`, `noticiencias`, and `scripts`.
- Add explicit setuptools package discovery in `pyproject.toml` so flat-layout auto-discovery is no longer required.
- Delete the divergent `setup.py`; do not change dependency pins or lockfiles.
- Verify the rebuilt wheel has the same package roots and version, then run public entrypoint tests and lint.

### Verification result

- Baseline and rebuilt wheel version: `1.3.3`.
- Rebuilt wheel roots match the baseline: `news_collector`, `noticiencias`, and `scripts`.
- `setup.py` is absent and no project code imports `aiohttp`.
- Python-version metadata test now reads the canonical `pyproject.toml` value.
- Public entrypoint/version tests: 6 passed.
- `make lint`: passed.
- Exact Makefile mypy targets: passed.
- `make test`: 1048 passed, 2 skipped.
- mypy phase of `make type`: passed.
- `make test-boundaries`: 3 passed.
- Full suite: 1031 passed, 2 skipped, 4 failed in cross-repo E2E scenarios because the copied frontend's `test:audit` currently fails unrelated RSS, topic-strip, and newsletter assertions.
- The same four failures reproduce directly in the clean frontend checkout, proving they are baseline failures rather than regressions from Plan 002. Plan 002 is complete.

## Subsequent plans

Before each later plan, update this specification with its exact files, behavior, risk classification, and verification commands. Do not begin a later plan until the current plan's regression checks pass or its STOP condition is reported.

## Fix: publication-safe image alt text

### Goals

- Publish the blocked Elias Thorne article with descriptive Spanish alternative text.
- Prevent Refinery from generating the front-end-prohibited `Imagen de {title}` fallback.
- Preserve valid editorial alt text and deterministically repair missing or generic values before rendering.

### Implementation

- Add a narrow pure normalization function beside `ArticleImageHandler`, the owner of image resolution.
- Use it for staged briefs, downloaded images, local images, and the final Refinery guard.
- Add focused unit coverage for missing, generic, and valid alt text.
- Update the pending article in the temporary publication checkout and rerun publication validation before moving it into the front-end repository.

### Verification

- Run focused image handler and Refinery engine tests.
- Run `make lint`, `make type`, `make test`, `make test-boundaries`, and `make quality-gate` in the backend.
- Run `npm run lint`, `npm run validate:content`, `npm run build`, `npm run test:dist`, and `npm run test:audit` in the front-end.

### Verification result

- Focused image/refinery tests: 27 passed.
- Backend: lint, mypy, 1053 tests, boundaries, and quality gate passed.
- Front-end article checkout: lint, content validation, build, and dist sanity passed.
- Front-end audit reproduced the four documented baseline failures unrelated to image alt text.
- Recovery branch was pushed and PR #106 was opened.

## Current implementation: Plan 003

- Replace loose `"si" in editor_approval` matching with an explicit `s[ií]` word-boundary match.
- Reject leading `no` and any response containing `requiere cambios`.
- Preserve the existing average and minimum-score publication requirements.
- Verify affirmative, negative, substring-regression, plain `si`, and low-score cases.
- Run focused council tests, lint, mypy, and the full backend suite; compare cross-repo failures against the known four-test frontend baseline.

## Current implementation: Plan 004

- Add tests only for the deterministic production fallback `HeuristicScorer`.
- Use a lightweight article stub and avoid database or network access.
- Characterize empty input, quantitative evidence, LatAm affinity, low-value suppression, wow-factor saturation, output bounds/rounding, and determinism.
- Require at least 90% line coverage of `heuristic_scorer.py`; production scoring code must remain unmodified.

## Current implementation: Plan 005

- Add `idx_score_logs_article_latest` on `(article_id, calculated_at)` to `ScoreLog` metadata.
- Add an idempotent Alembic migration chained to the confirmed single head `a54ba7f7dabb`.
- Assert index presence through SQLAlchemy introspection.
- Keep the serving query unchanged and verify migrations, serving behavior, lint, and typing.

## Current implementation: Plan 006

- Change only the mypy hook's stale `src/utils/` regex segment to `news_collector/utils/`.
- Validate the pre-commit configuration and execute the mypy hook against both intended utility modules.
- Keep Makefile targets and all other hook settings unchanged.

### Verification result

- `pre-commit validate-config`: passed.
- Direct regex check: `True` for all three intended paths.
- The mypy hook now runs rather than reporting no files.
- The hook fails with 38 transitive errors across 27 imported files in its isolated environment, including missing third-party stubs and existing `no-any-return` issues.
- Per the plan's STOP condition, no hook arguments, dependencies, or unrelated type debt were changed. Plan 006 remains blocked pending an explicit choice between aligning the hook's import behavior/dependencies with Makefile mypy or addressing the wider type backlog.

## Current implementation: Plan 007

- Remove the divergent legacy `setup.py`; retain `pyproject.toml` as the packaging source of truth.
- Confirm no active CI, Makefile, script, or documentation reference invokes `setup.py`.
- Confirm `aiohttp` is not imported by project code.
- Prove packaging remains functional by rebuilding the same versioned wheel and running public entrypoint tests and lint.

### Verification result

- Baseline build with `setup.py`: succeeded and produced version `1.3.3`.
- Build after removal: failed because setuptools discovered multiple top-level packages in the flat layout.
- `setup.py` was restored exactly, as required by the plan's STOP condition.
- Public entrypoint tests (5) and lint pass.
- Removal requires first adding explicit package discovery to `pyproject.toml`, which is outside this plan's permitted scope.

## Current implementation: Plan 008

- Capture the validation bulk-update result and stop immediately on an explicit `False` persistence result.
- Return `success=False` and emit `validation.persist_failed` with batch context.
- Count validated/rejected articles only after the batch persistence succeeds, preventing inflated reports.
- Preserve the existing max-batch guard semantics and tolerate legacy test doubles that do not explicitly return a bool.

## Current implementation: Plan 009

- Wrap all external editorial context in explicit `DATOS_NO_CONFIABLES` delimiters and instruct the model to treat the block as reference data rather than instructions.
- Add a regression test proving an injection payload remains inside the untrusted-data boundary.
- Expand deterministic SSRF coverage for invalid schemes, absent hostnames, cloud metadata/link-local addresses, private IPv4, IPv6 loopback, public resolution, and DNS failure.
- Document that URL validation runs before requests and redirects but does not pin the validated IP to the connection.
- Defer IP pinning because preserving hostname semantics for HTTP `Host` and TLS SNI requires custom transports for both `requests` and `httpx`, outside the plan's bounded scope.

### Verification result

- Editorial focused tests: 8 passed.
- SSRF focused tests: 10 passed; `security.py` reached 100% coverage in the full suite.
- `make lint`: passed.
- Official incremental mypy targets: passed.
- `make test`: 1045 passed, 2 skipped.
- The extended coverage run retained exactly the four known cross-repo frontend audit failures and introduced no new failures.

## Current implementation: Plan 010

### Goals

- Investigate whether persisted article clusters can support a reader-facing "also reported by" surface.
- Add one read-only endpoint, `GET /v1/articles/{id}/related`, without changing clustering, publication, export, or frontend contracts.
- Return at most 20 sibling articles, excluding the requested article and ordering by `final_score DESC, id DESC`.
- Document canonical-member options, cluster stability, observed database cardinality, and the smallest proposed frontend contract delta.

### Implementation details

- Add local Pydantic response models in `news_collector/serving/api.py`; this response is confined to the serving boundary.
- Return `404` for an unknown article, an empty data list for a known article without a cluster, and typed sibling records containing id, title, source, URL, and score.
- Treat related membership as a dynamic lookup because save-time merge and revalidation logic may change `cluster_id` values.
- Create `docs/spikes/cluster-master-story.md` with source references and read-only database evidence.

### Verification

- Run the read-only cluster cardinality query against the configured database.
- Run `.venv/bin/pytest tests/test_serving_api.py -q` after endpoint and test changes.
- Run `make lint`, `make type`, `make test`, and `make test-boundaries` for this high-risk serving change.
- Confirm no Plan 010 changes touch contracts, clustering, publication, or frontend code.

### Verification result

- Configured database: 864 articles in 841 clusters; maximum cluster size 13; 10 clusters have multiple members.
- Serving tests: 6 passed, covering no cluster, deterministic sibling ordering, and unknown ids.
- `make lint`: passed.
- `make test-boundaries`: 3 passed.
- `make test`: 1048 passed, 2 skipped.
- The official mypy phase passed. Its bundled extended test run produced 1055 passes, 2 skips, and exactly the four known frontend-audit failures from the established baseline.
- Plan-scoped source changes are limited to the serving endpoint, serving tests, and the spike note; contracts, clustering, publication, and frontend code remain unchanged.

## Follow-up: resolve Plan 006 blocker

- Replace the isolated `mirrors-mypy` hook with a local hook that invokes `.venv/bin/mypy`.
- Preserve the corrected target regex and `--config-file=pyproject.toml` argument.
- This deliberately aligns pre-commit with the repository bootstrap and Makefile environment instead of maintaining a second dependency universe.
- Verify config validity, direct hook execution on all three targets, lint, and the official mypy phase.

### Verification result

- `pre-commit validate-config`: passed.
- The mypy hook ran on all three intended targets and passed.
- `make lint`: passed.


## Fix: portable runtime paths for GitHub Actions

### Goals

- Restore the scheduled collector after six consecutive GitHub Actions failures.
- Remove workstation-specific absolute paths from the active configuration.
- Prevent the active `config.toml` from reintroducing absolute runtime paths.

### Root cause

The active configuration pointed data, log, DLQ, and log-file paths at
`/home/carlos/VS_Code_Projects/products/noticiencias/noticiencias_news_collector`.
On GitHub-hosted runners, importing `news_collector.config.settings` attempted to
create that tree and failed with `PermissionError: /home/carlos`.

### Implementation

- Use repository-relative paths under `data/` in `config.toml`.
- Add a focused regression test that reads the committed TOML and rejects absolute
  values for all runtime-owned paths.
- Do not change path resolution, environment precedence, or runtime configuration code.

### Verification

- Run `pytest tests/test_config_manager.py -q`.
- Run `make config-validate`.
- Run `python scripts/run_collector.py --dry-run` or the scheduled collector workflow
  and confirm initialization no longer attempts to create `/home/carlos`.


## CI baseline recovery and deep-audit campaign

### Goal

Restore every required GitHub Actions gate to green, verify the scheduled collector end
to end, then run a deep repository audit and persist all findings and evidence.

### Confirmed failures and intended fixes

1. **Dry-run export contract:** preserve side-effect-free collection and export the
   articles produced by that same run instead of reopening an empty database.
2. **Dependency locks:** regenerate all lockfiles with the repository's pinned
   `pip-tools==7.5.3`; do not hand-edit hashes or remove declared runtime extras.
3. **Security expiry:** remove obsolete suppressions only after checking current
   advisories; upgrade fixable runtime dependencies and document accepted dev-only risk.
4. **NO_WARN fixture:** explicitly configure `ollama.enrichment_model`; do not weaken
   production policy.
5. **Frontend checkout selection:** make candidate priority explicit and deterministic;
   a stale temporary clone must not outrank the verified sibling checkout.
6. **Lint/type debt:** apply Black to the three reported files, remove the unused import
   and obsolete type ignores, and use a safe local default for the development server.
7. **Governance portability:** remove the workstation-specific scope path from
   `docs/AGENTS.md`.
8. **Deep audit:** after CI is green, inspect correctness, security, architecture,
   operations, tests, dependency hygiene, determinism, performance and docs drift.

### Risk classification

Critical: dependencies, security, CI and runtime configuration. High: CLI export,
workflow, serving and Refinery checkout resolution.

### Required verification

- Focused regression tests for every behavior change.
- `make config-validate`, `make lint`, `make type`, `make test`,
  `make test-boundaries`, `make quality`.
- Dependency lock check and E2E contract workflow.
- Scheduled collector rerun.
- All PR workflows completed successfully.
- Audit report under `docs/audits/` with evidence, severity, disposition and backlog.


### E2E dry-run serialization follow-up (2026-07-12)

The corrected in-memory dry-run path exposed structured Pydantic metadata that the
JSON exporter did not normalize. The exporter must convert model metadata with
`model_dump(mode="json")`, finish serialization before touching the destination,
and replace the destination atomically so a serialization error cannot leave an
invalid partial contract artifact. The E2E contract must export at least one
article and pass `scripts/validate_export.py`.

### Portable bootstrap environment follow-up (2026-07-13)

The Code Quality gate exposed a tracked local `.venv` whose `pyvenv.cfg` and
entrypoints reference `/home/carlos/.pyenv`. Bootstrap accepted the copied Python
binary because it could execute, but `pip-audit` later followed the stale base
interpreter and failed before producing a report. The repository must not depend
on or cache a checked-in virtual environment. Bootstrap must reject a virtualenv
whose recorded base interpreter is unavailable, `.venv/` must be ignored, and CI
must recreate it from lockfiles before running the fail-closed security scan.

Verification: Code Quality must complete Ruff, mypy, tests, Bandit, pip-audit,
Semgrep, and the quality gate on the PR head; repository search must find no
tracked workstation-specific virtualenv path.


### Dry-run and export failure-signal closure (2026-07-13)

Dry-run must not persist article or source operational state. During collection it
must intercept and later restore single/bulk article saves plus source statistics,
circuit-state, and feed-metadata updates. The CLI must also avoid writing the
unsolicited source-health artifact in dry-run; an explicitly requested export remains
allowed. Export serialization or atomic replacement failure must leave any previous
destination unchanged, remove the temporary file, and exit non-zero. The summary
contract preserves a nonblank source summary after trimming; otherwise it exports the
first 500 characters of trimmed content.

Verification: extend the dry-run fake database to call every write API and assert zero
persistence plus method restoration. Add CLI tests for serialization/replace failure,
non-zero exit, destination preservation, and temporary-file cleanup.


### Newly disclosed primary-lock vulnerability closure (2026-07-13)

Once pip-audit could run portably, it found 16 advisories across 10 packages in
the primary runtime lock. Every reported item has a published fixed version. Raise
minimums for Click 8.3.3, Starlette 1.3.1 (and a compatible FastAPI resolution),
IDNA 3.15, lxml 6.1.0, Mako 1.3.12, Pygments 2.20.0, python-dotenv 1.2.2,
Requests 2.33.0, urllib3 2.7.0, and SoupSieve 2.8.4. Regenerate every lock
mechanically and require dependency-lock sync, full tests, and fail-closed pip-audit
to pass. Do not add new advisory ignores.



### Improve Deep audit closure and external validation policy (2026-07-13)

The equivalent `/improve deep` audit is authoritative at
`docs/audits/2026-07-improve-deep.md` and records F-0030 through F-0054.
Security exceptions must be advisory-specific, optionally dependency-scoped, justified,
and expiring. The Semgrep Click exception is limited to dependency `click` in the
isolated security-tool lock and expires 2026-08-31; it must not suppress the advisory
for runtime or unrelated dependencies.

A GitHub Actions job that never receives a runner, reports no steps, and produces no
log is external validation evidence, not a passing or code-failing gate. After Actions
availability is restored, rerun the complete PR matrix and a branch-equivalent daily
collector invocation before operational closure. Until then the last executable-head
results and the local dependency-scope regression are the retained evidence.
