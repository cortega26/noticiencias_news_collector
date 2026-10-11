# Plan 118: Enforce the v2 editorial contract in the backend mirror

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/contracts/frontend_schema.py`
> If the in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (plan 119 shrinks the sync-gate divergences after this lands)
- **Category**: bug
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

The frontend sealed schema rejects `schema_version >= 2` posts missing any
of the six editorial enrichment fields, but the backend `AstroPost` mirror
declares them all `Optional` with no v2 validator. The backend can therefore
approve, persist, and ship a v2 post that passes `make test-contracts` yet
fails the Astro build (`validate:content` / Content Guard) — a
publishable-looking article that becomes a deploy-time
`frontend_build_failure` or PR rejection. Same class of gap for
`featured_rank` (frontend: positive + required when featured; backend:
unconstrained `Optional[int]`) and for list items (frontend `min(1)`;
backend bare `List[str]`). Tightening the mirror moves these failures to
refinery time, where they belong. Pure validation tightening: it can only
reject payloads the frontend already rejects.

## Current state

The relevant file is
`news_collector/contracts/frontend_schema.py`, class `AstroPost`
(docstring: "Strict contract for Astro Content Collection 'posts'. Matches
src/content.config.ts v1"). Verified 2026-10-11:

```python
# frontend_schema.py:181-182 — no gt, no cross-field rule
featured: bool = Field(default=False)
featured_rank: Optional[int] = None
summary_points: Optional[List[str]] = None
```

```python
# frontend_schema.py:188, 208-209 — no per-item min_length
why_it_matters: Optional[List[str]] = Field(default=None, max_length=3)
known_points: Optional[List[str]] = Field(default=None, max_length=3)
open_questions: Optional[List[str]] = Field(default=None, max_length=3)
```

```python
# frontend_schema.py:207-210 — regex only, no calendar check (feeds plan 120)
review_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
corrected_at: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
```

Existing `model_validator(mode="after")` methods on `AstroPost` (verified):
`_correction_travels_together`, `_social_not_null` (+ field validators),
`ensure_date_format`, `ensure_alt_text_contract` — no v2
editorial-fields validator exists. (Note: `SocialConfig` already mirrors
the frontend `social` object correctly — strict bool, 64-hex id, required
when publishing. That is the exemplar to copy for style.)

Frontend rules to mirror (`noticiencias/src/content.config.ts`, read-only
reference — do NOT edit the frontend in this plan):

- `content.config.ts:86-87`: `featured_rank: z.number().int().positive().optional()`,
  `summary_points: z.array(z.string().min(1)).min(2).max(5).optional()`
- `content.config.ts:199-206`: `featured === true` requires `featured_rank`
- `content.config.ts:228-283` `superRefine`: `schema_version >= 2` requires
  `summary_points` (2–5 non-empty), `glossary` (≥1), `fact_check` (≥1),
  `confidence`, `sources` (≥1); `why_it_matters` 0–3 with no minimum
  (do NOT impose a minimum on it)
- `content.config.ts:121,157-158`: `why_it_matters` / `known_points` /
  `open_questions` are `z.array(z.string().min(1))`

Repo conventions (`docs/AGENTS.md` LAW-B1/B2): boundary shapes are Pydantic
models in `contracts/`; contract changes are High-risk class → baseline +
`make test-contracts`. Per `docs/AGENTS.md` §0.1 this repo mandates
spec-driven workflow — the executor works inside an isolated worktree, so
create the plan's `spec.md`/`todo.md` notes inline in commits rather than
new tracked files (or, if repo practice demands them, keep them untracked
in the worktree and note it). Tests are architectural evidence — every rule
added here needs a contract test. Also note the cross-repo rule: any change
to either schema file is a critical cross-repo change — run the frontend's
`npm run check:contract-sync` as the mirror check (Step 4).

Prior related work (do not duplicate): backend plan 094 unified slug
extraction; plan 100 moved manual-ingest policy gates; plan 060 Phase 2b
audited published v2 metadata. None added a v2 validator to `AstroPost`.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0 (+ coverage ratchet green) |
| Unit      | `make test`              | declared   | pass                |
| Contracts | `make test-contracts`    | declared   | pass                |
| Mirror    | frontend `npm run check:contract-sync` | declared | exit 0 (run from `../noticiencias/`) |

## Scope

**In scope** (the only files you should modify):

- `news_collector/contracts/frontend_schema.py` (three validator additions)
- `tests/` contract tests for the new rules (find the existing
  `frontend_schema`/`AstroPost` test file and extend it — do not create a
  competing suite)

**Out of scope** (do NOT touch, even though they look related):

- `../noticiencias/src/content.config.ts` — read-only reference. If the TS
  rules don't match this plan's description, STOP (contract drift).
- `scripts/check-contract-sync.js` (frontend) — plan 119 owns the gate.
- `review_date`/`corrected_at` calendar parsing — plan 120 owns it.
- Production data migration — no backfill; the validator applies to new
  validations only.

## Git workflow

- Branch: `advisor/118-contract-parity`
- Commit per validator; message style matches repo log, e.g.
  `fix(contracts): enforce v2 editorial fields in AstroPost mirror`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make lint && make type && make test-contracts` on the unmodified
