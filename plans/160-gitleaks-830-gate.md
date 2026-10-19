# Plan 160: Restore the gitleaks gate under 8.30 (report parsing + fixture allowlist)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c8196412..HEAD -- scripts/security_gate.py .gitleaks.toml .gitleaks-baseline.json .github/workflows/quality.yml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1 (CI gate is red on `main`)
- **Effort**: S
- **Risk**: MEDIUM (touching a security gate; a wrong change can silence it)
- **Depends on**: none
- **Category**: security / CI
- **Planned at**: commit `c8196412`, 2026-10-19

## Why this matters

The `Code Quality` workflow has been **failing on `main` since `8aa43fc8`**
(2026-10-19): the `gitleaks` step exits 1 with a HIGH finding at
`tests/scripts/test_editorial_critic_canary.py` (rule `generic-api-key`,
`StartLine` 281, matched value `key`). That value is a **fixture literal**, not
a credential, and the repository's own baseline was supposed to suppress it.

Two independent defects make the gate unreliable:

1. **Version drift.** CI installs gitleaks **8.30.1** (pinned in
   `.github/workflows/quality.yml`, download + checksum). The baseline entry was
   captured with gitleaks **8.18.1** (the tracked `./gitleaks` binary) at
   commit `2e512f7b`. Under 8.30 the baseline no longer matches that finding —
   it is reported against the original commit `a480ca1c` — so the file is
   scanned and flagged. Locally (`./gitleaks`, 8.18.1) the same command reports
   **0 findings**; under 8.30.1 it reports **1**. The gate therefore means
   different things on the developer machine and in CI.
2. **Wrong JSON keys in the gate.** `scripts/security_gate.py::gitleaks_findings`
   reads `ruleID` / `rule_id` / `description` and `secret` / `line` /
   `offender` / `match`, but the gitleaks report emits **`RuleID`, `File`,
   `Secret`, `Match`, `StartLine`** (capitalized, verified with both versions).
   Consequences observed in CI: `"rule_id": ""` (the finding loses its rule),
   and `_secret_is_allowlisted()` receives an **empty** secret, so every
   allowlist regex on secret content is inert — the path-based allowlist still
   works, but the secret-based one never can.

The fix must make the gate **honest and identical in both environments**: the
fixture path is allowlisted explicitly (like the many existing test-fixture
paths), the stale baseline entry is removed, and the parser reads the schema
both binaries emit — with a regression test.

## Current state

- `.github/workflows/quality.yml` — gitleaks installed by pinned download
  (`GITLEAKS_VERSION="8.30.1"`, `:46-58`); scan step `:71-82` runs
  `gitleaks detect ... --baseline-path .gitleaks-baseline.json ... || true`
  then `.venv/bin/python scripts/security_gate.py gitleaks ... --severity HIGH`.
  `fetch-depth: 0` at `:27-29`.
- `scripts/security_gate.py:264-301` — `gitleaks_findings()`:
  - `path = record.get("file") or record.get("path") or record.get("File")` (works)
  - `secret = record.get("secret") or record.get("line") or record.get("offender") or record.get("match") or ""` (**misses `Secret`, `Match`, `Line`**)
  - `rule_id = record.get("ruleID") or record.get("rule_id") or record.get("description") or ""` (**misses `RuleID`**)
  - severity defaults to `HIGH` (`SECRET_SEVERITY_DEFAULT`).
- `scripts/security_gate.py` — `_secret_is_allowlisted(path=..., secret=...)`;
  also check `_build_secret_allowlist()` for how `.gitleaks.toml` is parsed.
- `.gitleaks.toml` — `[allowlist].paths` already contains fixture paths with
  the "Placeholder/fixture values in test and documentation files" rationale
  (e.g. `^tests/integration/test_publication_callback_contract\.py$`,
  `^tests/unit/serving/test_write_surface_bounds\.py$`).
- `.gitleaks-baseline.json` — 5 entries; the last one is
  `{"RuleID": "generic-api-key", "File": "tests/scripts/test_editorial_critic_canary.py", "Commit": "2e512f7b...", "Secret": "key", ...}` (18 fields).
- `tests/scripts/test_editorial_critic_canary.py:281` — the matched literal is
  the three-character word `key` (a key **name** in a fake payload). Confirm by
  reading the line; do **not** paste any matched value into your report beyond
  the already-public `key` token.
- There is **no** unit test for `security_gate.py` today (`tests/scripts/` has
  the canary test only). A new `tests/scripts/test_security_gate.py` is in scope.

## Commands you will need

