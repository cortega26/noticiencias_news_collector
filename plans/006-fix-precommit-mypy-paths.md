# Plan 006: Fix the pre-commit mypy hook path so it actually checks the targeted files

> **Executor instructions**: Follow step by step; verify each step. Honor STOP
> conditions. Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- .pre-commit-config.yaml Makefile`
> If either changed, re-confirm the excerpts below; on a structural mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

The pre-commit mypy hook is supposed to type-check the same files the Makefile's `MYPY_TARGETS` does. Its `files:` regex points at `src/utils/(logger|url_canonicalizer).py`, but **this repo has no `src/` directory** — those modules live under `news_collector/utils/`. So the hook silently checks only `generate_api_docs.py` and skips both utility modules locally. Type regressions in `logger.py` / `url_canonicalizer.py` slip past the local hook and are only caught later in CI (`make type` does check them). This is a one-line regex fix that restores the intended local feedback loop. Because CI already type-checks these two files (they are in `MYPY_TARGETS`), they are currently type-clean, so the fix will **not** surface a backlog of new errors.

## Current state

```yaml
# .pre-commit-config.yaml:31
        files: ^(scripts/generate_api_docs\.py|src/utils/(logger|url_canonicalizer)\.py)$
```

The real, CI-checked targets (Makefile):

```makefile
# Makefile:176-181
MYPY_TARGETS := scripts/generate_api_docs.py \
    news_collector/utils/logger.py \
    news_collector/utils/url_canonicalizer.py
...
	@$(MYPY) --config-file=pyproject.toml $(MYPY_TARGETS)
```

The files exist at:
- `news_collector/utils/logger.py`
- `news_collector/utils/url_canonicalizer.py`

(`src/utils/...` does not exist — confirm: `ls src/ 2>/dev/null` returns nothing.)

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Confirm no `src/` | `ls src/ 2>/dev/null; echo done` | prints only `done` |
| The two files are type-clean | `make type` | exit 0 |
| Pre-commit config is valid | `.venv/bin/pre-commit validate-config` | exit 0 |
| Hook now matches the files | `.venv/bin/pre-commit run mypy --files news_collector/utils/logger.py news_collector/utils/url_canonicalizer.py` | hook runs (not "no files to check"), passes |

(If `pre-commit` is not installed in `.venv`, install isn't in scope — instead verify the regex by inspection and with the `python` snippet in Step 2.)

## Scope

**In scope:**
- `.pre-commit-config.yaml` — line 31 `files:` regex only

**Out of scope:**
- The Makefile `MYPY_TARGETS` (already correct).
- Expanding mypy coverage to more files (separate, larger effort).
- The hook's other settings (`entry`, `additional_dependencies`, etc.).

## Git workflow

- Branch: `advisor/006-precommit-mypy-paths`
- One commit; `fix(dx): …` / `chore(ci): …` style.
- Do NOT push or open a PR.

## Steps

### Step 1: Correct the regex

Change `.pre-commit-config.yaml:31` from:

```yaml
        files: ^(scripts/generate_api_docs\.py|src/utils/(logger|url_canonicalizer)\.py)$
```

to:

```yaml
        files: ^(scripts/generate_api_docs\.py|news_collector/utils/(logger|url_canonicalizer)\.py)$
```

(Only `src/utils/` → `news_collector/utils/` changes.)

### Step 2: Verify the regex matches the real files

If `pre-commit` is available, run the hook command from the table and confirm it reports running on the two utils files (not "no files to check"). Otherwise verify the regex directly:

```bash
.venv/bin/python -c "import re; p=re.compile(r'^(scripts/generate_api_docs\.py|news_collector/utils/(logger|url_canonicalizer)\.py)$'); \
print(all(p.match(f) for f in ['scripts/generate_api_docs.py','news_collector/utils/logger.py','news_collector/utils/url_canonicalizer.py']))"
```

**Verify:** prints `True`.

### Step 3: Confirm the targeted files type-clean

**Verify:** `make type` exits 0 (this is the same set the hook now mirrors; if it fails, the failure pre-exists and is not introduced by this change — but STOP and report rather than papering over it).

## Test plan

No unit test (this is config). The verification is: (a) regex matches all three target paths, (b) `make type` exits 0, (c) `pre-commit validate-config` passes.

Optionally, add an assertion to an existing config/meta test (e.g. there are tests like `tests/test_config_guardrails.py`) that the pre-commit mypy `files` pattern matches the Makefile `MYPY_TARGETS`. Only do this if such a meta-test pattern already exists; otherwise skip.

## Done criteria

ALL must hold:

- [ ] `.pre-commit-config.yaml:31` references `news_collector/utils/`, not `src/utils/`
- [ ] The Step 2 regex check prints `True`
- [ ] `.venv/bin/pre-commit validate-config` exits 0 (if pre-commit is installed)
- [ ] `make type` exits 0
- [ ] Only `.pre-commit-config.yaml` modified (plus an optional meta-test) (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `make type` fails — the targeted files are not actually clean; report the errors (do not fix unrelated type debt under this plan).
- The hook config has been restructured so line 31 no longer carries the `files:` regex (drift).

## Maintenance notes

- The broader issue (mypy covers only 3 of ~138 `news_collector/` files) is real but out of scope here — it belongs in a staged type-coverage roadmap, not this one-line fix. Note it as deferred.
- A reviewer should confirm the hook and `MYPY_TARGETS` now reference the same files.
