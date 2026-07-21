# Plan 042: Remove tracked frontend runtime artifacts

> **Executor instructions**: Remove only proven generated/runtime files, preserve intentional manifests/fixtures, and verify no code depends on the tracked copies. Update plan 042 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git -C ../noticiencias diff --stat 0cdca74..HEAD -- .gitignore .codegraph/daemon.pid data/logs/collector.log data/news_v3.db scripts tests docs`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: frontend `0cdca74`, 2026-07-21

## Why this matters

The frontend tracks a machine-specific CodeGraph daemon PID, a 60 KB collector runtime log with local paths/process metadata, and a 112 KB SQLite database. They create noisy diffs, leak workstation/runtime context, and blur the boundary between source fixtures and generated state. None is referenced by frontend code.

## Current state

- `git ls-files` identifies exactly `.codegraph/daemon.pid`, `data/logs/collector.log`, and `data/news_v3.db` as artifact-shaped tracked files.
- `.codegraph/daemon.pid` contains a live PID, absolute workspace socket path, version, and start timestamp.
- `data/logs/collector.log` is newline-delimited runtime JSON containing backend paths, process/thread IDs, model calls, and timestamps.
- `data/news_v3.db` is a SQLite runtime database.
- `../noticiencias/.gitignore` ignores build/test outputs and development metrics DBs, but not these three paths/classes.
- Repository search excluding the artifacts finds no source/test/doc references to them.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Tracked audit | `git -C ../noticiencias ls-files | rg '(^|/)(daemon\.pid|.*\.log|.*\.sqlite3?|.*\.db)$'` | no runtime matches; intentional fixtures, if any, are under `tests/fixtures` and documented |
| Ignore check | `git -C ../noticiencias check-ignore -v .codegraph/daemon.pid data/logs/collector.log data/news_v3.db` | all three resolve to explicit ignore rules |
| Full validation | `npm --prefix ../noticiencias run lint && npm --prefix ../noticiencias run validate:content && npm --prefix ../noticiencias run build && npm --prefix ../noticiencias run test:dist && npm --prefix ../noticiencias run test:audit` | exit 0 |

## Scope

**In scope**: untracking/deleting the three identified runtime files, narrow ignore rules for CodeGraph runtime state/logs/databases, optional sanitized minimal fixture only if a real test requires it, and a hygiene check.

**Out of scope**: deleting `data/image-derivatives-manifest.json`, delivery/placeholder allowlists, `src/content/posts/refinery_manifest.json`, content images, source history rewriting, or deleting ignored local copies from every developer machine.

## Git workflow

- Branch: `advisor/042-remove-frontend-artifacts` in the frontend repository.
- Commit example: `chore(repo): remove tracked runtime artifacts`.

## Steps

### Step 1: Prove the files are non-authoritative

Search code, scripts, tests, workflows, and active docs for each exact and basename path. Inspect database tables using a disposable read-only Python `sqlite3` command only to confirm it is runtime state, never to migrate its contents into source.

**Verify**: no consumer requires any tracked copy; if one does, STOP and define a sanitized fixture contract.

### Step 2: Remove and ignore runtime classes narrowly

Untrack the three files. Add explicit rules for `.codegraph/*.pid`, daemon socket/log/database runtime files, `data/logs/`, and runtime DB extensions under `data/`, with negations only for named versioned fixtures/manifests if needed. Avoid a blanket `data/` ignore.

**Verify**: ignore-check command identifies the intended rule for all three; `git ls-files` no longer contains them.

### Step 3: Add a hygiene gate

Extend an existing repository check or add a small script that fails when tracked PID/socket/log/database/cache/build artifacts appear outside approved fixture paths. Test it against a temporary Git index/repository fixture, not by committing junk.

**Verify**: gate passes current tracked files and fails for sample `data/runtime.db`, `.codegraph/daemon.pid`, and `data/logs/x.log` paths.

### Step 4: Validate normal workflows

Run full frontend validation and CodeGraph/tool startup if locally available to ensure ignored runtime files are recreated locally without status noise.

**Verify**: full validation passes and `git status --short --ignored` marks recreated files ignored.

## Test plan

- Hygiene path classifier pass/fail fixtures.
- Ignore behavior for all removed paths and preservation of authoritative `data/*.json` manifests.
- Full frontend lint/content/build/dist/unit checks.

## Done criteria

- [ ] Three runtime artifacts are no longer tracked.
- [ ] Narrow ignore rules prevent recurrence without hiding authoritative data.
- [ ] CI detects future tracked runtime artifacts.
- [ ] Full frontend validation passes.

## STOP conditions

- Stop if a test/runtime requires the database contents; extract a minimal anonymized fixture under `tests/fixtures` with provenance.
- Stop if logs contain credentials or personal data requiring history remediation; report for a separately authorized history-cleaning operation.
- Stop if an ignore rule would hide publication/image manifests.

## Maintenance notes

Generated operational evidence belongs in ignored directories or CI artifacts. Version only deterministic, minimal fixtures with an owning test.