| Purpose                | Command                                                                 | Provenance | Expected on success |
|------------------------|-------------------------------------------------------------------------|------------|---------------------|
| Install/baseline       | `make bootstrap`                                                        | declared   | exit 0              |
| Lint                   | `make lint`                                                             | declared   | exit 0              |
| Types + coverage       | `make type`                                                             | declared   | exit 0              |
| Unit suite             | `make test`                                                             | declared   | all pass            |
| Fetch gitleaks 8.30.1  | see Step 0 (exact curl + checksum, same as the workflow)                | declared   | version prints 8.30.1 |
| Scan (8.30.1)          | `/tmp/opencode/gl/bin/gitleaks detect --source . --config .gitleaks.toml --baseline-path .gitleaks-baseline.json --report-format json --report-path /tmp/opencode/g830.json --no-banner` | declared | `no leaks found` |
| Scan (8.18.1)          | `./gitleaks detect --source . --config .gitleaks.toml --baseline-path .gitleaks-baseline.json --report-format json --report-path /tmp/opencode/g818.json --no-banner` | declared | `no leaks found` |
| Gate                   | `.venv/bin/python scripts/security_gate.py gitleaks /tmp/opencode/g830.json --severity HIGH` | declared | exit 0, 0 findings |
| New tests              | `.venv/bin/pytest tests/scripts/test_security_gate.py -q --no-cov`      | declared   | all pass            |
| Ledger                 | `make plans-ledger-check`                                               | declared   | `validate_plans_ledger: OK` |

Provenance: all `declared`.

## Scope

**In scope**:

- `scripts/security_gate.py` — case-insensitive field extraction in
  `gitleaks_findings()` (and any helper it needs); no change to
  `PIP_AUDIT_ALLOWLIST` or the pip-audit path.
- `.gitleaks.toml` — one path allowlist entry for the canary test, with the
  same rationale comment style as the neighbours.
- `.gitleaks-baseline.json` — remove the now-dead canary entry (5 → 4 entries);
  do **not** regenerate the other four.
- `tests/scripts/test_security_gate.py` — new regression tests.

**Out of scope** (do NOT touch):

