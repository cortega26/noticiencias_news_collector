# Plan 130: Backend dependency hygiene (drop dead deps, retire drifted manifest, pin serving)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- pyproject.toml requirements.txt requirements.lock requirements-security.lock requirements-refinery.lock scripts/sync_lockfiles.py scripts/setup/check_env.py scripts/generate_inventory.py Dockerfile.serving Dockerfile apps/refinery/requirements.txt`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: migration
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

Three dependency-hygiene defects, one of them load-bearing for the
publicly-exposed tier: the serving image (webhook tier behind Cloudflare
Tunnel, per the file's own security comment) builds from bare
`pip install .` — unpinned, unhashed — while the collector image pays for
hash-pinning per ADR-0002, so a compromised/yanked upstream release can
enter exactly the public tier; `requirements.txt` claims to be generated
but no generator produces it, and it has drifted (older click/lxml,
missing Postgres driver + multipart) so anyone provisioning from it gets a
silently wrong runtime; and two declared dependencies (`toml`, abandoned
2020, superseded by stdlib `tomllib`; `schedule`, scheduler nobody calls)
are statically unimported yet widen CVE surface for zero benefit.
Risk is MED only for the image rebuild path (needs a serving smoke test).

## Current state

Facts (all verified 2026-10-11):

```dockerfile
# Dockerfile.serving:4,25 — floating base + unpinned install (public tier)
FROM python:3.13-slim
...
RUN pip install --no-cache-dir .
# vs Dockerfile:11-14 — hash-pinned (collector):
COPY requirements.lock requirements-security.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
 && pip install --no-cache-dir --require-hashes -r requirements-security.lock
# Serving sets NOTICIENCIAS__APP__ENVIRONMENT=production (fail-closed) — preserve it.
# .python-version pins 3.13.12; both images float on 3.13-slim.
```

```txt
# requirements.txt:1-8 header claims generation by scripts/sync_lockfiles.py,
# whose LOCK_TARGETS compile only the three .lock files — nothing regenerates it.
# Drift: click>=8.3.0 (pyproject:29 → >=8.3.3); lxml>=6.0.2 (pyproject:13 → >=6.1.0);
# psycopg[binary]>=3.2.0 and python-multipart>=0.0.20 absent entirely.
# Pointers: scripts/setup/check_env.py:28 ("pip install -r requirements.txt");
# scripts/generate_inventory.py:193 inventories it.
# apps/refinery/requirements.txt orphaned (zero references; superseded by
# requirements-refinery.lock per Makefile).
```

```toml
# pyproject.toml:18 "schedule>=1.2.2"; :33 "toml>=0.10.2" (+ :48 refinery also lists toml)
# No `import toml`/`import schedule` in news_collector/, scripts/, apps/,
# tools/, noticiencias/, tests/ (only prose comment in config/sources.yaml:880;
# only stdlib tomllib + tomli_w in code; PyYAML in ~15 files).
# scripts/setup/check_env.py:9 lists "toml" as required.
```

Repo conventions: ADR-0002 (hash-pinned lockfiles); dependency/security
changes are Critical class → baseline + `make quality`; `make quality-gate`
needs no LLM (`quality-gate-refresh` overwrites snapshots — never run it).

Negative evidence (do not re-audit): `pip-audit` on the main lock is clean
(exit 0, zero advisories at audit time); Alembic is one linear chain
(single head); `starlette==1.6.0` covers the historic Range-header CVE;
runtimes current (Python 3.13.12, supported to 2029).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Quality   | `make quality`           | declared   | exit 0              |
| Serving smoke | `make serve` + `/healthz` probe (or the repo's serving smoke — verify target first) | declared | 200 + fail-closed auth behavior |

## Scope

**In scope** (the only files you should modify):

- `pyproject.toml` (drop `toml`, `schedule` lines)
- `requirements.lock`, `requirements-security.lock`,
  `requirements-refinery.lock` (regen via `scripts/sync_lockfiles.py` —
  verify it regenerates all three first)
- `requirements.txt`, `apps/refinery/requirements.txt` (delete, or
  regenerate-then-freeze — deletion preferred; see Step 2)
- `scripts/setup/check_env.py` (drop `"toml"`; repoint install hint at
  lock-based bootstrap)
- `scripts/generate_inventory.py` (update the requirements.txt reader)
- `Dockerfile.serving` (hash-pinned install; base digest pin)

**Out of scope** (do NOT touch, even though they look related):

- Dependency version bumps beyond the removals (no upgrades in this plan).
- `Dockerfile` (collector — already pinned).
- Four-way HTTP-client overlap (`requests`/`httpx`/scrapling/playwright) —
  each tier load-bearing, consolidation L/HIGH risk: verdict is a one-line
  boundary rule for new network code (add to the serving/collector module
  docstring or `docs/AGENTS.md`? NO — docs/AGENTS.md is plan-081-owned;
  put the one-liner in the executor's commit message + this plan's notes,
  and propose the doc line to 081). Do NOT migrate.
- `lunr`-style watch items — frontend concern (plan 010 notes).

## Git workflow

- Branch: `advisor/130-backend-deps`
- Commit per step (removals, manifest retirement, serving pin).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline

Run `make lint && make type && make test`. Verify
`scripts/sync_lockfiles.py` regenerates the three locks (read
LOCK_TARGETS; dry-run if supported). Verify no workflow references the two
`.txt` manifests except the two known pointers
(`grep -rn "requirements.txt" .github/ Makefile scripts/ | grep -v ".lock"`).

**Verify**: gates green; regen path + pointer census recorded.

### Step 1: Drop toml and schedule

Remove both lines from `pyproject.toml` (+ the refinery-extras `toml`
line at `:48` if it mirrors the same dead dep — verify it's equally
unimported first). Regen all three locks. Drop `"toml"` from
`check_env.py`'s required list.

**Verify**: `grep -rn "^import toml\|^from toml\|^import schedule\|^from schedule" news_collector/ apps/ scripts/ tests/ tools/` empty (post-change proof);
`pip install --require-hashes -r requirements.lock --dry-run` (or the
repo's equivalent check) resolves; `make test` passes.

### Step 2: Retire requirements.txt files

Preferred: delete `requirements.txt` and `apps/refinery/requirements.txt`;
repoint `check_env.py:28` at the lock-based bootstrap (`make bootstrap`);
update `generate_inventory.py:193` reader. Alternative (only if a consumer
found in Step 0 needs the file): regenerate-then-freeze from the lock and
document the regen command in the header — report the choice.

**Verify**: no remaining references to the deleted files
(`grep -rn "requirements.txt" .github/ Makefile scripts/ docs/`
excluding `.lock` and historical docs); `make lint` passes.

### Step 3: Pin the serving image

`COPY requirements.lock` (+ security lock if the serving stage needs it —
prune to the serving-needed subset ONLY if image size is a documented
concern; default to the full lock) and switch to
`pip install --require-hashes -r requirements.lock`. Pin the base image
digest (resolve `python:3.13-slim` digest at build time; record it).
Preserve the `NOTICIENCIAS__APP__ENVIRONMENT=production` fail-closed env.
Rebuild the serving image and run the serving smoke test (`/healthz` +
webhook/admin no-token → fail-closed per the file's ENV comment).

**Verify**: image builds; smoke test passes (health 200, unauthenticated
admin/webhook refused); `git diff` on Dockerfile.serving shows only the
COPY/install/digest lines + preserved ENV.

### Step 4: Full gates

Run `make lint && make type && make test && make quality`.

**Verify**: all green.

## Test plan

- Post-change unimported proof (grep, Step 1).
- Lock-install resolution check (hashes satisfied).
- Serving image build + smoke (health + fail-closed).
- Verification: `make test` + `make quality` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n '"toml\|schedule' pyproject.toml` returns no dependency matches (comments/docs excluded)
- [ ] `requirements.txt` + `apps/refinery/requirements.txt` deleted (or regenerated+frozen with documented regen)
- [ ] `Dockerfile.serving` installs with `--require-hashes` and a pinned base digest
- [ ] Serving smoke passes (health 200, fail-closed auth)
- [ ] `make lint && make type && make test && make quality` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Any unknown consumer of `requirements.txt` surfaces in Step 0 (regenerate path instead of delete).
- The serving subset-prune breaks imports (use the full lock — size is not this plan's problem).
- Base-digest pinning breaks the container build pipeline (report the
  pipeline constraint; keep the `--require-hashes` half).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- New dependencies must land in `pyproject.toml` + regen'd locks in the
  same PR (the deleted `.txt` must never be resurrected as a side channel).
- The serving image now pins like the collector — keep the two Dockerfiles'
  install stanzas in sync on future lock changes.
- **Deferred:** four-client HTTP overlap (rule-only verdict above);
  `lodash`-override vestige in frontend (not worth a finding).
