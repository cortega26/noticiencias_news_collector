# Improve Deep Audit — 2026-07-13

Status: complete. Repository remediation and finding dispositions are documented.
Final-head GitHub-hosted execution is externally blocked because GitHub stopped
assigning runners; the last executable head and the no-runner evidence are recorded
separately below.

## Executive summary

This audit started from six consecutive scheduled-collector failures and expanded to
the complete pull-request gate surface. The first operational root cause was a set of
committed workstation-specific runtime paths. After fixing those paths, progressively
deeper CI execution exposed defects in dry-run data flow, bulk-write isolation, export
serialization and atomicity, summary-contract compatibility, model-stage configuration,
dependency locks, security exception expiry, deterministic checkout selection, and a
second portability failure caused by an entire local virtual environment committed to
the repository.

The campaign records 25 findings (F-0030 through F-0054): 22 resolved or contained in
PR #235, 1 partially resolved because the connected GitHub policy rejected two
privileged workflow edits, 1 monitored external-source item, and 1 external validation
infrastructure blocker. The previously open F-0024 is
closed by the exclusive-create remediation recorded under F-0039; it is not
reclassified as new work. No residual item is represented as fixed merely because
required PR gates pass.

No repository or installed skill definition named `/improve` exists. This report is the
requested equivalent deep audit, covering runtime portability, data-flow correctness,
side-effect isolation, dependency and security posture, deterministic behavior, CI
supply-chain hardening, operational behavior, quality gates, and documentation drift.

## Scope and method

- Compared PR #235 with `main` and inspected each failed GitHub Actions job and log.
- Traced dry-run data from `run_collection_cycle()` through reporting and export.
- Verified that both single and bulk persistence methods are neutralized in dry-run.
- Exercised export mappings, model-like metadata, missing summaries, atomic replacement,
  and the full frontend schema validator.
- Reviewed dependency declarations, all generated locks, pip-audit policy, bootstrap,
  tracked repository artifacts, serving defaults, checkout discovery, audit ledgers,
  and workflow pinning/install patterns.
- Followed the mandatory change matrix in `docs/AGENTS.md` and requested an independent
  spec/implementation gap review.
- Required final evidence: lint, type, full tests, quality/security, config validation,
  dependency lock sync, E2E contract, system/source gates, and a branch-equivalent run
  of the scheduled collector without merging the draft PR.

## Findings

