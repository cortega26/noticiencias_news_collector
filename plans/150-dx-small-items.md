# Plan 150: Four small DX fixes (hooks, healthcheck job, scripts index, PR e2e run)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- CONTRIBUTING.md .pre-commit-config.yaml Makefile .github/workflows/e2e.yml .github/workflows/ci.yml scripts/ docs/RUNBOOK_LOCAL_DEV.md docs/ci.md gitleaks`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S-M (four independent items)
- **Risk**: LOW (deleting the committed binary is git-reversible; MD risk on the e2e workflow narrowing)
- **Depends on**: none; **sequence against plans 138/139/142/143/144/145** for the
  shared Makefile/CI files
- **Category**: dx
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

1. **The documented hook install never installs the secret scan.** `CONTRIBUTING.md:17-20`
   says only `pre-commit install`, but the gitleaks hook is declared
   `stages: [pre-push]` (`.pre-commit-config.yaml:55-64`), so it never runs
   unless the developer also runs `pre-commit install --hook-type pre-push`.
   No doc carries that command. Separately, the repo tracks a **6.9 MB
   `gitleaks` 8.18.1 binary** at the root that no Makefile target, doc, or script
   references, while CI installs **8.30.1**.
2. **A PR job that cannot fail gates the build.** `ci.yml`'s `healthcheck` job
   runs the collector healthcheck against an empty DB (no database is tracked;
   `DatabaseManager` creates the schema), where the ingest check returns `warn`
   and `healthy = all(status != "fail")` — so both thresholds are unreachable —
   yet `build-artifacts` lists it in `needs`.
3. **`scripts/` has no entrypoint map, and a "migrations" directory applies raw
   DDL to a stale DB file.** 33 of ~91 tracked scripts are referenced by nothing
   (Makefile, workflows, docs, other scripts), there is no index, and
   `scripts/migrations/20250930_optimize_indexes.py:17` resolves
   `NEWS_DB_PATH` or `data/news.db` — while the committed config uses
   `data/news_v3.db` (`config.toml:18`). A newcomer grepping "migrations" finds a
   path that can add columns to a file the app no longer reads.
4. **A live, unfiltered collection across all 58 sources runs on every PR.**
   `.github/workflows/e2e.yml` triggers on every `pull_request` with no `paths:`
   filter and runs `scripts/run_collector.py --dry-run --export-json output.json`
   (no `--sources`), then validates the export requires ≥ 1 article. PR colour
   depends on third-party feeds, and the job asserts nothing about the diff.
   `docs/ci.md:103-104` still calls it the legacy workflow and it is absent from
   the omissions list at `docs/ci.md:14-19`.

## Current state

- `.pre-commit-config.yaml:55-64` — the `gitleaks-push` hook, `stages: [pre-push]`,
  `entry: gitleaks detect …`, `language: system`, `always_run: true`.
- `git ls-files -s gitleaks` → mode `100755`, tracked blob; `./gitleaks version`
  → `8.18.1`. CI pin: `GITLEAKS_VERSION="8.30.1"` in
  `.github/workflows/quality.yml:44-58`.
- `Makefile:329-334` — the local security leg's gitleaks branch (plan 138 changes
  its failure behaviour; this plan only touches the docs/binary).
- `.github/workflows/ci.yml:261-288` — the `healthcheck` job and
  `build-artifacts.needs`; `scripts/healthcheck.py:140-164` — `warn` when
  `latest_ingest is None`, `healthy = all(check.status != "fail" …)`.
- `.github/workflows/e2e.yml:3-8` (triggers, no `paths:`), `:16`
  (`timeout-minutes: 15`), `:30-34` (the dry run + export validation);
  `scripts/run_collector.py:198` ("Procesando todas las N fuentes") when no
  filter is passed; `news_collector/config/sources.yaml` defines 58 sources.
- `scripts/` — 91 tracked files; no index (`git ls-files scripts | grep -iE
  "readme|index"` finds only `scripts/debugging/README.md`);
  `scripts/migrations/20250930_optimize_indexes.py:17`
  `DB_PATH = Path(os.getenv("NEWS_DB_PATH", ROOT / "data" / "news.db"))`, with
  `DROP INDEX IF EXISTS`/`ALTER TABLE … ADD COLUMN`/`PRAGMA optimize`
  (`:27-29,53-55,87`) and no Alembic counterpart.