checkout. Note: the working tree was dirty at plan time (~25 modified
files around webhook-inbox-pull/source-health) — you are in an isolated
worktree; if those files differ from `04016ca`, that is expected drift,
not breakage. Record the baseline result.

**Verify**: all three gates pass; write down any pre-existing reds (if any
are red pre-existing, STOP and report — do not "fix" the baseline).

### Step 1: Add the v2 editorial-fields validator

Add a `mode="after"` `model_validator` on `AstroPost` mirroring the TS
`superRefine` branches exactly: when `schema_version >= 2`, require
`summary_points` (2–5 non-empty strings), `glossary` (≥1 item),
`fact_check` (≥1 item), `confidence`, `sources` (≥1). `why_it_matters`
keeps its 0–3 max with NO minimum. Strip whitespace when checking
non-emptiness (so `["  "]` fails). Error messages must name the field and
the v2 condition (mirror the TS messages where practical).

**Verify**: `make test-contracts` passes; a manual probe (python repl or
one-off test) shows a v2 post missing `summary_points` raises, while a v1
post without any editorial fields still validates.

### Step 2: Constrain featured_rank

Set `featured_rank: Optional[int] = Field(default=None, gt=0)` and add a
`_featured_rank_required_when_featured` after-validator mirroring
`content.config.ts:199-206` (`featured is True` and no rank → error).

**Verify**: `featured=True` without rank raises; `featured_rank=0`/`-3`
raises; `featured=False` without rank passes; `make test-contracts` passes.

### Step 3: Require non-empty list items

Constrain item types to non-empty (whitespace-stripped) strings for
`summary_points`, `why_it_matters`, `known_points`, `open_questions`
(`List[constr(min_length=1)]` equivalent or an item validator — match the
file's existing style). Add one parametrized contract test per field with
`[""]` and `["  "]` cases.

**Verify**: `make test-contracts` passes with the new cases green.

### Step 4: Mirror check + full gates

Run `make lint && make type && make test` and, from `../noticiencias/`,
`npm run check:contract-sync` (read-only mirror confirmation — the
`ALLOWED_DIVERGENCES` shrink happens in plan 119, so tolerated warnings
here are expected, errors are not).

**Verify**: backend gates green; frontend sync shows no NEW divergences
vs the Step-0 baseline (compare outputs).

## Test plan

- Extend the existing `AstroPost` contract test file (find it via
  `grep -rln "AstroPost" tests/ | head`): v2-missing-fields cases (5+),
  featured-rank cases (4), empty-item cases (4 fields × 2).
- Every new rule gets a positive case (valid payload still passes) and a
  negative case.
- Verification: `make test-contracts` all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] A v2 `AstroPost` missing `summary_points` fails validation (probe or test)
- [ ] `featured=True` without `featured_rank` fails; `featured_rank=0` fails
- [ ] `summary_points=[""]` fails validation
- [ ] `make lint && make type && make test && make test-contracts` all pass
- [ ] Frontend `npm run check:contract-sync` shows no new divergences
- [ ] `git diff --name-only 04016ca...HEAD` lists only `frontend_schema.py` + the test file(s)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts
  (especially if a v2 validator was added meanwhile — don't duplicate it).
- The frontend TS rules differ from this plan's description (mirror first,
  then report the drift).
- Any currently-persisted refinery fixture/test that SHOULD be valid starts
  failing (the rule may be stricter than the frontend — compare against TS
  behavior before "fixing" fixtures).
- A `declared` command fails on the unmodified checkout (broken baseline).
- The fix appears to require touching an out-of-scope file.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- Every future `content.config.ts` rule needs a mirror here in the same PR
  (cross-repo contract law) — plan 119 makes the gate enforce the
  cross-field class of rules.
- **Deferred:** `review_date`/`corrected_at` calendar validation → plan 120.
- If the v2 field set grows upstream, this validator is the single place
  to extend (don't scatter v2 checks across workflows).