| ID | Severity | Finding | Evidence | Status / disposition |
| --- | --- | --- | --- | --- |
| F-0030 | S0 | Active runtime paths were tied to one workstation and prevented initialization on GitHub-hosted runners. | Scheduled runs #229–#234; `PermissionError: /home/carlos`; `config.toml`. | **Resolved.** Runtime data, log, DLQ, and log-file paths are repository-relative; regression coverage rejects absolute active paths. |
| F-0031 | S1 | Dry-run export discarded articles produced by the same cycle and queried a new empty database; article and source-state persistence APIs were not all neutralized. | First corrected E2E collected articles but exported zero; collectors can call single/bulk saves plus source statistics, circuit-state, and feed-metadata updates. | **Resolved.** Dry-run captures in-memory articles, neutralizes and restores all five persistence paths, skips the unsolicited source-health file, and has zero-persistence/method-restoration coverage. |
| F-0032 | S1 | Dependency declarations and generated lockfiles drifted after runtime/security dependency changes. | Dependency lock sync failed and published mechanically regenerated artifacts. | **Resolved.** All three lockfiles were regenerated with the repository toolchain and lock sync passes. |
| F-0033 | S0 | Expired pip-audit exceptions hid dependencies that no longer met the recorded remediation policy. | `CVE-2026-0994` and `GHSA-7p94-766c-hgjp` expired 2026-06-30; NLTK was 3.9.2. | **Resolved for the scanned runtime set.** NLTK is locked at 3.10.0 and obsolete exceptions were removed. The secondary-lock coverage issue is tracked separately as F-0047. |
| F-0034 | S2 | The NO_WARN model-registry fixture and typed configuration schema drifted after enrichment became a required stage. | Explicit-stage test inherited enrichment; schema lacked `enrichment_model`. | **Resolved.** Schema, generated field docs, and explicit-stage coverage now include a canonical enrichment model without weakening production policy. |
| F-0035 | S2 | Local frontend checkout discovery was nondeterministic and could prefer a temporary stale clone. | Extra candidates preceded verified siblings; sibling iteration was unsorted. | **Resolved.** Verified sibling candidates are sorted deterministically and temporary/extra candidates are considered last. |
| F-0036 | S2 | Webhook/editorial changes arrived with Black, Ruff, and mypy blockers, including a public bind default. | Black/Ruff/mypy job logs on the first PR head. | **Resolved.** Files are formatted, unused import/ignores removed, and direct serving defaults to loopback. |
| F-0037 | S3 | Binding contributor documentation encoded an absolute workstation path. | `docs/AGENTS.md` scope. | **Resolved.** Scope is the repository root. |
| F-0038 | S2 | The audit index contradicted the authoritative ledger. | `Audit_Backlog.md` claimed 18 open findings while the ledger showed only F-0024 open from that round. | **Resolved as documentation in this campaign.** Index updated with exact open/closed counts and the new audit link. |
| F-0039 | S2 | Prior finding F-0024 remained open: an existence check followed by a normal write retained a TOCTOU window. | `Findings_Ledger.md`, F-0024; publication concurrency review. | **Resolved.** New publications use exclusive file creation (`x` mode); a concurrent winner raises a controlled conflict instead of being overwritten. Regression coverage exercises the collision path. |
| F-0040 | S1 | Quality installed Gitleaks through an unverified archive stream. | Original `.github/workflows/quality.yml` used `curl ... | tar` without checksum validation. | **Resolved.** The workflow downloads the release archive and published checksum file separately and verifies the selected archive with strict `sha256sum` before extraction. |
| F-0041 | S2 | The direct serving entry point enabled auto-reload unconditionally. | Original `news_collector/serving/__main__.py`, `reload=True`. | **Resolved.** Reload defaults off and is enabled only by explicit `NOTICIENCIAS_API_RELOAD` truthy values. |
| F-0042 | S2 | GitHub Actions used mutable version tags instead of immutable commit SHAs. | Action references across local composite actions and workflows. | **Partially resolved.** All 17 connector-permitted workflow/action files now pin reviewed immutable SHAs with tag comments. `release.yml` and `sync-master.yml` remain tag-based because the connected GitHub policy rejected mutation of workflows that publish packages/releases or force-push `master`; no bypass was attempted. |
| F-0043 | S1 | Collector export failures were printed but still returned CLI exit code 0, and duplicated initialization commentary remained. | `scripts/run_collector.py`; independent spec/implementation review. | **Resolved.** Serialization and atomic-replace failures now return exit code 1, preserve a previous export, clean the temporary file, and have regression tests; duplicate commentary was removed. |
| F-0044 | S1 | Pydantic-like metadata was not JSON-normalized and export wrote directly to the destination, permitting a partial artifact on serialization failure. | E2E follow-up failed during metadata serialization; direct destination write. | **Resolved.** Metadata uses `model_dump(mode="json")`; serialization completes to a temporary file followed by atomic `os.replace`; regression coverage includes model metadata. |
| F-0045 | S1 | Some valid source articles omitted or blanked `summary`, violating the downstream frontend export contract. | E2E validator rejected MIT Technology Review and Hugging Face records. | **Resolved.** Export uses a bounded content-derived summary only when source summary is absent/blank; E2E validates all exported records. |
| F-0046 | S0 | A complete local `.venv` was committed, including `/home/carlos/.pyenv` interpreter metadata; bootstrap reused it and pip-audit could not start on Actions. | Code Quality run 29262985410, job 86860855275; tracked `.venv/pyvenv.cfg` and entrypoints. | **Resolved.** Entire `.venv/**` tree removed, local venvs ignored, bootstrap rejects a missing base interpreter, and a git-index regression test prevents reintroduction. |
| F-0047 | S1 | The quality audit scanned only `requirements.lock`, leaving secondary security/refinery locks outside fail-closed vulnerability coverage. | Original Makefile quality targets; secondary-lock audit output. | **Resolved.** Quality and developer security targets now route all three generated locks through the same expiry-aware fail-closed security gate. Eight newly visible tool-lock advisories were eliminated by upgrading GitPython, Msgpack, Protobuf, Pytest, Semgrep, and their generated dependency closure. The two remaining NLTK advisories have no fixed release and retain bounded, documented exceptions through 2026-09-30. |
| F-0048 | S2 | Live collection is operationally degraded for a small subset of third-party sources: Import AI returned 403 and The Neuron rejected several enrichment fetches with 403. | E2E run 29262984968/job 86860854548; source success 98.25%. | **Backlog / external dependency.** Collection and contract export remain successful. Recheck over multiple runs, then update source strategy or disable the source only if the failure is persistent; enrichment already degrades without corrupting output. |
| F-0049 | S0 | Once the portable pip-audit gate ran, it disclosed 16 fixable advisories across 10 primary runtime packages. | Code Quality advisory output; primary dependency and lock diffs. | **Resolved.** Minimums were raised to published fixed versions, FastAPI was moved to a Starlette-compatible release, every lock was regenerated mechanically, obsolete exceptions were removed, and lock sync passes. |
| F-0050 | S1 | The backend publication smoke fixture omitted the frontend-required absolute `source_url`, so the real frontend content gate rejected the otherwise valid fixture. | Publication Smoke Test run 29266268327; `_smoke-test.md: source_url must be an absolute http(s) URL`. | **Resolved.** The typed fixture now carries an absolute synthetic source URL, the Markdown renderer emits it, and a regression assertion guards the exact frontmatter. |
| F-0051 | S2 | The mocked redirect response in the SSRF regression lacked its originating request; the upgraded Requests redirect resolver now requires that protocol context. | CI run 29266617114; `test_robust_requests_client_blocks_redirects` failed with `NoneType.url`. | **Resolved.** The test double now attaches the prepared request to the synthetic response, matching a real adapter response while preserving the assertion that a redirect to link-local metadata is blocked before a second network send. |
| F-0052 | S1 | The security lock was compiled from the full project plus security/test extras, mixing incompatible runtime and Semgrep Click constraints and allowing the old lock to anchor vulnerable tool versions. | Lock-sync runs 669–671; `click>=8.3.3` conflicted with Semgrep's `click~=8.1.8`; pip-tools reused prior concrete pins. | **Resolved.** A dedicated `requirements-security.in` defines the isolated quality environment, lock generation uses it with an explicit upgrade, and the runtime/refinery dependency declarations retain their independent constraints. |
| F-0053 | S1 | The newest available Semgrep release still requires vulnerable `click~=8.1.8`, while the advisory fix is Click 8.3.3; forcing the fixed version would violate the analyzer's declared compatibility. | Code Quality run 29268622310; `semgrep==1.169.0`; `PYSEC-2026-2132`. | **Contained / accepted temporarily.** The exception is scoped to advisory plus dependency name `click`, applies only to the isolated security-tool lock, and expires 2026-08-31. Runtime Click remains fixed and unallowlisted. A regression proves the same advisory is not suppressed for another dependency. |
| F-0054 | S1 | GitHub stopped assigning hosted runners during final validation: every job failed before setup, with `steps: null` and no downloadable log. | Final head `dff5ee4`; nine runs 29269237658–29269238918; Code Quality retry job 86882718414 reproduced the result. | **External validation blocker.** Not attributed to repository code. Last executable-head evidence and local validation are retained below; owner action is required to restore Actions capacity/account eligibility before rerunning the final matrix and scheduled collector. |

