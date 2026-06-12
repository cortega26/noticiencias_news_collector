# Plan 001: Remove live secrets from `config.toml` and load them from the environment

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- config.toml .env.example`
> If `config.toml` changed since this plan was written, re-confirm the line
> numbers of the `[github]` and `[nvidia]` sections before editing — they may
> have shifted. A line-number mismatch is not a STOP, but a structural change
> (sections removed/renamed) is.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (code) / the real-world exposure is CRITICAL and is handled by the operator, not this plan
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

`config.toml` is tracked in git and contains a **live GitHub token** (`config.toml:477`, a `ghp_…` value) and a **live NVIDIA API key** (`config.toml:496`, an `nvapi-…` value). They are present in `HEAD` and across ~51 commits of history. Anyone with repo access — or anyone who ever cloned it — has both credentials. This plan removes them from the working tree and makes the app load them from the environment instead. **Deleting the values does not undo the exposure**: the secrets remain valid and readable in git history until the operator rotates them and (optionally) purges history. Those two actions are explicitly out of scope for the executor (see STOP conditions).

## Current state

The config loader already supports environment overrides — **no loader code change is needed.**

- `noticiencias/config_manager.py:485-524` — `load_config()` merges layers in order: defaults → `config.toml` (file) → `.env` → process env. **Later layers win**, so an env var overrides the file value.
- `noticiencias/config_manager.py:403-419` — `_legacy_env_key_map()` maps flat vars to nested paths, including `"GITHUB_TOKEN": "github.token"`. So `GITHUB_TOKEN=…` in the environment populates `config.github.token`.
- There is **no** flat alias for the NVIDIA key, so it must be set with the nested form: `NOTICIENCIAS__NVIDIA__API_KEY=…` (double-underscore between prefix, section, and key). `.env.example:53` already documents this exact variable as a comment.
- `config.toml` is the **entire runtime config** (sections `[app] [scoring] [enrichment] …` — see `grep '^\[' config.toml`), not just secrets. **Do NOT gitignore or delete the file.** Only blank the two secret values.

Secret-bearing lines today (values redacted here on purpose — you will see the real values in the file):

```toml
# config.toml
[github]
token = "ghp_…"      # line 477  → must become  token = ""
...
[nvidia]
api_key = "nvapi-…"  # line 496  → must become  api_key = ""
```

Consumer behavior after blanking (confirmed, no change needed):
- `news_collector/infrastructure/llm/factory.py:244-245` — `if nvidia_api_key:` treats `""` as falsy, so with no env set the NVIDIA provider is simply skipped and the system falls back to Gemini/Ollama. Safe.
- `news_collector/components/publishing/github_publisher.py:51` — already reads `os.environ.get("GITHUB_TOKEN", "")` as a fallback.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Drift check | `git diff --stat b30248f..HEAD -- config.toml` | (see drift note) |
| Confirm secrets gone from tree | `grep -nE 'ghp_[A-Za-z0-9]|nvapi-[A-Za-z0-9]' config.toml` | exit 1, **no matches** |
| Config still loads | `make config-validate` | exit 0 |
| Env override works | see Step 3 snippet | prints `RESOLVED` |
| Lint | `make lint` | exit 0 |

## Scope

**In scope** (the only files you should modify):
- `config.toml` — blank the two secret values only
- `.env.example` — document the two variables

**Out of scope** (do NOT touch):
- `noticiencias/config_manager.py` — the loader already supports env overrides
- `news_collector/infrastructure/llm/factory.py`, `github_publisher.py` — already env-aware
- Every other section of `config.toml` — leave byte-for-byte unchanged
- **Git history rewriting** (`git filter-repo`, BFG, force-push) — operator action, see STOP
- **Credential rotation** — operator action, see STOP

## Git workflow

- Branch: `advisor/001-externalize-secrets`
- One commit; message style matches repo (`chore(security): …`).
- Do NOT push or open a PR.

## Steps

### Step 1: Blank the GitHub token in `config.toml`

On line 477 (`[github]` section), replace the entire quoted token value after `token =` with an empty string, so the line reads exactly:

```toml
token = ""
```

### Step 2: Blank the NVIDIA API key in `config.toml`

On line 496 (`[nvidia]` section), replace the entire quoted key value after `api_key =` with an empty string:

```toml
api_key = ""
```

**Verify (Steps 1–2):** `grep -nE 'ghp_[A-Za-z0-9]|nvapi-[A-Za-z0-9]' config.toml` → exit code 1 (no matches).

### Step 3: Document the env vars in `.env.example`

`.env.example:53` already has a commented `# NOTICIENCIAS__NVIDIA__API_KEY=…` line — leave it. Add a GitHub token entry near the other commented vars (the project's flat-alias convention), e.g.:

```bash
# GitHub publishing token (flat alias → config.github.token). Required to open PRs.
# GITHUB_TOKEN=ghp_your_token_here
```

Keep it commented so the example file never holds a real value.

**Verify:** `grep -c 'GITHUB_TOKEN' .env.example` → at least `1`.

### Step 4: Confirm the env override still resolves the secret at runtime

Run this read-only snippet (uses a dummy value, never a real secret):

```bash
NOTICIENCIAS__NVIDIA__API_KEY=dummy-test-value \
.venv/bin/python -c "from noticiencias.config_manager import load_config; c=load_config(); print('RESOLVED' if getattr(c.nvidia,'api_key','')=='dummy-test-value' else 'FAIL')"
```

**Verify:** prints `RESOLVED`. If it prints `FAIL`, the loader did not apply the env override — STOP and report (do not edit the loader).

### Step 5: Validate config and lint

**Verify:** `make config-validate` → exit 0; `make lint` → exit 0.

## Test plan

No new automated test is required (this is config hygiene), but Step 4 is the behavioral proof that env override works. If you want to harden it, add a test in `tests/test_config_manager.py` that sets `NOTICIENCIAS__NVIDIA__API_KEY` in a monkeypatched env and asserts `load_config().nvidia.api_key` equals it — model it after the existing tests in that file. This is optional; do not block the plan on it.

## Done criteria

ALL must hold:

- [ ] `grep -nE 'ghp_[A-Za-z0-9]|nvapi-[A-Za-z0-9]' config.toml` → no matches (exit 1)
- [ ] `config.toml` lines 477 and 496 read `token = ""` and `api_key = ""`
- [ ] Step 4 snippet prints `RESOLVED`
- [ ] `make config-validate` exits 0
- [ ] `make lint` exits 0
- [ ] Only `config.toml` and `.env.example` modified (`git status`)
- [ ] `plans/README.md` status row updated, **with a note that the operator must still rotate both credentials and purge git history**

## STOP conditions

Stop and report back (do not improvise) if:

- The Step 4 snippet prints `FAIL` (loader does not honor the env override — needs investigation, not a loader edit by you).
- `make config-validate` fails after blanking (some code requires a non-empty key at import time — report which).
- You are tempted to rewrite git history or rotate the live keys — **these are operator actions. Do them yourself you must not.** Report that they are pending.

## Maintenance notes

- **For the operator (REQUIRED, not done by this plan):** (1) Rotate the GitHub token and NVIDIA key in their provider dashboards — the committed values are burned. (2) Decide whether to purge them from git history (`git filter-repo --replace-text` or BFG) and force-push; coordinate with anyone who has clones. Until rotation, the secrets are compromised even though the working tree is clean.
- A reviewer should confirm no real secret appears in the diff and that only the two values changed.
- Future secrets (e.g. a Gemini key) must follow the same pattern: blank in `config.toml`, set via `NOTICIENCIAS__<SECTION>__<KEY>` env. Consider a pre-commit secret scan (`scripts/run_secret_scan.py` exists) to prevent recurrence.