- The tracked `./gitleaks` binary (6.6 MB; removal is plan 150's job) and the
  version pin in `quality.yml` (keep 8.30.1).
- `Makefile`, `.github/workflows/ci.yml`, `docs/ci.md` (plan 139 is editing them
  in parallel).
- `tests/scripts/test_editorial_critic_canary.py` (do not edit the test; only
  allowlist its path).
- `.gitleaks.toml`'s other entries; do not broaden allowlists.
- Collectors, serving, or any product code.

## Git workflow

- Branch: `advisor/160-gitleaks-830`
- Conventional commit, e.g.
  `fix(security): parse gitleaks 8.30 report keys and allowlist the canary fixture (plan 160)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Reproduce in both versions

1. `make bootstrap`; record the baseline gates.
2. Download the CI binary exactly as the workflow does (temp dir):
   ```bash
   mkdir -p /tmp/opencode/gl/bin && cd /tmp/opencode/gl
   V=8.30.1; T="gitleaks_${V}_linux_x64.tar.gz"
   curl -sSL -o "$T" "https://github.com/gitleaks/gitleaks/releases/download/v${V}/${T}"
   curl -sSL -o checksums.txt "https://github.com/gitleaks/gitleaks/releases/download/v${V}/gitleaks_${V}_checksums.txt"
   grep "$T" checksums.txt > expected.sha256 && sha256sum -c expected.sha256
   tar -xzf "$T" -C bin gitleaks && ./bin/gitleaks version
   ```
3. Run both scans (8.30.1 and the repo's `./gitleaks`) into `/tmp/opencode/`.
4. Record: 8.30.1 → 1 finding (`generic-api-key`, canary file, line 281,
   commit `a480ca1c`); 8.18.1 → 0 findings. Print only counts, paths, rule IDs
   and line numbers — **never** values.

**Verify**: the two versions disagree exactly as described; gates green.

### Step 1: Fix the report parsing (test first)

5. Write `tests/scripts/test_security_gate.py` with a canonical **8.30.1**
   record dict (`RuleID`, `File`, `Secret`, `Match`, `StartLine`, `Commit`,
   `Description`, `Fingerprint`, …) written to a temp JSON **array** file, and
   assert:
   - `gitleaks_findings()` returns one finding with the right `path`,
     `rule_id` and severity (currently `rule_id` would be `""` → red test);
   - a path allowlisted in a temp `.gitleaks.toml` is skipped (monkeypatch the
     module's `GITLEAKS_CONFIG`/allowlist loader the way the function reads it);
   - a secret allowlist regex that targets the **`Secret`** field suppresses the
     finding (proves `_secret_is_allowlisted` now sees it);
   - a 8.18.1-shaped record (same capitalized keys — verify what 8.18 emits)
     still parses identically;
   - malformed input (a list entry that is not an object) is either rejected or
     counted as a HIGH finding — **never** silently dropped. Choose one and
     test it.
6. Implement normalization in `gitleaks_findings()`: a small helper that reads
   a field by trying the known spellings (`RuleID`/`ruleID`/`rule_id`/`id`,
   `File`/`file`/`path`, `Secret`/`secret`/`Match`/`match`/`Line`/`line`,
   `StartLine`/`start_line`). Keep the existing severity default and output
   shape (`path`, `rule_id`, `severity`) unchanged.

**Verify**: new tests pass; `make lint` green.

### Step 2: Allowlist the fixture and drop the dead baseline entry

7. Add to `.gitleaks.toml` `[allowlist].paths` (with a one-line rationale in
   the same style as its neighbours):
   `'''^tests/scripts/test_editorial_critic_canary\.py$'''`
   Rationale must say the matches are fake payload key names / placeholder
   values used to exercise the canary parser.
8. Remove the canary object from `.gitleaks-baseline.json`; keep the other four
   entries byte-identical and keep the file valid JSON (re-dump with
   `json.dumps(..., indent=2)` only if the existing formatting matches; check
   `git diff` — it must show **one** removed object, not a reformat).

**Verify**: scan with **both** binaries → `no leaks found`; `git diff` on the
baseline shows only the removed entry.

### Step 3: Prove the gate still fails when it must

9. Build a temp report with one synthetic HIGH finding (a real-looking random
   string, **not** a credential from this repo, e.g. generated with
   `secrets.token_hex(16)` at runtime) and run
   `.venv/bin/python scripts/security_gate.py gitleaks <temp> --severity HIGH`
   → **exit 1** and one finding printed.
10. Run it on the real 8.30.1 report → exit 0.
11. Run `make quality` (or the repo's security target) to confirm the pip-audit
    leg is unaffected by the parser change.

**Verify**: 9 fails as designed, 10 passes, 11 green.

### Step 4: Gates and report

12. `make lint`, `make type` (**post-commit only**), `make test`,
    `make test-boundaries`, `make plans-ledger-check`.
13. In NOTES, state the gitleaks versions verified and the exact commands.

**Verify**: all exit 0.

## Test plan

- New `tests/scripts/test_security_gate.py` cases: 8.30 record parses
  path/rule/secret; path allowlist; secret allowlist; malformed entry policy;
  version-shape equivalence.
- Manual falsifiability check (Step 3.9) with a synthetic finding.

**Verify**: `make test && make type` green; the new tests fail if the key
normalization is reverted.

## Done criteria

All must hold:

- [ ] 8.30.1 scan → `no leaks found`; 8.18.1 scan → `no leaks found`
- [ ] `security_gate.py gitleaks` on a synthetic HIGH report → exit 1
- [ ] `security_gate.py gitleaks` on the real report → exit 0 with `rule_id` populated in the synthetic case
- [ ] `tests/scripts/test_security_gate.py` passes and fails if normalization is reverted
- [ ] `.gitleaks-baseline.json` has 4 entries; `git diff` is a clean removal
- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] `git diff --name-only main...HEAD` lists exactly the four in-scope files
- [ ] `plans/README.md` row 160 updated by the reviewer; ledger check OK

## STOP conditions

- The canary match is **not** a fixture value (read the line; if it looks like
  a real credential, stop, do not allowlist, and report `file:line` only).
- 8.18.1 and 8.30.1 cannot both be made green by the path allowlist + parser
  fix (e.g. 8.30 reports additional different findings) → report the
  differences; do not add per-commit baseline entries blindly.
- The gate's existing tests/fixtures expect the old (broken) key handling in a
  way that would force weakening a real assertion → report.
- Any change would make the gate **pass on a synthetic real secret** (Step 3.9
  fails) → stop.

## Maintenance notes

- **Baseline entries are version-sensitive.** Regenerate/refresh with the
  **pinned CI binary**, not the local one, and delete entries once their file
  is allowlisted. The tracked `./gitleaks` (8.18.1) is stale; plan 150 removes
  it — until then, verify a baseline change with **both** versions.
- **Reviewer should scrutinise**: no allowlist broadening beyond the one fixture
  path; the parser change does not default missing fields to "allowlisted";
  the synthetic-secret check proves the gate can still fail.
- **Deferred:** pinning `gitleaks` in one place (Python/Toml constant + workflow)
  and a `make gitleaks-baseline-refresh` target. Unblocked by plan 150 (which
  owns the tracked binary and the Makefile DX slot).
