# Plan 060 / Phase 0: Baseline, decision record, and reproducible fixtures

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. This phase spans **two sibling repositories** that live under the
> same parent directory:
>
> - **Backend** = `noticiencias_news_collector/` (this repo; also the home of
>   the master plan at `plans/060/spec.md` and `plans/060/todo.md`)
> - **Frontend** = `noticiencias/` (sibling directory — same parent as backend)
>
> If you were dispatched into an isolated worktree of only one of these two
> repos, complete only that repo's steps below (they are grouped and labeled),
> commit, and report which half you completed and which half still needs a
> separate dispatch against the other repo. Do not attempt to `cd` out of your
> worktree into the other repo's working tree — treat the sibling repo as
> read-only reference material you can `cat`/`git show` via its path if your
> environment happens to expose it, but never write to it from this worktree.
>
> When done, update the status row for **this phase** in
> `plans/060/todo.md` (check off the four "Phase 0" boxes under "Wave A") —
> unless a reviewer dispatched you and told you they maintain the index, per
> the standard override.
>
> **Drift check (run first, in each repo you touch)**:
> `git diff --stat d63cbea..HEAD -- docs/adr/ docs/PIPELINE_CONTRACTS.md docs/ARCHITECTURE.md tests/fixtures/ plans/060/` (backend)
> `git diff --stat 237cd13..HEAD -- docs/adr/ docs/SOURCE_OF_TRUTH.md tests/fixtures/ src/content.config.ts` (frontend)
> If either reports changes, compare the "Current state" excerpts below
> against the live files before proceeding; on a mismatch, treat it as a STOP
> condition (see below) — the master plan's evidence baseline may be stale.

## Status

- **Priority**: P1 (blocks every later phase of plan 060 — nothing else in
  the program has a lower hard dependency)
- **Effort**: M
- **Risk**: LOW (additive docs and fixtures only; no production code path
  changes, no schema/behavior changes, no CI gate is tightened in this phase)
- **Depends on**: none
- **Category**: tech-debt / migration (foundation for plan 060 waves A–E)
- **Planned at**: backend commit `d63cbea`, frontend commit `237cd13`,
  2026-08-22
- **Parent plan**: `plans/060/spec.md` (read section "Phase 0: Baseline,
  decision record, and reproducible fixtures" there for the one-paragraph
  purpose statement this plan expands — you do not need to read the rest of
  that 800-line file to execute this phase; everything required is inlined
  below)

## Why this matters

