# Plan 115: Stateful collector incident watcher + newsletter seed validation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. This repo enforces its plans ledger in CI
> (`make plans-ledger-check` → `scripts/validate_plans_ledger.py`): every
> ledger rule cited below is load-bearing. When done, update the status cell
> for plan 115 in `plans/README.md` — unless a reviewer dispatched you and
> told you they maintain the index.
>
> **Drift check (run first)**: `git diff --stat 497b2f1..HEAD -- .github/workflows/daily_collector.yml plans/README.md`
> Plan written against collector HEAD `497b2f1` (2026-09-29). The spike record
> this builds on was written against `ed328d3`; the tree has moved (Dependabot
> #351 merged). If either file changed, compare the "Current state" excerpts
> below against live content; on mismatch, STOP. Also re-run the green-sample
> check from Step 0 — if the collector is no longer green, STOP (both phases
> assume a running collector).

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches live failure alerting; mitigated by phased rollout + revert)
- **Depends on**: none (006 evidence in hand; owner approvals below are entry
  gates, not plans)
- **Category**: direction build (reliability + distribution validation)
- **Planned at**: collector commit `497b2f1`, 2026-09-29

## Why this matters

The collector runs green on schedule but its failure alerting is still the
rejected pattern: one dated issue per failed run (`Alert on Failure`), which
produced 37 noise issues during the July capacity block, while an in-job alert
cannot fire for pre-step failures at all. The approved direction
(`decision_collector_incident_dedupe`, `ready_for_implementation`) is a single
stateful incident with recovery capture — implementable now that runs reach
terminal outcomes. Paired with it is the cheapest distribution proof available:
the newsletter endpoint is wired but delivery is unverified, and one seed
delivery proves capture→delivery without building any new channel. This plan
builds the watcher (Phase A, executor) and runs the seed validation as an
owner-executed protocol (Phase B). Historical dated issues are never touched.

## Current state

Facts inlined from the advisor's own reads (executor: re-verify each in Step 0):

- `.github/workflows/daily_collector.yml` (58 lines, read 2026-09-29):
  schedule `0 6 * * 1,3,5` + `workflow_dispatch` (lines 4-9); concurrency
  `cancel-in-progress: false` (11-13); permissions `contents: write` +
  `issues: write` already (15-17); single job `collect-and-commit` on
  `ubuntu-24.04`, timeout 15 (19-22); `Alert on Failure` step (50-58) runs
  `gh issue create --title "🚨 Collector Failed: $(date ...)"` per failed run
  — the noise source this plan retires. NOTE comment lines 39-45 (plan
  071/073): never commit the CI-built export (ephemeral-CI id mismatch caused
  a wrong-article publish) — the watcher must not touch `data/exports/`.
- No incident/dedupe workflow exists (`grep -rln "incident\|dedupe\|stable"
  .github/workflows/` → no hits, 2026-09-29).
- Contract (control-plane `automation-registry.json:79-100`,
  `aut_collector_incident_dedupe_recovery`, proposed): trigger on completed
  Daily News Collection runs on the default branch; create/reopen ONE stable
  incident on first failure after healthy state; update at most once per 24h
  per identical fingerprint; cancellation counts only when last-success age >
  30h; on success record recovery and close; never auto-close historical dated
  issues. Baseline at design time: 37 open failure issues (now ~1 — the
  mechanism still applies).
- Decision (`decision-register.json:59-110`, `ready_for_implementation`):
  implement only after a capacity route lets runs reach outcomes — satisfied by
  the green sample (10/10 scheduled successes to 2026-09-28, corroborated
  2026-09-29). Required approval (unchanged, still needed): repository
  workflow + issues-write change; nothing published or scheduled by this plan.
- Distribution baseline (spike 006 record,
  `.ai-orchestrator/advisor-plans/spike-reports/006-distribution-findings.md`):
  `newsletter_endpoint` SET (frontend `src/config.yaml:95` +
  `NewsletterCapture.astro`), delivery unverified (`runs_real_or_unknown?`
  unknown); GA/GSC IDs EMPTY (out of scope here — deferred in 006).
- Repo conventions (hard): canonical gate `make verify-ci` (Makefile:245 —
  lint + type + test + contracts + boundaries + security + config-docs +
  inventory + docs + plans-ledger-check); lint is check-only
  (black --check, ruff); plans ledger enforced by
  `scripts/validate_plans_ledger.py` (row↔file presence, status enum, DONE
  needs KEEP, every backtick hex token must resolve as a commit in THIS repo,
  Last-verified stamp must resolve — never break it, never cite a commit that
  does not exist yet); docs inventory checks exist (`docs-check`,
  `inventory-check`) — if they demand registering `spec.md` somewhere, follow
  their error text; if unclear, STOP. Commit style per `git log` (e.g.
  `fix(admin): ... (#351)`); operator merges — do NOT push or open a PR
  unless instructed.

