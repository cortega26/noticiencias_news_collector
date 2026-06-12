# Plan 007: Remove the redundant, divergent `setup.py` (single-source packaging on `pyproject.toml`)

> **Executor instructions**: Follow step by step; verify each step. Honor STOP
> conditions. Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- setup.py pyproject.toml Makefile`
> If any changed, re-confirm the excerpts before acting; on a structural
> mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED (packaging change — verify the build before and after)
- **Depends on**: none
- **Category**: migration (deps/packaging)
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

The project declares dependencies in **two** places that disagree:

- `pyproject.toml` is the real build source: `[build-system]` uses `setuptools.build_meta`, `[project]` lists 28 pinned dependencies, and the version is dynamic from `news_collector/config/VERSION`.
- `setup.py` redeclares a **different, looser** 8-package list and includes **`aiohttp>=3.9.0`, which is never imported anywhere** in `news_collector/` (a phantom dependency). It omits 20+ real dependencies (fastapi, httpx, sqlalchemy, scikit-learn, alembic, …).

Modern tooling builds from `pyproject.toml`, so the wheel is fine — but the stray `setup.py` is a correctness trap: anything that reads it (older tooling, a contributor running `pip install .` on a stale path, a human reading deps) gets wrong information, and the phantom `aiohttp` invites confusion. Removing `setup.py` makes `pyproject.toml` the single source of truth.

## Current state

```python
# setup.py (entire dependency block)
install_requires=[
    "aiohttp>=3.9.0",      # <-- phantom: not imported anywhere in news_collector/
    "feedparser>=6.0.0",
    "requests>=2.0.0",
    "tenacity>=8.0.0",
    "loguru>=0.7.0",
    "sqlalchemy>=2.0.0",
    "pydantic>=2.0.0",
    "pyyaml>=6.0.0",
]
```

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "noticiencias-news-collector"
dynamic = ["version"]
dependencies = [ "feedparser>=6.0.12", "requests>=2.32.5", ... 28 entries ... ]

[tool.setuptools.dynamic]
version = {file = "news_collector/config/VERSION"}
```

Confirmations to run yourself:
- `aiohttp` unused: `grep -rn "import aiohttp\|from aiohttp" news_collector/ scripts/ apps/ tools/` → no matches.
- The build uses pyproject: `grep -n "build-backend\|MYPY\|build" Makefile | grep -i build` and read the `build:` target (`make build` → "Produce a wheel artifact in dist/ using pinned dependencies").

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Phantom dep check | `grep -rn "import aiohttp\|from aiohttp" news_collector/ scripts/ apps/ tools/` | no matches (exit 1) |
| Build a wheel (baseline & after) | `make build` | exit 0, wheel appears in `dist/` |
| Public entrypoints test | `.venv/bin/pytest tests/test_public_entrypoints.py -q` | all pass |
| Lint | `make lint` | exit 0 |

## Scope

**In scope:**
- Delete `setup.py`
- If `make build` or any doc references `setup.py`, update those references (search first)

**Out of scope:**
- Changing `pyproject.toml` dependency pins.
- Adding `aiohttp` to pyproject (it is genuinely unused — do not add it).
- Touching `requirements*.txt` / lockfiles.

## Git workflow

- Branch: `advisor/007-remove-setup-py`
- One commit; `chore(build): …` style.
- Do NOT push or open a PR.

## Steps

### Step 1: Establish the build baseline (before deleting)

Run `make build` and confirm it currently produces a wheel in `dist/`. Note the wheel filename. This proves the build does not depend on `setup.py`.

**Verify:** `make build` → exit 0; `ls dist/*.whl` shows a wheel.

### Step 2: Confirm nothing references `setup.py`

```bash
grep -rn "setup\.py" Makefile .github/ docs/ scripts/ README.md CLAUDE.md 2>/dev/null
```

Note every hit. CI bootstrap, docs, or the Makefile may mention it. If a reference is just informational (a doc sentence), update it to point at `pyproject.toml`. If a **build step actually invokes `python setup.py …`**, that is a STOP condition (the build is not fully migrated) — report it instead of deleting.

**Verify:** you have reviewed every `setup.py` reference and none is an active build invocation.

### Step 3: Delete `setup.py`

Remove the file. Update any informational references found in Step 2 to reference `pyproject.toml`.

### Step 4: Re-verify the build and tests

**Verify:**
- `make build` → exit 0, wheel produced (same as baseline).
- `.venv/bin/pytest tests/test_public_entrypoints.py -q` → all pass (these tests guard importability of the package).
- `make lint` → exit 0.

## Test plan

No new unit test is strictly required. The regression guard is `make build` succeeding without `setup.py` plus the public-entrypoints test. If the repo has a packaging/metadata test, run it; otherwise the build is the proof.

## Done criteria

ALL must hold:

- [ ] `setup.py` no longer exists (`test ! -f setup.py`)
- [ ] `make build` exits 0 and produces a wheel in `dist/`
- [ ] `grep -rn "import aiohttp" news_collector/ scripts/ apps/ tools/` → no matches (the phantom dep is gone with the file and was never used)
- [ ] No remaining doc/CI reference instructs running `python setup.py`
- [ ] `.venv/bin/pytest tests/test_public_entrypoints.py -q` → all pass
- [ ] `make lint` exits 0
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Any CI workflow or Makefile target **invokes** `python setup.py …` (e.g. `sdist`, `develop`) — the build still depends on it; deleting would break CI. Report which step.
- `make build` fails after deletion (unexpected — pyproject should suffice).
- `pyproject.toml` lacks a working `[build-system]`/`[project]` (drift) — without it, deleting `setup.py` removes the only build metadata.

## Maintenance notes

- After this, `pyproject.toml` is the single source of dependency truth; new deps go only there.
- A reviewer should confirm the wheel built from pyproject contains the right metadata (name/version) and that no install instructions still mention `setup.py`.
- The separate `requirements.txt` ↔ `pyproject.toml` relationship (lockfile provenance) is a known doc-clarity item but is **not** part of this plan.