## Commands you will need

| Purpose           | Command                                              | Provenance | Expected on success           |
|-------------------|------------------------------------------------------|------------|-------------------------------|
| Install/baseline  | `make bootstrap`                                     | declared   | exit 0                        |
| Lint              | `make lint`                                          | declared   | exit 0                        |
| Docs gates        | `make docs-check`                                    | declared   | exit 0                        |
| Inventory         | `make inventory-refresh && make inventory-check`     | declared   | exit 0                        |
| Ledger            | `make plans-ledger-check`                            | declared   | `validate_plans_ledger: OK`   |

Provenance: all `declared`. Note for the e2e item: the advisor did not run the
workflow (no network runs).

## Scope

**In scope**:

- `CONTRIBUTING.md` (hook install instructions)
- `gitleaks` (the tracked binary — delete)
- `.github/workflows/ci.yml` (healthcheck job naming/needs)
- `Makefile` + `docs/runbooks/healthcheck.md` (only if the job's meaning changes)
- New: `scripts/README.md` (the index)
- `scripts/migrations/20250930_optimize_indexes.py` (header warning only)
- `.github/workflows/e2e.yml` (narrow the run and/or add a paths filter)
- `docs/ci.md`, `docs/RUNBOOK_LOCAL_DEV.md` (where they describe these)

**Out of scope** (do NOT touch):

- Deleting or refactoring any script beyond the header warning (a prior pass
  deferred dead-script consolidation — do not re-litigate it).
- The healthcheck's thresholds or semantics beyond naming/needs (that is the
  point of the job's smoke role).
- `scripts/security_gate.py` and the pre-push hook's own definition.

## Git workflow

- Branch: `advisor/150-dx-small-items`
- One commit per item; conventional commits, e.g.
  `chore(dx): document the pre-push hook and drop the stale gitleaks binary (plan 150)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make docs-check`. Red baseline → STOP.

**Verify**: all exit 0.

### Step 1: Install the hooks the docs assume (item 1)

1. Replace `CONTRIBUTING.md`'s install instruction with both hook types:

```bash
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

   and note that `gitleaks` must be on `PATH` (point at the CI pin
   `GITLEAKS_VERSION` in `quality.yml` for the version).
2. Delete the tracked root binary: `git rm gitleaks`. Verify nothing references it
   (`grep -rn "gitleaks" Makefile .github/ scripts/ docs/ tools/ | grep -v "command -v gitleaks\|GITLEAKS_VERSION\|gitleaks detect\|gitleaks.json"`).
3. Add `gitleaks` to `.gitignore` (so a locally downloaded copy is not committed
   again). If `.gitignore` is out of your comfort zone, say so instead.

**Verify**: `git ls-files gitleaks` → empty; `make lint` → exit 0;
`make inventory-refresh && make inventory-check` → exit 0.

### Step 2: Make the healthcheck job honest (item 2)

4. Pick the minimal honest change and state it in the workflow's step name:
   - **Preferred:** rename the job to reflect what it proves on CI
     (e.g. `healthcheck-smoke` with a step note "empty DB: verifies the healthcheck
     can run") **and** remove it from `build-artifacts.needs` (the build should not
     wait on a job that cannot fail).
   - Alternative (only if you want the thresholds to be real): seed a fixture DB
     with rows that trip each check and assert exit 1 — that is a bigger change;
     if you take it, add the fixture and prove both branches.
5. Update `docs/ci.md`'s job list and `docs/runbooks/healthcheck.md` if the
   naming/meaning changed.

**Verify**: YAML parses; `grep -n "healthcheck" .github/workflows/ci.yml docs/ci.md` → consistent.

### Step 3: Index the scripts and flag the DDL footgun (item 3)

6. Create `scripts/README.md`: a short index grouped by purpose (collector/
   ops/dev/evaluation/migrations/historical), one line per script or group, and a
   "how to find things" header. Do not attempt to document all 91 individually —
   group them, list the ones referenced by the Makefile/workflows/docs
   individually, and put the rest under a "one-off / historical" section.
7. Add a loud header warning to `scripts/migrations/20250930_optimize_indexes.py`:
   it is **not** the migration path (Alembic is), it targets the legacy
   `data/news.db` (the app uses `data/news_v3.db`), and it must not be run against
   production data. List it in `scripts/README.md` under historical one-offs.
   Do not move or delete it in this plan.
8. Link `scripts/README.md` from `docs/INDEX.md` (one row) and from
   `CONTRIBUTING.md`'s "where things live" region if one exists.

**Verify**: `ls scripts/README.md`; `make docs-check` → exit 0;
`make inventory-refresh && make inventory-check` → exit 0.

### Step 4: Stop running a live collection on every PR (item 4)

9. Narrow the workflow so it stops depending on the whole internet on every PR:
   - add a `paths:` filter to the `pull_request` trigger limited to the collector/
     contract/export surface (`news_collector/collectors/**`,
     `news_collector/contracts/**`, `news_collector/system/**`,
     `scripts/run_collector.py`, `scripts/validate_export.py`,
     `news_collector/config/sources.yaml`, the workflow itself);
   - pass an explicit small source list to the dry run, e.g.
     `--sources` with **three** sources verified to exist in `sources.yaml` and to
     be tier A / not scrapling/headless (prefer fast RSS sources), so the job's
     cost and flake surface shrink;
   - keep the export validation as-is (a zero-article export must still fail).
10. Update `docs/ci.md`: move the workflow out of the "legacy" description and
    document its narrowed scope and that it is required on its paths.

**Verify**: YAML parses; the three source ids exist
(`.venv/bin/python -c "import yaml;d=yaml.safe_load(open('news_collector/config/sources.yaml'));print([s for s in ['<id1>','<id2>','<id3>'] if s in d])"`).
Record the chosen ids and the reason (tier/strategy) in the ledger row.

## Test plan

- No Python tests: docs/workflow changes only. Verifications are the YAML parse,
  the inventory/docs gates, and the source-id existence check.
- Optional: if `tests/test_run_collector_smoke.py` asserts the CLI's
  no-filter behaviour, ensure it still passes (do not change the CLI).

**Verify**: `make lint && make docs-check && make inventory-check && make test` (the
last only if you touched anything importable) → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make docs-check` exit 0
- [ ] `CONTRIBUTING.md` documents both hook types and the gitleaks requirement
- [ ] `git ls-files gitleaks` empty; `make inventory-check` exits 0 after refresh
- [ ] The healthcheck job's name/needs reflect what it can prove; docs agree
- [ ] `scripts/README.md` exists, is indexed from `docs/INDEX.md`, and lists the DDL script as historical
- [ ] `scripts/migrations/20250930_optimize_indexes.py` carries the warning header
- [ ] `e2e.yml` has a `paths:` filter and an explicit ≤ 3-source list; ids recorded
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (+ inventory baseline)
- [ ] `plans/README.md` row 150 updated; `make plans-ledger-check` → OK

## STOP conditions

- The chosen sources do not exist or are scrapling/headless (would keep the
  flake cost) → pick different ids and report the change.
- Narrowing `e2e.yml` breaks a required branch-protection check the operator
  relies on → report; a `paths:`-filtered required check can leave PRs "pending".
  Confirm by reading `.github/` (and, if available, the branch-protection docs)
  before shipping; if you cannot confirm, prefer keeping the workflow unfiltered
  and only narrowing the source list, and say why.
- Deleting the binary breaks a local workflow you find evidence of (a doc telling
  people to run `./gitleaks`) → update the doc instead of leaving both.

## Maintenance notes

- `scripts/README.md` is a maintained index: new scripts should be added there in
  the same PR (mention it in `CONTRIBUTING.md` if you touch that file).
- Reviewer should scrutinise: that the narrowed e2e job still exercises the export
  contract end to end, and that the healthcheck change does not silently drop a
  required-check signal the operator wants.
- **Deferred:** a repo-wide root-debris sweep (`latest-log.txt`,
  `openai_debug.html`, `output/`, `security_status.txt`, `temp_*_data/`) —
  recorded in plan 146's maintenance notes; needs an operator decision.