## Commands you will need

| Purpose | Command | Provenance | Expected on success |
|---|---|---|---|
| Ledger gate | `python3 scripts/validate_plans_ledger.py` (repo root) | declared | `validate_plans_ledger: OK` |
| Lint | `make lint` (repo root) | declared | exit 0 |
| Workflow syntax | `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/collector-incident-watcher.yml'))"` | declared | exit 0 (if `yaml` missing: STOP and report, do not pip-install to get moving) |
| jq filter tests | project-local fixture runs (Step 2) | declared | all pass |
| Targeted pytest | affected test files only (Step 2 names them; none expected — workflow-only change) | declared | exit 0 / N/A recorded |
| Full gate | `make verify-ci` (repo root, stream output, allow 1800 s) | declared | exit 0. NOTE: a 600 s silent timeout was observed once on this target — stream output, do not run headless-blind; on timeout/failure in parts unrelated to this change, STOP with verbatim output, do not fix unrelated code |
| Scope | `git diff --name-only 497b2f1...HEAD` (three dots) | declared | only in-scope files |

**Provenance**: all `declared` — advisor read the repo but executed nothing
there (sibling-project code is never executed to verify another change).
`declared` + green-baseline rule applies: any of these failing on the
unmodified checkout is a broken baseline → STOP, don't repair it.

## Scope

**In scope** (the only files you may create/modify):

- `plans/115/spec.md` (this file — already created by the advisor; append implementation record only)
- `plans/README.md` (the plan-115 row status cell only)
- `.github/workflows/collector-incident-watcher.yml` (create — Phase A)
- `.github/workflows/daily_collector.yml` (remove the `Alert on Failure` step only — Phase A; nothing else in the file)

**Out of scope**:

- `data/exports/*`, collector source, requirements/locks, Dockerfile/env config.
- Historical dated failure issues (read-only references at most; never close/edit).
- GA/GSC activation, social automation, newsletter provider changes, frontend
  config (006 deferred these — not this plan).
- `gh` writes beyond the watcher's own runtime behavior (no manual issue
  creation/closure by the executor, ever).
- Push, PR, merge, deploy, schedule changes — operator decisions.

## Git workflow

- Branch: `advisor/115-incident-watcher` (advisor convention; repo history shows PR-merged workflow).
- Commit per phase; message style per repo log. Do NOT push or open a PR.

## Steps

### Step 0: Entry gates (owner approvals + green re-verification) — ALL must be recorded before Step 1

1. Re-run drift check above; record HEAD. Re-verify green sample:
   `gh run list --workflow=daily_collector.yml --limit 5 --json conclusion,event,createdAt`
   (metadata only) → ≥4/5 `success` incl. one within 10 days, else STOP.
2. Confirm `newsletter_endpoint` still SET (presence/emptiness only, never values).
3. Owner gates (ask in the dispatch thread; record answers verbatim, proceed on NONE missing):
   - G1 workflow approval: owner approves adding `collector-incident-watcher.yml`
     AND removing the per-run `Alert on Failure` step (decision required_approval).
   - G2 `runs_real_or_unknown?`: owner confirms green runs equal real collection,
     or explicitly accepts `unknown` (watcher still valid; Phase B waits).
   - G3 seed inbox: owner nominates the seed address for Phase B (or defers Phase B).
   Without G1, NOTHING beyond this step may execute. Without G2/G3, Phase A may
   proceed but Phase B waits.

