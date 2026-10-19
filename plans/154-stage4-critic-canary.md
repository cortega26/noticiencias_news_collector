# Plan 154: A bounded Stage-4 critic canary (operational evidence for issue #366)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 736ad5f2..HEAD -- news_collector/components/editorial/ai_editor.py news_collector/components/editorial/editorial_stages.py scripts/ docs/editorial_quality_system.md tests/scripts/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW (a standalone script; no pipeline, DB, or publication side effects)
- **Depends on**: none (resolves GitHub issue #366's tooling gap)
- **Category**: tests / ops evidence
- **Planned at**: commit `736ad5f2`, 2026-10-19

### Decision (2026-10-19) — build the canary; run it local-first

Issue #366 asks for operational evidence of the source-aware Stage-4 critic. It
also states the existing `scripts/llm_canary.py` is **not equivalent** (it
measures `CognitiveScorer.score_batch_async`, not the critic), and that a
technical failure must be recorded as **UNVERIFIED**, never as approval via
fail-open.

So this plan **builds the missing tooling first** (that is the actual blocker),
runs it against the **local provider** (free, and the repo is local-first), and
leaves the cloud run as one documented command. No paid provider call is made by
the executor; the operator can run the same command with cloud keys if they want
evidence against that provider.

## Why this matters

The editorial critic is a publication gate: it decides whether an article is
approved, repaired once, or blocked. PR #365 changed it to a source-aware
critique and was merged on the strength of deterministic tests only — no
real-provider evidence exists that the configured provider returns a parseable
`value_add_assessment` and that the decision path behaves as designed. That is
exactly the class of gap where a mock-tested gate can be hollow in production
(fail-open paths turning "no verdict" into "approved").

The deliverable is a repeatable, sanitized evidence artifact — not a new gate.

## Current state

- `scripts/llm_canary.py` — the existing canary: measures the cognitive scorer's
  batch path and scoring counters. It does **not** call the critic.
- `news_collector/components/editorial/ai_editor.py` — the Stage-4 critic lives
  here (`_critic_editorial_pass`); it consumes a title, the source text and an
  editorial draft, and returns a verdict dict (e.g. `approved`,
  `value_add_assessment`, evidence fields). Read the real signature and the
  response schema before writing the script; do not duplicate prompt strings —
  invoke the real method.
- `news_collector/components/editorial/editorial_stages.py` — stage wiring
  (`EditorialStages`), useful to see how the critic is reached without the full
  pipeline.
- Provider configuration: `config.toml` (`[ollama]`, `[nvidia]`, `[gemini]`) plus
  env overrides; the local Ollama endpoint is `localhost:11434`. API keys, if
  any, live in `.env` — never read, print or persist them.
- Issue #366's acceptance shape: sanitized record with SHA, environment,
  provider/model, transport result, JSON parse/validation result, decision,
  latency, optionally cost; `UNVERIFIED` on provider failure.

## Commands you will need

| Purpose          | Command                                                               | Provenance | Expected on success              |
|------------------|-----------------------------------------------------------------------|------------|----------------------------------|
| Install/baseline | `make bootstrap`                                                      | declared   | exit 0                           |
| Lint             | `make lint`                                                           | declared   | exit 0                           |
| Types + coverage | `make type`                                                           | declared   | exit 0                           |
| Unit suite       | `make test`                                                           | declared   | all pass                         |
| Script tests     | `.venv/bin/pytest tests/scripts -q --no-cov`                           | declared   | all pass                         |
| Local provider   | `curl -s -o /dev/null -w '%{http_code}' http://localhost:11434/api/tags` | declared | `200` when Ollama runs           |
| Canary (local)   | `.venv/bin/python scripts/editorial_critic_canary.py --provider local`  | declared   | exit 0 + sanitized JSON evidence |
| Canary (cloud)   | `.venv/bin/python scripts/editorial_critic_canary.py --provider configured --require-keys` | declared | exit 0 + evidence, or 2 UNVERIFIED |
| Ledger           | `make plans-ledger-check`                                              | declared   | `validate_plans_ledger: OK`      |

Provenance: all `declared`.

## Scope

**In scope**:

- New: `scripts/editorial_critic_canary.py`
- New: `tests/scripts/test_editorial_critic_canary.py` (the evidence-shaping /
  sanitization / exit-code logic — the live call is not unit-tested)
- `docs/editorial_quality_system.md` — a short "operational canary" section
  (command, what it proves, `UNVERIFIED` semantics)
- The issue comment with the evidence (see Step 4; the reviewer posts it)

**Out of scope** (do NOT touch):

- `scripts/llm_canary.py` (different subsystem; leave it alone).
- Any pipeline, DB, or publication path: the script must not create articles,
  write to the database, or open PRs.
- `Makefile` / `ci.yml` / `docs/ci.md` (shared with running plans; a Make target
  is optional and deferred).
- The critic's implementation or prompts.

## Git workflow

- Branch: `advisor/154-stage4-critic-canary`
- Conventional commits, e.g.
  `feat(scripts): bounded Stage-4 critic canary with sanitized evidence (plan 154)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline and probe the providers

`make bootstrap`, `make lint`, `make test`, `tests/scripts`, and the Ollama probe.
Record which provider is reachable **without printing any key** (a boolean
"local reachable" is enough; for cloud, only "keys present: yes/no").

**Verify**: gates green; the probe result recorded.

### Step 1: Read the real critic seam

1. Read `_critic_editorial_pass` and the stage wiring. Record in your report:
   the exact callable the script will use, its inputs, the verdict schema, and
   whether it needs a DB/session (if it does, STOP and report — the script must
   stay side-effect free).
2. Reuse the real prompt/schema construction; do not copy prompt text into the
   script.

**Verify**: the seam is named in your report with `file:line`.

### Step 2: Write the canary

3. `scripts/editorial_critic_canary.py`:
   - synthetic inputs only: a title, a short synthetic source body, and a
     synthetic editorial draft (clearly marked as synthetic);
   - flags: `--provider local|configured` (default `local`), `--require-keys`
     (exit 3 if the configured provider has no credentials), `--timeout`,
     `--json` (default) / `--human`;
   - output: one sanitized JSON object with `status` (`PASS` / `FAIL` /
     `UNVERIFIED`), `git_sha`, `environment`, `provider`, `model`, `transport_ok`,
     `json_parsed`, `verdict_fields` (only the safe keys: `approved`,
     `value_add_assessment`, counts — **never** the prompt or the full response),
     `latency_ms`, `error_kind` on failure;
   - exit codes: `0` PASS, `1` FAIL (a valid verdict that is a hard fail),
     `2` UNVERIFIED (transport/parse failure — **never** treated as approval),
     `3` configuration error;
   - no DB, no file writes outside stdout, no publication.
4. Sanitization is a hard rule: the script must never print prompts, tokens,
   keys, or raw provider responses. Redact anything that looks like a credential.

**Verify**: `.venv/bin/pytest tests/scripts -q --no-cov` → the new tests pass
(they cover the evidence shape, the redaction, and the exit-code mapping with a
fake critic callable).

### Step 3: Run it

5. Run `--provider local`. Record the exact JSON output (it is synthetic, safe to
   paste) and the exit code.
6. If local is unreachable, record `UNVERIFIED` with the reason and the exact
   command for the cloud run; do **not** fabricate a PASS and do not silently
   switch providers.
7. Optionally run `--provider configured` **only if** keys are present and the
   operator's budget is acceptable — the reviewer has not authorised a paid call,
   so default to not running it and say so.

**Verify**: the recorded JSON + exit code.

### Step 4: Document and hand the evidence to the issue

8. Add the short section to `docs/editorial_quality_system.md`: what the canary
   proves, how to run it (local and cloud), and the `UNVERIFIED` rule.
9. Put the sanitized evidence (command, exit code, JSON) in your report; the
   reviewer will post it on issue #366 and close it **only** on a PASS.

**Verify**: `make docs-check` exits 0.

## Test plan

- `tests/scripts/test_editorial_critic_canary.py`: evidence shape, redaction of
  key-looking strings, exit-code mapping (PASS/FAIL/UNVERIFIED/config error) with
  an injected fake critic; no network.
- The live run is manual evidence, not a unit test.

**Verify**: `make test` green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test` exit 0
- [ ] `scripts/editorial_critic_canary.py` exists, has the flags and exit codes above, and makes no DB/publication side effects
- [ ] Redaction test proves no key-looking string can reach stdout
- [ ] A real run is recorded: either a PASS against the local provider, or an honest UNVERIFIED with the exact reason and the cloud command
- [ ] `docs/editorial_quality_system.md` documents it; `make docs-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 154 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- The critic cannot be invoked without a DB/session or other stateful side
  effects → STOP and report the seam; do not fake it with a reimplementation.
- The configured provider's response schema differs from what the critic parses
  (e.g. no `value_add_assessment`) → report it as the likely finding (this is
  exactly what the canary exists to detect) and do not "fix" the critic here.
- Running the local provider requires pulling a model (large download / no
  network) → record UNVERIFIED and stop; do not start downloads.
- The script would need to read `.env` directly to work → STOP; configuration
  belongs to the app's config layer, and the script must not handle secrets.

## Maintenance notes

- The canary is evidence, not a gate: do **not** wire it into CI as a required
  check (provider availability and cost are not CI-stable). A scheduled,
  best-effort run is a separate decision.
- Reviewer should scrutinise: the redaction path, that `UNVERIFIED` can never be
  read as approval, and that the synthetic inputs cannot be mistaken for real
  articles.
- **Deferred:** a scheduled canary with cost tracking, and a critic-scoped
  mutation/coverage extension. Both unblocked by an operator decision on provider
  budget.