Plan 060 is an 11-phase, two-repository reliability and architecture-hardening
program. Every later phase (durable workflow tables, generated contracts,
strict v2 enforcement, etc.) depends on three things existing first: a
recorded decision trail (so later phases don't re-litigate settled tradeoffs),
a versioned corpus of valid/invalid publication fixtures (so "does this
validator accept the right things" has a fixed answer both repos can check
against), and a frozen baseline of the current strict-editorial failure state
(so Phase 2's human content review has a fixed worklist instead of a moving
target). None of this changes runtime behavior — it is pure scaffolding that
de-risks everything that follows.

## Current state

### Repository layout (confirmed 2026-08-22)

Both repos are git siblings under the same parent directory. This is not a
new convention — `tests/test_contracts_sync.py:36` already resolves the
frontend path this way:

```python
_REPO_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND_CONFIG = _REPO_ROOT.parent / "noticiencias" / "src" / "content.config.ts"
```

Backend git status at plan time: **`plans/060/` is untracked** (`git status
--short` shows `?? plans/060/`) and `plans/README.md` has uncommitted
modifications. **The operator must commit `plans/060/` (the master
`spec.md`/`todo.md` plus this `phase-0-baseline/` pair) before any `execute`
dispatch** — a worktree only contains committed files, so an executor cannot
read this plan at all until that commit lands. This is a precondition of
dispatch, not a task for the executor: if you are executing this phase and
`plans/060/` is still untracked or absent from your worktree, that is
impossible under a correct dispatch, so STOP immediately and report it rather
than committing it yourself or guessing why it's missing.

Frontend git status at plan time: only `.codegraph/.gitignore` is modified,
pre-existing and unrelated (do not touch it).

### ADR inventory (existing, for numbering the new ones)

Backend `docs/adr/`: `0000-adr-template.md`, `0001-adapter-pattern-contracts.md`,
`0002-hash-pinned-lockfiles.md`, `0003-two-repo-split-and-schema-versioning.md`,
`0004-curated-enrichment-registry-spike.md`,
`0005-completed-is-scoring-state-not-publication.md`. **Next number: `0006`.**

Frontend `docs/adr/`: `0000-adr-template.md`, `0001-server-first-rendering.md`,
`0002-two-ui-layers.md`, `0003-content-schema-contract.md`,
`0004-npm-over-pnpm.md`. **Next number: `0005`.**

Both repos share the identical template at `docs/adr/0000-adr-template.md`:

```markdown
# ADR-NNNN: [Short title]

- **Date**: YYYY-MM-DD
- **Status**: Proposed | Accepted | Superseded by ADR-XXXX

## Context

What situation or constraint forced this decision?

## Decision

What was chosen and why?

## Consequences

What becomes easier? What becomes harder or constrained?

## Alternatives considered

| Option | Reason rejected |
|--------|-----------------|
| …      | …               |
```

Backend ADR-0003 (`docs/adr/0003-two-repo-split-and-schema-versioning.md`) is
the closest existing exemplar for tone/depth — it uses a fuller structure
(Context / Decision / Rollback / Consequences / Alternatives Considered with a
Deciders line) than the bare template. Match that fuller style, not the bare
template, for the three new ADRs — they are consequential, cross-repo
decisions like ADR-0003 was.

### Strict editorial failure state (re-verified 2026-08-22, matches master plan's planning evidence exactly — no drift)

Command run from the frontend repo root:

```bash
STRICT_EDITORIAL=true node scripts/check-editorial-fields.js --json
```

Result: `status: "fail"`, `filesCount: 31`, `v2Count: 31`, 180 error entries
across exactly 30 distinct files (one v2 post is complete and produces zero
errors). Every one of the 30 failing files is missing the same six fields:
`summary_points`, `glossary`, `fact_check`, `why_it_matters`, `confidence`,
`sources` — i.e., these are 30 posts with **no v2 enrichment data at all**,
not 30 posts with scattered partial gaps.

### v2 schema field shapes (for building fixtures — from `src/content.config.ts`)

```
schema_version: z.number().int().min(1).default(1)          // line 11
summary_points: array of 1+ non-empty strings, 2–5 items     // line 47, enforced 2–5 at line 115-119
glossary: array of {term: string(min 1), definition: string(min 1)}, ≥1 item   // lines 49-57, 123-131
fact_check: array of {label: string, status: string}, ≥1 item                  // lines 58-66, 132-140
why_it_matters: array of strings, ≥1 item                                      // line 67, 141-148
confidence: string, required                                                   // line 42, 150-157
sources: array of {title: string(min 1), url, publisher?: string, date?: string}, ≥1 item  // lines 70-77, 159-166
```

The strict-mode enforcement (`superRefine`, gated on `schema_version >= 2` and
`strictEditorial` flag) lives at `src/content.config.ts:102-166`. This is the
authoritative shape for every v2 fixture you write — do not invent a shape
that isn't backed by these lines.

One complete, currently-passing v2 post to use as your positive-example
template:
`src/content/posts/2026-08-12-un-modelo-de-ia-realizo-mas-de-17-500-acciones-en-hugging-face.md`.
Read its frontmatter directly; do not paraphrase it into the fixture corpus —
copy the real field shapes.

### Existing publication-schema snapshot tooling (already built — verify, do not rebuild)

Frontend `package.json` already has:

```json
"sync:contract-snapshot": "node scripts/check-contract-sync.js --generate-snapshot .contract-snapshots/frontend_schema.snapshot.json ${BACKEND_SCHEMA_PATH:-../noticiencias_news_collector/news_collector/contracts/frontend_schema.py} src/content.config.ts"
```

`.contract-snapshots/frontend_schema.snapshot.json` is already committed and
tracked (last synced commit `26dae65`, 2026-08-04). Both schema sources are
older than that sync (`src/content.config.ts` last changed 2026-06-24;
backend `news_collector/contracts/frontend_schema.py` last changed 2026-07-21)
— the committed snapshot is current as of this plan's baseline SHAs. **Do not
regenerate it unless your drift check shows either schema file changed** —
this half of Phase 0's "publication schema snapshot" requirement is already
satisfied; your job is to confirm and document that, not redo it.

### Backend: no OpenAPI snapshot tooling exists yet (new work)

`news_collector/serving/api.py:475-477`:

```python
def create_app(  # noqa: C901
    database_manager: Optional[DatabaseManager] = None,
) -> FastAPI:
    """Create a configured FastAPI application."""
    db_manager = database_manager or get_database_manager()
    app = FastAPI(title="Noticiencias API", version="1.0.0")
```

Calling `create_app()` with no argument falls back to `get_database_manager()`
(`news_collector/serving/api.py:550-564`), a module-level singleton that opens
the **real, configured production database**. Do not do this. Instead
construct an isolated `DatabaseManager` exactly the way
`tests/test_serving_admin_api.py:31-34` already does for the same purpose:

```python
db_manager = DatabaseManager({"type": "sqlite", "path": db_path})
```

where `db_path` is a throwaway file path (e.g. under `tempfile.mkdtemp()`),
then pass it explicitly: `create_app(database_manager=db_manager)`.

Every route in `create_app` is registered unconditionally — `grep -c
"@app\.\(get\|post\|put\|delete\)" news_collector/serving/api.py` returns 29,
and the only two `runtime.environment != "development"` checks in the file
(lines 402 and 446) are inside request-handler bodies, not around route
registration. This means `app.openapi()`'s output does **not** depend on
`ADMIN_API_KEY` being set or on `ENVIRONMENT` — you do not need to set any
environment variable to get a complete, representative document. The CORS
middleware (`ADMIN_CORS_ORIGINS`, read at `create_app` call time) also has no
effect on `app.openapi()`'s structure — leave it at its default.

FastAPI's built-in `app.openapi()` returns the full OpenAPI document as a dict
— no new routes or dependencies are needed beyond constructing the app this
way and dumping the result. This document snapshot is the backend half of
Phase 0's "API/OpenAPI ... snapshot" requirement; it is a **baseline artifact
for drift detection only**. Full OpenAPI-driven TypeScript client generation
is Phase 6 work (`plans/060/spec.md`, "Phase 6: Generate admin and
publication contracts") — out of scope here.

### `docs/audits/` convention (backend)

Backend already stores point-in-time analysis artifacts at `docs/audits/`
(e.g. `docs/audits/2026-08-plans-rejected-findings.md`). `scripts/check_doc_review.py:66-73`
classifies `docs/adr/`, `docs/audits/`, and `plans/` as `HISTORICAL_PREFIXES`
— edits there are not subject to the active-doc review gate that protects
files like `docs/PIPELINE_CONTRACTS.md`. This phase does not need to touch
`docs/audits/`; the failure inventory goes into `tests/fixtures/` instead (see
Step 3) because it is machine-readable migration input for Phase 2, not prose.

## Commands you will need

**Important — path resolution.** `check-contract-sync.js`'s default for
`BACKEND_SCHEMA_PATH` is `../noticiencias_news_collector/...`, a path
*relative to the frontend checkout*. That only resolves when the frontend
working copy is a sibling directory of a full backend checkout — true in the
normal two-repo layout, but **not** true inside an isolated `execute`
worktree, which is created outside that sibling layout. Before running any
command below in a worktree, export an **absolute** path instead of relying
on the default:

```bash
export BACKEND_SCHEMA_PATH=/absolute/path/to/noticiencias_news_collector/news_collector/contracts/frontend_schema.py
```

If you don't know the absolute path to a real backend checkout from inside
your worktree, STOP and report it — do not fall back to the relative default
and do not skip the command; both hide a real failure.

| Purpose | Command | Repo | Provenance | Expected on success |
|---|---|---|---|---|
| Strict editorial check | `STRICT_EDITORIAL=true node scripts/check-editorial-fields.js --json` | frontend | executed | exit 1 (fail is the expected/known state — see Step 3), JSON with `status`, `filesCount`, `v2Count`, `errors[]` on stdout |
| Contract snapshot (regenerate only if drifted) | `npm run sync:contract-snapshot` | frontend | declared (script exists, not run by this planning pass) | exit 0, `.contract-snapshots/frontend_schema.snapshot.json` written |
| Contract snapshot compare (verify current snapshot is fresh) | `BACKEND_SCHEMA_PATH=<absolute path, see above> node scripts/check-contract-sync.js --strict "$BACKEND_SCHEMA_PATH" src/content.config.ts` | frontend | declared | exit 0 |
| Frontend lint | `npm run lint` | frontend | declared | exit 0 |
| Frontend doc-drift | `npm run check:doc-drift` | frontend | declared | exit 0 |
| Backend doc-drift | `make docs-check` | backend | declared | exit 0 |
| Backend plans ledger check | `make plans-ledger-check` | backend | declared | exit 0 |
| Backend Python syntax check for new script | `python -c "import ast; ast.parse(open('scripts/generate_admin_openapi_snapshot.py').read())"` | backend | declared | no exception |
| Run new OpenAPI snapshot script | `python scripts/generate_admin_openapi_snapshot.py` | backend | declared (script does not exist yet — you are writing it in Step 4) | exit 0, writes `.contract-snapshots/admin_openapi.snapshot.json` |

## Scope

**In scope — backend (`noticiencias_news_collector/`):**
- `docs/adr/0006-durable-workflow-lifecycle-state.md` (new)
- `docs/adr/0007-generate-contracts-instead-of-hand-maintained-parsers.md` (new)
- `docs/adr/0008-harden-two-repo-boundary-before-reconsidering-consolidation.md` (new)
- `scripts/generate_admin_openapi_snapshot.py` (new)
- `.contract-snapshots/admin_openapi.snapshot.json` (new, generated — create the `.contract-snapshots/` directory if absent)
- `plans/060/phase-0-baseline/todo.md` (this phase's own checklist — check items off as you complete them)
- `plans/060/todo.md` (check off the four Phase-0 boxes under "Wave A" only)

**In scope — frontend (`noticiencias/`):**
- `docs/adr/0005-durable-workflow-lifecycle-state.md` (new)
- `docs/adr/0006-generate-contracts-instead-of-hand-maintained-parsers.md` (new)
- `docs/adr/0007-harden-two-repo-boundary-before-reconsidering-consolidation.md` (new)
- `tests/fixtures/publication-contract-corpus/` (new directory — see Step 3 for exact file list)

**Out of scope (do NOT touch, even though they look related):**
- Any change to `src/content.config.ts` validation logic — this phase only
  *reads* it to build fixtures; Phase 2 is where enforcement changes happen.
- Any change to `news_collector/contracts/frontend_schema.py` — same reason.
- Turning on `STRICT_EDITORIAL=true` anywhere in CI/deploy config — that is
  explicitly Phase 2 work and is currently gated on human content review.
- `.contract-snapshots/frontend_schema.snapshot.json` — leave it as-is unless
  your drift check proves it stale (see "Current state" above).
- Any file under `plans/048/` — unrelated, independent plan; do not touch.
- Any code in `serving/api.py` beyond importing `create_app` — do not add
  routes, do not modify the app factory, do not wire the new snapshot script
  into `Makefile`/CI in this phase (that wiring, and making it a CI gate that
  fails on staleness, is explicit Phase 1/Phase 6 work per the master plan).
- Rewriting or "fixing" any of the 30 posts missing v2 fields — Step 3 only
  *records* the failure list as a fixture; inventing field values to make
  posts pass is explicitly forbidden by the master plan's evidence baseline
  ("Never fabricate sources, fact checks, glossary entries, or confidence").

## Git workflow

- Backend branch: `architecture/060-00-baseline` (matches the master plan's
  `architecture/060-NN-slug` convention in its "Delivery strategy" section).
- Frontend branch: same name, `architecture/060-00-baseline`, in the frontend
  repo — these are two independent branches in two independent repos, not one
  branch spanning both.
- `plans/060/` (master + this phase's spec/todo) must already be committed on
  the base branch before you start — that is an operator precondition of
  dispatch, not a step in this plan. Do not commit it yourself; if it is
  missing, see the matching STOP condition below.
- Commit per step (Steps 1–5 below), conventional-commit style matching
  backend `git log` (e.g. `docs(adr): record durable workflow state decision`,
  `feat(contracts): add admin OpenAPI snapshot script`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run every `declared` command in the table above **on an unmodified checkout**,
in its own repo, before changing anything:

- Backend: `make docs-check`, `make plans-ledger-check`
- Frontend: `npm run lint`, `npm run check:doc-drift`, and (after exporting
  an absolute `BACKEND_SCHEMA_PATH` per "Commands you will need" above)
  `node scripts/check-contract-sync.js --strict "$BACKEND_SCHEMA_PATH" src/content.config.ts`

If they all pass: proceed to Step 1. If a `declared` command does not exist or
fails on the unmodified checkout: STOP and report it with the exact command
and output — do not fix a pre-existing failure as part of this phase.

**Verify**: all five commands above exit 0. (This does not include the
strict-editorial check from the table above — that command's expected exit
code is 1, not 0; it is exercised separately in Step 3, not as a Step 0
baseline gate.)

### Step 1: Write the three ADR pairs

Write three ADRs in the backend repo (`0006`, `0007`, `0008`) and three
matching ADRs in the frontend repo (`0005`, `0006`, `0007`). "Matching" does
**not** mean byte-identical files — each repo's ADR is written from that
repo's vantage point and cross-references its sibling by relative path, the
same way you'd reference a file two directories up. Use the fuller
ADR-0003-style structure (Context / Decision / Consequences / Alternatives
Considered, with an optional Rollback section where relevant), not the bare
template.

**1a. Durable workflow lifecycle state** (backend `0006`, frontend `0005`)

- Context: `Article.processing_status` plus `article_metadata` JSON currently
  carries publication and audit state; it cannot be queried or reconciled
  reliably (this is measured, not speculative — see master plan's evidence
  baseline row "Operational history").
- Decision: add five new additive SQLite tables —
  `workflow_runs`, `workflow_stage_attempts`, `editorial_decisions`,
  `publication_attempts`, `publication_events` — as the source of truth for
  operational lifecycle state, built in Phase 3 of the master plan. Keep
  existing `Article` columns as a dual-written compatibility projection during
  migration; do not drop anything in this ADR's scope (that's a future
  cleanup phase, per the master plan's "Rollout and rollback rules": expand →
  dual-write → compare → cut over → clean up).
  Pull the full field lists for these five tables verbatim from
  `plans/060/spec.md`, section "## Data contracts to add" (lines 148–211) —
  do not re-derive or paraphrase them; copy the table definitions as given
  there, since Phase 3 will implement exactly what this ADR records.
- Alternatives considered: keep the JSON-blob approach (rejected — unqueryable,
  already measured as a reliability gap); move to PostgreSQL (rejected — ADR
  already exists and is settled: plan 046, operator decision 2026-08-11,
  SQLite-only); an external state store/Redis/Kafka (rejected — explicitly
  out of scope per master plan's "Out of scope" section, no new infrastructure).
- The frontend counterpart ADR should be shorter: it records that the
  frontend's publication callback recipient (`publication_events` /
  reconciliation semantics from Phase 5) now has a durable, queryable backend
  counterpart, cross-references backend ADR-0006, and notes the frontend has
  no schema changes of its own here — this ADR exists so a frontend-only
  reader understands why backend publication-attempt IDs are now stable and
  reconcilable.

**1b. Generate contracts instead of hand-maintained parsers** (backend `0007`,
frontend `0006`)

- Context: `scripts/check-contract-sync.js` (frontend) is a 1,488-line
  regex parser of both Python and TypeScript; `apps/admin/src/lib/types.ts`
  (frontend) is a handwritten mirror of the backend admin API with
  `api.ts` casting response JSON. Both are measured drift-detection gaps (see
  master plan's evidence baseline rows "Contract parser" and "Admin types").
- Decision: adopt native, documented generation instead of the custom parser —
  FastAPI's `app.openapi()` / `BaseModel.model_json_schema()` for the admin
  HTTP contract (owns TypeScript client generation via `openapi-typescript`);
  Zod 4's `z.toJSONSchema()` for a generated neutral JSON Schema from the
  frontend's structural publication schema, compared against backend Pydantic
  on a shared valid/invalid fixture corpus (this phase's Step 3 output).
  Retire the regex parser only after one full release window of proven parity
  — this ADR records the target state; Phase 6 of the master plan implements
  it. Link the five reference URLs listed in `plans/060/spec.md`, section
  "## Primary implementation references" (lines 228-241), in this ADR's
  Decision section.
- Alternatives considered: keep the hand-maintained mirror/parser (rejected —
  proven drift risk, that's why this ADR exists); generate the frontend Zod
  schema from the backend Pydantic model or vice versa (rejected — inverts
  the ownership rule already established in backend ADR-0003: frontend Zod is
  publication-input authority, FastAPI/Pydantic is admin-HTTP-contract
  authority; this ADR does not change ADR-0003, it implements its next step).
- Frontend counterpart: same content, frontend vantage point, noting that
  `check-contract-sync.js` is explicitly *not* deleted by this ADR — only
  scheduled for retirement after the compatibility window in Phase 6.

**1c. Harden the two-repo boundary before reconsidering consolidation**
(backend `0008`, frontend `0007`)

- Context: backend ADR-0003 already decided to keep two repositories with a
  contract-mirror pattern. Plan 060's evidence baseline shows the current pain
  (v2 posts failing strict validation, admin state lost on restart, callback
  reconciliation gaps, etc.) comes from *unenforced contracts and missing
  durable state*, not from the repository boundary itself.
- Decision: this ADR does not reverse or supersede ADR-0003. It records the
  explicit sequencing decision: harden contracts/state/observability first
  (plan 060, all phases), then — and only then — measure actual cross-repo
  coordination overhead for at least one release window and write an
  evidence-based keep-split-or-consolidate decision (master plan Phase 11).
  Reconsidering consolidation before that measurement is a listed
  program-wide STOP condition in `plans/060/spec.md` ("Program-wide STOP
  conditions": "repository consolidation is proposed without measured
  post-hardening cost").
- Alternatives considered: consolidate into a monorepo now (rejected —
  premature per the STOP condition above; also explicitly listed under
  `plans/060/spec.md`'s "Out of scope": "A big-bang monorepo move or
  framework/language rewrite"); do nothing / leave ADR-0003 as the last word
  (rejected — the evidence baseline shows real, measured reliability gaps that
  need addressing regardless of eventual repo shape).
- Status field: use `Proposed` for all six ADRs in this step — they record
  decisions that Phase 0 makes but that later phases (2, 3, 5, 6, 11) actually
  implement and validate. Do not mark them `Accepted` until the master plan's
  own Phase 11 done criterion ("the final repository-shape ADR is based on
  measured post-hardening evidence") closes the loop — that is out of scope
  for this phase; leave them `Proposed`.

**Verify**: `ls docs/adr/000{6,7,8}-*.md` (backend) lists exactly three new
files; `ls docs/adr/000{5,6,7}-*.md` (frontend) lists exactly three new files;
each file parses as valid Markdown with a `# ADR-NNNN:` H1 and all four
required sections (`## Context`, `## Decision`, `## Consequences`,
`## Alternatives considered` or `## Alternatives Considered`).

### Step 2: Confirm the publication-schema snapshot is current (frontend)

Per "Current state" above, `.contract-snapshots/frontend_schema.snapshot.json`
should already be fresh as of both baseline SHAs. Confirm this rather than
blindly regenerating (with `BACKEND_SCHEMA_PATH` exported as an absolute path,
per "Commands you will need"):

```bash
node scripts/check-contract-sync.js --strict "$BACKEND_SCHEMA_PATH" src/content.config.ts
```

- If this exits 0: the live schemas agree, and the committed snapshot (synced
  more recently than either schema last changed) is current. No file changes
  needed for this step — do not touch `.contract-snapshots/` in this case.
- If this fails: your drift check at the top of this plan should already have
  caught the underlying schema change. With `BACKEND_SCHEMA_PATH` still
  exported as an absolute path (it drives the same default inside
  `sync:contract-snapshot`'s own command), run
  `npm run sync:contract-snapshot` to regenerate, commit the updated snapshot,
  and note the drift in your final report — do not silently absorb it.

**Verify**: `node scripts/check-contract-sync.js --strict ...` (command above)
exits 0, and `git status --short .contract-snapshots/` is empty (no
unexpected regeneration happened).

### Step 3: Commit the shared publication-contract corpus (frontend)

Create `tests/fixtures/publication-contract-corpus/` with:

- `README.md` — explain: this corpus is the shared valid/invalid fixture set
  used across plan 060 (Phase 0 commits it; Phase 2 uses it to prove
  producer/consumer v2 rejection; Phase 6 uses it to prove Zod/JSON
  Schema/Pydantic parity). State its version (start at `v1`) and that new
  fixtures require a version bump plus a note in this README, not silent
  edits to existing fixture files (existing fixtures are frozen once other
  phases start depending on them).
- `valid/v1-complete.json` — a complete, schema-version-1 publication object
  (no v2 fields), field-shape-accurate per `src/content.config.ts` lines
  10–48 (the non-v2 fields).
- `valid/v2-complete.json` — copy the real frontmatter from
  `src/content/posts/2026-08-12-un-modelo-de-ia-realizo-mas-de-17-500-acciones-en-hugging-face.md`
  as structured JSON (YAML frontmatter → equivalent JSON object; do not
  paraphrase field values).
- `invalid/v2-missing-summary-points.json`, `invalid/v2-missing-glossary.json`,
  `invalid/v2-missing-fact-check.json`, `invalid/v2-missing-why-it-matters.json`,
  `invalid/v2-missing-confidence.json`, `invalid/v2-missing-sources.json` — each
  is `valid/v2-complete.json` with exactly one of the six required v2 fields
  removed (one fixture per field, matching the six error types seen in the
  live failure inventory below).
- `invalid/v2-empty-summary-points.json` — `summary_points: []` (violates the
  2–5 item minimum at `content.config.ts:115-119`).
- `invalid/v2-too-many-summary-points.json` — `summary_points` with 6 items
  (violates the max-5 constraint).
- `edge-cases/date-formats.json` — an array of a few date-string variants seen
  in real content (check 2–3 real posts under `src/content/posts/` for the
  `date`/`published` field's actual string format; use real observed formats,
  not invented ones).
- `edge-cases/source-objects.json` — a `sources` array exercising the optional
  fields: one source with only `title`+`url`, one with all four fields
  (`title`, `url`, `publisher`, `date`).
- `edge-cases/defaults.json` — an object omitting every field that has a
  `.default(...)` in `content.config.ts` (e.g. `author`, `categories`, `tags`,
  `schema_version`), to characterize default-application behavior later.
- `edge-cases/additional-property-stripped.json` — a valid `v2-complete.json`
  plus one extra unknown top-level field (e.g. `"not_a_real_field": true`).
  **Verified for this plan**: `grep -n "\.strict()\|\.passthrough()" src/content.config.ts`
  returns no matches, so Zod's default applies — unknown keys are silently
  stripped, not rejected. Name and describe this fixture accordingly (it
  characterizes *stripping*, not rejection); do not call it "-rejected". Note
  in the corpus README that this is a live design gap Phase 6 must decide on
  explicitly when generating the neutral JSON Schema (strip vs. reject
  unknown keys), since JSON Schema's default (`additionalProperties: true`)
  and Pydantic's default (ignore-and-drop, unless `extra="forbid"`) don't
  automatically agree with each other either.
- `v2-strict-failure-inventory.json` — the JSON output of
  `STRICT_EDITORIAL=true node scripts/check-editorial-fields.js --json` run
  against the current `src/content/posts/` corpus at frontend commit
  `237cd13` (record this SHA inside the fixture, e.g. as a top-level
  `"_generated_at_commit": "237cd13"` key added after parsing the tool's
  JSON — the tool's own output has no such field). **This command exits 1 by
  design when validation fails — that is success for this step, not an
  error**; capture its stdout, don't treat the non-zero exit as a problem.
  This is the migration input Phase 2 will use for its human content review —
  do not edit, filter, or invent values in the `errors[]` array; only the
  wrapping `_generated_at_commit` key is added on top.

**Verify**: `find tests/fixtures/publication-contract-corpus -name "*.json" | xargs -I{} python3 -c "import json,sys; json.load(open('{}'))"`
exits 0 for every file (all fixtures are valid JSON). For the failure
inventory, since frontend content is edited by automated PRs and can drift
day to day, don't assert byte-identity against an arbitrary future re-run;
instead re-run the check now and confirm the `errors[]` *content* (ignoring
key order) matches what you committed, and confirm `git rev-parse --short HEAD`
in the frontend repo still equals the `_generated_at_commit` value you
recorded — if it doesn't match, you're on a different commit than the one the
inventory documents, which is expected in the future but should not happen
during this same phase's execution.

### Step 4: Add the backend OpenAPI snapshot script and generate the snapshot

Create `scripts/generate_admin_openapi_snapshot.py`:

- Import `create_app` from `news_collector.serving.api` and `DatabaseManager`
  from `news_collector.storage.database`.
- Construct an isolated, throwaway database exactly as specified in "Current
  state" above:

  ```python
  import tempfile
  from pathlib import Path

  db_path = Path(tempfile.mkdtemp()) / "openapi_snapshot.db"
  db_manager = DatabaseManager({"type": "sqlite", "path": db_path})
  app = create_app(database_manager=db_manager)
  ```

  Do not call `create_app()` with no arguments — that falls back to
  `get_database_manager()`, the production singleton. If constructing
  `DatabaseManager` this way raises, STOP and report the exact error — do not
  fall back to the production singleton to work around it.
- Call `app.openapi()`, which returns a plain `dict`.
- Serialize with `json.dumps(doc, indent=2, sort_keys=True)` for determinism
  (sorted keys means the same app produces byte-identical output on repeat
  runs — this is required, verify it in the check below).
- Write to `.contract-snapshots/admin_openapi.snapshot.json` (create the
  `.contract-snapshots/` directory in the backend repo if it does not exist —
  it is a new directory in this repo; the frontend repo's own
  `.contract-snapshots/` is unrelated and untouched).
- Print the output path on success; exit non-zero with a clear message on
  any exception (do not swallow errors — this project bans
  `except Exception: pass` everywhere, per `CLAUDE.md`).

Run it twice in a row and diff the two outputs to prove determinism:

```bash
python scripts/generate_admin_openapi_snapshot.py
cp .contract-snapshots/admin_openapi.snapshot.json /tmp/openapi-run1.json
python scripts/generate_admin_openapi_snapshot.py
diff /tmp/openapi-run1.json .contract-snapshots/admin_openapi.snapshot.json
```

**Verify**: both runs exit 0; the `diff` is empty (byte-identical output);
`.contract-snapshots/admin_openapi.snapshot.json` is valid JSON
(`python3 -c "import json; json.load(open('.contract-snapshots/admin_openapi.snapshot.json'))"`
exits 0) and contains a top-level `"openapi"` key.

### Step 5: Close out the phase

- Check off the four Phase-0 checkboxes under "Wave A → Phase 0" in
  `plans/060/todo.md` (lines 20-27 as currently written — re-read them first
  in case your drift check found changes):
  - "Add matching ADRs for durable state, generated contracts, and the
    harden-before-consolidating repository decision." → Step 1
  - "Add the versioned shared publication valid/invalid fixture corpus." →
    Step 3
  - "Add deterministic OpenAPI/publication schema snapshot commands." →
    Steps 2 and 4
  - "Preserve the strict editorial failure inventory as migration input." →
    Step 3 (`v2-strict-failure-inventory.json`)
  - Leave "Verify snapshot generation twice with byte-identical output."
    checked only if you actually ran the two-pass diff in Step 4 (you did) —
    check it.
- Check off this phase's own `plans/060/phase-0-baseline/todo.md` checklist
  (see that file).
- Do **not** touch any Wave B–E checkboxes, and do not mark plan 060 itself
  DONE in `plans/README.md` — this phase is one of eleven; the master plan
  stays `TODO` until Phase 11 closes it out (per the master plan's "Final
  closeout": "Archive plan 060 ... only after all phases are complete").

**Verify**: `git diff --stat` (backend) and `git diff --stat` (frontend) each
show only the in-scope files from the "Scope" section above, plus the two
todo-checkbox edits.

## Test plan

This phase adds no application code and no test suite changes beyond the
fixture corpus itself — the corpus's own validity *is* the test (see Step 3's
verification: every fixture must parse as JSON, and the failure-inventory
fixture's `errors[]` content must match a fresh tool run at the SHA it
records). No new Vitest/pytest files are required in this phase; Phase 2 and
Phase 6 are where the corpus gets wired into actual test suites that assert
against it.

## Done criteria

Machine-checkable. ALL must hold:

- Backend: `ls docs/adr/0006-*.md docs/adr/0007-*.md docs/adr/0008-*.md`
  succeeds (three files exist)
- Frontend: `ls docs/adr/0005-*.md docs/adr/0006-*.md docs/adr/0007-*.md`
  succeeds (three files exist)
- `find tests/fixtures/publication-contract-corpus -name "*.json"` (frontend)
  lists at least 12 files (README doesn't count; count the fixtures listed in
  Step 3) and every one parses as valid JSON
- `v2-strict-failure-inventory.json`'s `_generated_at_commit` equals
  `git -C <frontend repo> rev-parse --short HEAD` at the time you committed
  it, and its `errors[]` content (order-independent) matches a fresh
  `STRICT_EDITORIAL=true node scripts/check-editorial-fields.js --json` run
  (exit code 1 expected — that is not a failure of this check)
- `python scripts/generate_admin_openapi_snapshot.py` (backend, using the
  isolated `DatabaseManager` construction from Step 4) run twice produces
  byte-identical `.contract-snapshots/admin_openapi.snapshot.json`
- With `BACKEND_SCHEMA_PATH` exported as an absolute path:
  `node scripts/check-contract-sync.js --strict "$BACKEND_SCHEMA_PATH" src/content.config.ts`
  (frontend) exits 0 (publication schema snapshot confirmed current, or
  regenerated if drifted)
- `make docs-check && make plans-ledger-check` (backend) exits 0
- `npm run lint && npm run check:doc-drift` (frontend) exits 0
- `git diff --stat` (each repo) lists only the files named in "Scope" plus
  the two todo checklists
- Both `plans/060/todo.md` (Phase 0 rows) and
  `plans/060/phase-0-baseline/todo.md` are checked off

## STOP conditions

Stop and report back (do not improvise) if:

- The code/docs at the locations in "Current state" don't match the excerpts
  given here (drift since this plan was written) — especially: if
  `content.config.ts`'s field list or line numbers have shifted, re-derive
  the fixture shapes from the live file rather than trusting the excerpt, but
  STOP first and report the drift before proceeding.
- The re-run strict editorial check produces different counts than
  `filesCount: 31, v2Count: 31, 30 failing files, 180 errors` — this means
  content changed since the master plan's baseline; report the new numbers,
  do not silently substitute them into the fixture without flagging it.
- `create_app()` cannot be constructed without live secrets/database/network
  access in Step 4.
- You find yourself needing to invent field values (a fake source URL, a
  fabricated confidence level, etc.) to make any fixture "look realistic" —
  use structurally valid but clearly-synthetic placeholder values instead
  (e.g. `"https://example.com/source"`), consistent with how the existing
  `tests/fixtures/pipeline_e2e/*.json` fixtures already use `example.com`
  URLs.
- `plans/060/` is still untracked in your worktree when you start (see Git
  workflow) — this means the prerequisite commit didn't happen; report it
  rather than guessing whether to make it yourself.
- Either repo's Step 0 baseline commands fail on an unmodified checkout.

## Maintenance notes

- The six ADRs written here are read by every subsequent phase's executor as
  load-bearing context (Phase 2, 3, 5, 6, and 11 all cite decisions this phase
  records). If a later phase's plan quotes this ADR content and it doesn't
  match what you actually wrote, that later phase's drift check should catch
  it — but flag in your final report exactly which ADR file/section future
  phases should treat as authoritative if you deviated from the outline
  above.
- The fixture corpus's `README.md` versioning note matters: Phase 6 explicitly
  needs Zod/JSON-Schema/Pydantic parity proven "on the shared corpus" — if a
  later phase adds fixtures without bumping the version and noting it, parity
  proofs become silently untrustworthy. Make the versioning instruction in
  the README explicit and easy to follow.
- The OpenAPI document's structure does not depend on `ADMIN_API_KEY` or
  `ENVIRONMENT`/`ADMIN_CORS_ORIGINS` — verified for this plan by confirming
  all 29 routes in `news_collector/serving/api.py` are registered
  unconditionally (the only environment checks are inside handler bodies, at
  lines 402 and 446). A future CI staleness gate built on this snapshot (Phase
  1/6 work) does not need to pin any environment variable to stay stable —
  if that stops being true (e.g. a future change makes route registration
  conditional), whoever adds that gate should revisit this note.
- The backend OpenAPI snapshot script from Step 4 is intentionally not wired
  into any Makefile target or CI job in this phase — that wiring (and making
  staleness a CI failure) is Phase 1 (dashboard/CI gaps) and Phase 6
  (generated contracts) work. A reviewer should not expect `make verify-ci`
  to invoke this script yet.