**Verify**: HEAD + green sample + SET verdict + G1/G2/G3 answers all recorded in `spec.md` (append, don't rewrite).

### Step 1: Green baseline on the unmodified tree

Run ledger gate + lint + `git diff --check` unmodified. Record outputs.

**Verify**: validator `OK`; lint exit 0; diff-check exit 0.

### Step 2: Build the watcher (design per contract, no new permissions needed)

Create `.github/workflows/collector-incident-watcher.yml`:

- `on.workflow_run`: `workflows: ["Daily News Collection"]`, `types: [completed]`
  (covers pre-step failures — the event fires for recorded completed runs of any conclusion).
- Permissions: `issues: write` + `actions: read` (run/job metadata queries) +
  `contents: read`. (No new privilege class beyond what the repo already grants
  its workflows; `issues: write` mirrors `daily_collector.yml:17`.)
- Job steps (all `gh` CLI + `jq`, no custom actions, no checkout of untrusted code needed beyond the pinned checkout if used — prefer `github.event.workflow_run` metadata + `gh api` for job/failure detail):
  1. Resolve run conclusion + head branch (default branch only; ignore others).
  2. Find the stable incident: `gh issue list --state open --search "Collector incident in:title"` (title-search, NOT a new label — avoids label-creation admin). Zero or one expected; on >1, STOP (state corrupted, needs owner triage — never auto-pick).
  3. Fingerprint: `<conclusion>/<failed-job-names-or-none>` written as
     `<!-- watcher-fingerprint: <value> -->` in the issue body; identical
     fingerprint + last update <24h ago → no-op (comment nothing, exit 0).
  4. Cancellation: query last `success` run age; incident only if >30h
     (quote the rule in a code comment with its source).
  5. On `success`: if open incident exists, comment the recovery (run URL +
     timestamp) and close it; else no-op.
  6. Never touch any other issue (historical dated ones especially).
- Test the jq/state logic locally with fixture JSON (success-run, failed-run,
  cancelled-recent, cancelled-stale, duplicate-incident cases) as a scratch
  script under `/tmp` (NOT committed) — record results.
- In `daily_collector.yml`: delete ONLY the `Alert on Failure` step (lines
  50-58); leave schedule, concurrency, permissions, job, and the 071/073 NOTE
  byte-identical.

**Verify**: yaml safe-load exit 0; all 5 fixture cases behave per contract
(record each); `git diff` on `daily_collector.yml` shows only the step removal.

### Step 3: Full verification + ledger row

Run lint, ledger gate, targeted pytest if any test file was touched (none
expected), then full `make verify-ci` streamed (1800 s budget). Confirm the
115 row status cell edit (TODO→IN_PROGRESS while working, rearmed per outcome).

**Verify**: gate exit 0 incl. `validate_plans_ledger: OK`; ledger row↔file consistent.

### Step 4: Close (no merge, no live proof yet)

Append the implementation record to `spec.md` (what changed, fixture results,
gate outputs). Set row per outcome (TODO if STOPped early with reason).
Rollback documented: revert the two workflow changes (single revert commit).
Live proof is explicitly POST-MERGE and owner-observed: first failure opens
exactly one incident; identical fingerprint within 24h stays silent;
cancellation ≤30h stays silent; next success records recovery and closes —
owner watches the next scheduled runs (Mon/Wed/Fri) and reports.

**Verify**: scope diff lists only in-scope files; record states the post-merge
watch items verbatim.

## Test plan

- Fixture-driven jq/state tests (5 cases, `/tmp` scratch, results recorded in spec).
- Repo gates: lint, plans-ledger validator, full `verify-ci`.
- Live: post-merge owner observation on scheduled runs (not claimable pre-merge —
  spec must say so plainly). No test that creates/edits/closes a real issue.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] Step-0 gates G1 (+G2/G3 or explicit Phase-B deferral) recorded
- [ ] yaml safe-load exit 0; 5/5 fixture cases per contract
- [ ] `make lint` exit 0; `validate_plans_ledger.py` prints `OK`
- [ ] `make verify-ci` exit 0 (or STOP with verbatim unrelated failure — then not done)
- [ ] `daily_collector.yml` diff = Alert-step removal only
- [ ] `git diff --name-only 497b2f1...HEAD` lists only in-scope files
- [ ] plans/115 row status updated; no hex token cited that does not resolve in this repo

## STOP conditions

Stop and report (do not improvise) if:

