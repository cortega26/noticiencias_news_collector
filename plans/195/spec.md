# Plan 195 — remediate current Security and Quality findings

## Objective and scope

Resolve verified open GitHub dependency alerts in both repositories without dismissing alerts, weakening security checks or activating optional cloud providers. Initial live inventory: frontend 16 Dependabot alerts; backend two. Both report zero open code-scanning and secret-scanning alerts; this does not prove that no secret has ever been exposed. Operator rotation of previously exposed local credentials remains separate.

## Decisions and invariants

Dependency changes are critical risk. Use isolated worktrees and preserve canonical checkouts. Keep Vitest and coverage packages aligned at patched 4.1.12; remove the unnecessary fast-uri major override so AJV resolves compatible patched3.x; advance vulnerable overrides for brace-expansion, selector parsing, worker sharp and Undici7.30.1 (including additional advisories found by npm audit). The selector-parser major override requires the full real site build and regression suite, because typography pins an older vulnerable parser.

Backend: upgrade only the development-only replay tool from Promptfoo0.124.1 to0.125.1, whose optional dependencies drop jks-js/node-forge. Do not invent a patched node-forge version: GHSA-86w9-cpqp-85rv reports none. Override the remaining optional Azure MSAL Node dependency to patched7.1.0; cloud providers remain outside the offline tool's supported scope. Full npm audit additionally requires body-parser2.4.0 and a basic-ftp6.2.3 override (get-uri still requests vulnerable5.x); verify the offline supported path after these transitive changes. Worker Zod must also advance within its existing4.x range. Keep production Python/admin dependencies and editorial behavior unchanged.

## Semgrep quality correction

The local starter rule matches every string assignment and emits603 generic
warnings; its top-level include list does not activate the intended registry
profiles. Replace it with the intended official p/python, p/security-audit and
p/secrets profiles, used identically by local and CI quality targets with
metrics disabled and strict partial-scan error handling. Remove the unused starter config and update active security
and quality docs. Keep the existing advisory policy for findings; technical
scanner failures must fail rather than masquerade as findings. Save a JSON
report for auditable triage without printing potential matched secrets.

The official profiles currently report seven SQLAlchemy text audit matches.
Review their values/data flow; repository-owned status constants in partial
index DDL are not user SQL. Document findings explicitly without broad rule
suppression or altering applied migrations to appease a scanner. Run real
positive/negative scanner controls and verify technical-error propagation.

## Acceptance and verification

- Inspect live GitHub alerts and actual dependency paths, documenting versions and exposure. No raw secret values in logs/reports.
- Clean locked installs and full npm audits for frontend, workers and backend replay tool; confirm removed vulnerable paths and clean default-depth npm dependency checks. Triage recursive peer mismatches against the base: record unchanged optional peers explicitly rather than forcing unrelated framework/cloud SDK upgrades or claiming that the recursive tree passes.
- Frontend lint, typecheck, content validation, build, distribution checks, audit tests; worker typecheck and coverage tests. Run existing browser checks when needed to establish that typography/site output still works.
- Backend lint/type/test, quality, docs/inventory checks; existing editorial-evaluation tests including real Promptfoo baseline/paired replay with networking denied. Baseline must pass6/6; paired controls must produce the expected7passes/5deliberate failures, preserving captured output and honest provenance.
- Independent review under docs/AGENTS.md; read remote review threads before merge. Verify exact-head CI and live alert resolution after authorized integration; report any unpatched issue honestly.
- Add full npm audit gates (including development dependencies) to existing frontend Content Guard and backend Code Quality workflows, covering root/workers and admin/editorial respectively. Use lockfile auditing without installing or running the optional tool in CI. Confirm the commands work without installed packages. Do not weaken or suppress findings.
- Update active dependency documentation in the same changes. Final reports distinguish open alerts from green CI and preserve remaining operator actions.