## Implemented remediation

- Portable active configuration and repository governance paths.
- Side-effect-free dry-run across both persistence APIs, with in-memory reporting.
- Shared export normalization for mappings, ORM-like values, Pydantic metadata, dates,
  missing summaries, and atomic destination replacement.
- Mechanically regenerated runtime, Refinery, and security lockfiles.
- NLTK security upgrade and removal of expired allowlist entries.
- Typed enrichment-model schema/docs plus strict-policy regression coverage.
- Deterministic frontend checkout ordering.
- Formatting, Ruff, mypy, and safe loopback-default corrections.
- Removal and future rejection of tracked local virtual environments.
- Diagnostic lock artifacts on lock-sync failure.
- Exclusive-create protection for new publication files.
- Explicit opt-in serving reload.
- Checksum verification for the Gitleaks binary archive.
- Immutable action pins in every connector-permitted workflow/action file.
- Fail-closed auditing of runtime, security, and Refinery lockfiles.
- Fixed dependency floors for all 16 primary-lock advisories.
- Publication fixture alignment with the frontend `source_url` contract.
- Requests-compatible SSRF redirect test-double protocol context.
- Isolated, reproducible security-tool input and upgrade-aware lock generation.
- Dependency-scoped, expiring containment for Semgrep's unfixed Click constraint.