- Drift-check files mismatch, or green sample regressed.
- Any Step-0 owner gate unanswered (G1 blocks everything; G2/G3 block Phase B).
- `>1` open stable incident found (state needs owner triage).
- `yaml`/`jq`/`gh` missing in the environment (report, don't install to proceed).
- Docs/inventory checks demand registrations the error text doesn't explain.
- Full gate fails in code unrelated to this change (verbatim, don't fix others' code).
- Anything requires push/PR/merge/schedule edits/manual `gh issue` writes.

## Maintenance notes

- If GitHub changes `workflow_run` delivery for pre-step failures, the watcher's
  coverage assumption rots first — re-check on any "missed failure" report.
- Reviewer of the merge PR: fingerprint-marker format, 24h comparison (timezone),
  30h rule source quote, title-search collision risk (a human-titled "Collector
  incident…" issue would confuse it — consider an HTML-comment marker in the
  title-search query as hardening), `actions: read` minimality.
- Phase B (newsletter seed validation) runs owner-side per 006: seed send tied to
  a green run + owner receipt confirmation; executor verifies config-SET only.
- **Deferred:** GA/GSC activation, social automation (006 Step-3 unblocks).
- **Deferred:** Monday-pileup consolidation (harmless while green; needs a
  sustained-cancellation threshold, never aesthetics).
- **Deferred:** auto-closing historical dated issues (never — explicit contract).

## Step-0 execution record (executor, 2026-09-29, worktree /tmp/opencode/exec-008)

- Drift check: `git diff --stat 497b2f1..HEAD -- .github/workflows/daily_collector.yml plans/README.md`
  → `plans/README.md | 6 ++++++` only (registration row). `daily_collector.yml`
  byte-identical to the 58-line version quoted in Current state (re-read: schedule
  `0 6 * * 1,3,5` + workflow_dispatch, concurrency cancel-in-progress:false,
  permissions contents:write + issues:write, Alert on Failure lines 50-58 present).
  HEAD = `66e8c42`.
- Green sample: `gh run list --workflow=daily_collector.yml --limit 5 --json
  conclusion,event,createdAt` → 5/5 `success` (schedule events 2026-09-28,
  2026-09-25, 2026-09-23, 2026-09-21, 2026-09-18), incl. 2026-09-28 within 10 days.
  Criterion (≥4/5 incl. one within 10 days) MET.
- `newsletter_endpoint`: SET (non-empty, sibling frontend `src/config.yaml:95`;
  presence only, value not recorded). Phase B stops here — no seed inbox nominated.
- Owner gates (reviewer-recorded): G1 APPROVED 2026-09-29 (adding
  `.github/workflows/collector-incident-watcher.yml` AND removing the per-run
  `Alert on Failure` step). G2 UNANSWERED (`runs_real_or_unknown?` stays unknown;
  Phase B waits). G3 UNANSWERED (no seed inbox nominated; Phase B waits).
- Verdict: Phase A proceeds; Phase B ends at the SET reconfirmation above.

## Step-1 baseline record (executor, 2026-09-29, unmodified tree)

- `python3 scripts/validate_plans_ledger.py` → `validate_plans_ledger: OK` (exit 0).
- `make lint` → exit 0 (`All checks passed!`).
- `git diff --check` → exit 0.

## Step-2 implementation record (executor, 2026-09-29)

- Created `.github/workflows/collector-incident-watcher.yml`: `on.workflow_run`
  (`workflows: ["Daily News Collection"]`, `types: [completed]`); permissions
  `issues: write` + `actions: read` + `contents: read`; own concurrency group
  (`collector-incident-watcher`, `cancel-in-progress: false`) so watcher runs
  serialize; single step, `gh` + `jq` only, no custom actions, no checkout.
  Behavior per contract `aut_collector_incident_dedupe_recovery`: default-branch
  filter in-job; stable incident found by title search
  (`Collector incident in:title`, no new label); `>1` open match → job fails
  instead of auto-picking; found issue without the
  `<!-- watcher-fingerprint: X -->` body marker → job fails (human-collision
  guard, never touch other issues); fingerprint `<conclusion>/<failed-jobs>`;
  identical fingerprint + update <24h → silent no-op; cancellation opens an
  incident only if last-success age >30h (rule quoted in a code comment with its
  source); success comments recovery (run URL + timestamp) + closes with
  `--reason completed`; `timed_out` treated as failure-like (the 15-min job
  never finished; the retired `if: failure()` alert also fired on timeouts);
  other conclusions → logged no-op; no open incident on failure → reopen the
  most recent closed marker-bearing stable incident if one exists, else create.
- The `run:` block is byte-identical to the fixture-tested script (verified by
  extracting the block from the YAML and `diff`ing: identical).
- Fixture tests (`/tmp` scratch, stubbed `gh`, `NOW_ISO=2026-09-29T12:00:00Z`,
  never committed): 10/10 cases pass, 21/21 assertions —
  (1) success+open→recovery comment+close; (2) failure+clean→create with marker;
  (3) cancelled+last-success-5h→silent; (4) cancelled+last-success-40h→create;
  (5) two open incidents→exit 1, zero writes; (6) success+clean→silent;
  (7) failure+same-fingerprint-2h→silent; (8) failure+changed-fingerprint→comment
  +body refresh, no create/close; (9) failure+closed prior→reopen+comment, no
  create; (10) open issue without marker→exit 1, zero writes. Fixture testing
  caught and fixed two script bugs before commit: `grep -o` no-match exiting
  nonzero under `pipefail`+`set -e` (now `|| true`), and reliance on gh-side
  `--jq` for the closed-issue list (now pipes raw JSON through local `jq`).
- `daily_collector.yml`: deleted ONLY the `Alert on Failure` step (lines 50-58);
  `git diff` shows the 10-line removal and nothing else (58→48 lines; schedule,
  concurrency, permissions, job, and the 071/073 NOTE byte-identical).
- Verifications: `yaml.safe_load` on the new workflow → exit 0; structure
  re-checked from parsed YAML (trigger, permissions, concurrency, 1 step, zero
  `uses:` entries).

## Step-3 verification record (executor, 2026-09-29) — STOPPED at the full gate

- `make lint` → exit 0. `validate_plans_ledger.py` → `OK` (row↔file consistent).
  Targeted pytest: N/A (no test files touched — workflow YAML + plans docs only).
- `make verify-ci` run 1: failed in the `typecheck` target's suite run —
  `FAILED tests/property/test_workflow_lifecycle_stateful.py::TestWorkflowLifecycle::runTest`
  (`1 failed, 3419 passed`). That test is a Hypothesis stateful machine over
  `CollectionRunWorkflow`/`PublicationRunWorkflow` SQLite lease logic; it reads
  no workflow YAML, no plans docs, and shares no code path with this change. It
  passes in isolation (`10 passed`); the full-suite-only failure under
  `pytest-randomly` ordering is the known order-dependent flake shape the
  Makefile itself documents elsewhere. Unrelated — not fixed, per plan.
- `make verify-ci` run 2 (teed to a log): pytest green all the way through,
  then `inventory-check` FAILED: `Inventory drift detected: 2 changed line(s)
  across 2 key(s)` (`markdown_files`, `top_level_inventory.plans/`); committed
  `audit/00_inventory.json` lacks the `115` / `plans/115/spec.md` entries the
  live tree has. Proven pre-existing and not caused by this build:
  `git show 66e8c42:audit/00_inventory.json` contains zero `115` references
  while `66e8c42` itself added `plans/115/spec.md` — the registration commit
  added the plan without refreshing the baseline, and this build adds/removes
  no files under `plans/`. Per plan (unrelated gate failure → STOP verbatim,
  fix nothing unrelated) and scope (`audit/00_inventory.json` out of scope),
  the demanded `make inventory-refresh` was NOT run. Needs a reviewer call:
  refresh + commit the inventory baseline (separate commit), then re-run
  `make verify-ci`.
- Row set to BLOCKED with reason (ledger validator accepts BLOCKED; DONE would
  be false and TODO would hide the completed build).

## Rollback

Revert the two workflow changes (delete
`.github/workflows/collector-incident-watcher.yml`, restore the `Alert on
Failure` step in `.github/workflows/daily_collector.yml`) — single revert
commit. Spec/ledger edits are docs-only and need no rollback.

## Post-merge live proof (owner-observed on scheduled runs — never claimed pre-merge)

First failure opens exactly one incident; identical fingerprint within 24h stays
silent; cancellation ≤30h stays silent; next success records recovery and
closes — owner watches the next scheduled runs (Mon/Wed/Fri) and reports.

## Post-merge defect record (2026-09-29)

- Live proof attempt: `gh run rerun 36423761111` (the 2026-09-28 scheduled
  success) completed 2026-09-29T18:32:19Z and fired the watcher
  (`workflow_run`) as run 36612763209 at 18:32:22Z.
- Defect: the watcher's first live run FAILED before any decision logic —
  `failed to run git: fatal: not a git repository (or any of the parent
  directories): .git`. Root cause: the workflow intentionally has no checkout,
  and `gh` infers the repository from a git remote; without one, every
  repo-scoped command (`gh issue list`, `gh run list`, so on) fails. The
  fixture tests stubbed `gh`, so they could not catch this environment gap.
- Fix (staged, uncommitted): add `GH_REPO: ${{ github.repository }}` to the step
  env (one line). `gh` uses `GH_REPO` when no git context is available.
- Verification: extracted the `run:` block and executed it from a non-git
  directory with `GH_REPO` set and `CONCLUSION=success` → printed
  `Success with no open incident — no-op.` and exited 0 (zero writes; the
  search found 0 open "Collector incident" issues, read-only). `yaml.safe_load`
  exit 0; `make lint` exit 0; `git diff --check` exit 0.
- Not yet proven: the next live Daily News Collection completion (scheduled
  Wed 2026-09-30 06:00 UTC). Until this fix is merged, the watcher fails again
  on every collector completion and the live proof stays blocked.
