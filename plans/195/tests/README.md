# Verification evidence

Initial inventory:16frontend and2backend dependency alerts; zero open code-scanning/secret-scanning alerts. Fresh results will be recorded after execution.

## Dependency-tree triage

Workers pass `npm ls --all`. Frontend and replay-tool recursive checks exit1
on unchanged optional peers, independently verified against origin/main:

- Astro7.4.0 optionally requests markdown-remark^7.3.0; MDX7.0.3 pins7.2.1.
- MDX7.0.3 optionally requests markdown-satteri^0.3.1; Astro pins0.4.4.
- MongoDB7.7.0 optionally requests gcp-metadata^7.0.1; unchanged Promptfoo/Google Auth ranges resolve9.2.1.

These are documented pre-existing peer mismatches. Clean installs, audits,
default-depth checks and supported build/replay behavior are verified separately;
a passing full recursive graph is not claimed. Independent review found no new
P1/P2 issues. Offline replay, including its real Promptfoo integration, passed22
tests with outbound networking denied.

## Fresh completed validation

- Clean replay-tool install and full npm audit:0vulnerabilities. Admin lock audit:0.
  Site and worker audits are also0; all four cold-lockfile audits work without
  node_modules. See dependency-audits.json. No alert was dismissed.
- Backend lint, type/coverage via make quality, ordinary unit tests and docs checks
  passed. Unit result:4,447passed,40skipped,190deselected. Live provider/network
  opt-ins remain skipped; offline real Promptfoo replay is separately22passed.
- Updated make quality passed with official strict Semgrep profiles. Its seven
  visible SQL audit findings are reviewed in semgrep-triage.md;0scanner errors.
- Independent review found no P1/P2 issues in dependencies, workflow additions,
  reviewed SQL paths or strict scanner failure handling.
- Frontend: lint/type/content/build/dist/1,019unit+coverage tests passed;
  91browser tests passed/1skipped. Workers: typecheck and75tests passed.

Full prepush passed: unit and integration suites, pipeline E2E, performance
tests and all three quality snapshots. Hosted CI/live alert receipts are
recorded after those runs finish. These records are local source verification, not a claim
that a pending PR has already been deployed. Credential rotation remains an
operator action; absence of GitHub secret alerts does not prove revocation.

## Prioritized dependency findings

1. **High — unpatched node-forge:** the optional jks-js path in the offline
   tool retained a signature-verification advisory with no published patch.
   Promptfoo0.125.1 removes that dependency; neither package remains in the lock.
2. **High — MSAL Node:** nested Azure Identity pulled6.x despite another7.1.0
   copy. Override all copies to patched7.1.0. Only offline replay is supported;
   optional cloud authentication is not exercised or activated here.
3. **High — additional npm findings:** patch basic-ftp to6.2.3 (its parent
   excludes the patched major) and body-parser to2.4.0. Both are outside the
   supported offline echo execution path; the full lock audit now reports0.
4. **Quality defect — scanner noise/failure handling:** replace the starter
   catch-all with official profiles; preserve visible reviewed findings and
   fail on technical/partial-scan errors. See the source triage and controls.