## Validation ledger

| Gate | Evidence | Result |
| --- | --- | --- |
| Placeholder Audit | Run 29268622365 | Passed on code head `b88dc92` |
| Config validation/docs | CI run 29268622331; docs run 29268622322 | Passed on code head `b88dc92` |
| Healthcheck and performance | CI run 29268622331 | Passed on code head `b88dc92` |
| Lint / Black / Ruff | CI run 29268622331 | Passed on code head `b88dc92` |
| Type check | CI run 29268622331 | Passed on code head `b88dc92` |
| Full pytest suite | CI run 29268622331 | Passed on code head `b88dc92`; last-change dependency-scope test passed locally |
| Code Quality / security | Run 29268622310 | Runtime audit, coverage ratchet, Bandit, and preceding checks passed; only F-0053 remained before containment |
| Dependency lock sync | Run 29268622309 | Passed with exact generated locks |
| E2E contract | Run 29268622340 | Passed with non-empty schema-valid export |
| System/source gates | Runs 29268622412 and 29268622377 | Passed |
| Publication smoke | Run 29268622372 | Runner was not assigned; no steps/logs (F-0054) |
| CI coverage job | Run 29268622331 | Runner was not assigned; upstream test and coverage-artifact upload passed (F-0054) |
| Final head matrix | Runs 29269237658–29269238918; retry job 86882718414 | Externally blocked before setup; all jobs report `steps: null` (F-0054) |
| Scheduled collector equivalent | Not started after runner allocation failed globally | Externally blocked by F-0054; do not infer collector failure |

## Residual risk and prioritized backlog

1. **S2 — F-0042:** pin the action references in `release.yml` and
   `sync-master.yml` through an owner-approved workflow change. The connected GitHub
   policy blocked those two privileged edits; 17 other files are already pinned.
2. **S2 — F-0048:** monitor third-party 403 source degradation across multiple live
   runs and change source strategy only if it remains persistent.
3. **S1 external — F-0054:** restore GitHub Actions runner/account availability, then
   rerun the final PR matrix and the branch-equivalent scheduled collector. No code
   change is indicated by the available evidence.
4. **S1 accepted risk — F-0053:** remove the Click exception no later than 2026-08-31
   when Semgrep publishes compatibility with Click 8.3.3 or later.

F-0042 is a documented partial remediation, F-0048 is an external source dependency,
F-0053 is a bounded tool-only accepted risk, and F-0054 is an external validation
blocker. All repository defects with permitted in-scope remediations are closed.

## Exit criteria

The audit report, `todo.md`, and the central ledger/backlog contain exact dispositions.
Operational closure still requires the owner-controlled F-0054 follow-up: restore
runner availability and rerun the final matrix plus scheduled-collector equivalent.
