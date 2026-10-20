# Plan 175: Generate the post JSON Schema and prove Zod/JSON Schema/Pydantic parity

> Two phases, two repos. **Phase F (frontend) merges first**; Phase B (backend)
> reads its artifact and corpus. Run every verification; stop on STOP.
>
> **Drift check (frontend)**: `git diff --stat ee12c38d..origin/main -- src/schemas/post.ts src/content.config.ts tests/ package.json`
> **Drift check (backend)**: `git diff --stat 06e291ad..HEAD -- news_collector/contracts/frontend_schema.py tests/`

## Status

- **Priority**: P2 (060 Phase 6, steps 3–4)
- **Effort**: M
- **Risk**: MEDIUM (generated contract; date/unknown-property semantics)
- **Depends on**: 174 (schema module), 060 Phase 0 corpus
- **Category**: frontend contract / parity
- **Planned at**: backend `06e291ad`, frontend `ee12c38d`, 2026-10-20

## Why this matters

The structural schema is extracted (174) and the shared corpus exists
(`tests/fixtures/publication-contract-corpus`, currently unused). 060 Phase 6
requires a **neutral JSON Schema** generated with stable Zod 4 APIs and
**parity with the Pydantic mirror** on that corpus. This closes the loop
between Zod (frontend load), JSON Schema (neutral artifact) and Pydantic
(backend contract) and is the prerequisite for eventually retiring the
line-based parser.

## Facts (verified)

- Astro 7.4 depends on `zod ^4.6.6` (Zod 4, `z.toJSONSchema` available).
- `src/schemas/post.ts` has `date: z.date()` and one union (`image`); no
  `any`/`custom`/`record`.
- The corpus has `valid/` (v1, v2), `invalid/` (v2 missing/empty/too-many),
  `edge-cases/` (date formats, source objects, defaults, extra property) and a
  README with a versioning rule.
- Pydantic `AstroPost.date: Union[date, datetime]`; `AstroPost` has **no**
  `extra="forbid"` (extras are accepted and ignored), matching Zod's default
  stripping. The JSON Schema should therefore **allow** additional properties
  (default) and the extra-property edge case must pass everywhere.
- `jsonschema` is **not** in the backend venv (and adding it needs a lock change).
  Phase B therefore proves the artifact↔Pydantic contract **structurally**; the
  artifact↔corpus validation is already proven in the frontend with Ajv 8.20.0 +
  ajv-formats 3.0.1. The three layers are covered transitively and the known
  semantic gaps are explicit.
- The frontend has no node_modules in the main checkout; use `npm ci`.

## Phase F — frontend (PR first)

**Branch**: `feat/post-json-schema`. Do not touch the backend or posts.

1. Add dev deps pinned exactly: `ajv@8.20.0`, `ajv-formats@3.0.1`.
2. Add `tests/post-json-schema.test.ts`:
   - Import `postStructuralSchema`; generate with
     `z.toJSONSchema(postStructuralSchema, { /* stable options */ })`.
   - Set `$schema` to the 2020-12 dialect and a title; make the output
     deterministic (stable key order, 2-space JSON, trailing newline).
   - **Date handling (explicit)**: the neutral artifact represents frontmatter
     dates as strings, matching Pydantic's `Union[date, datetime]`: override
     the generated `date` property to
     `{ "oneOf": [ {"type":"string","format":"date"},
     {"type":"string","format":"date-time"} ] }`.
   - Leave additional properties allowed (the default); assert the
     `additional-property-stripped` fixture still validates.
   - Compare the generated object to the committed
     `src/schemas/post.schema.json`; with `UPDATE_SCHEMA=1`, write it instead
     (deterministic regeneration). Add a `package.json` script for the update
     (`schema:update`).
   - **Corpus tests** (Ajv 2020 + ajv-formats):
     - `valid/v1-complete.json`, `valid/v2-complete.json`,
       `edge-cases/defaults.json`, `edge-cases/additional-property-stripped.json`
       → valid;
     - every `invalid/*.json` → invalid;
     - each value in `edge-cases/date-formats.json`, substituted into
       `v2-complete`, → valid.
   - **Zod tests** on the same corpus: convert the `date` string to a `Date`
     before `postStructuralSchema.parse` (Astro supplies Dates); valid set
     passes, invalid set fails. Document this conversion in the test.
3. Commit `src/schemas/post.schema.json` + the test + deps + scripts.
4. Update `tests/fixtures/publication-contract-corpus/README.md`: add a
   "Phase 6 (v1 results)" note with the date decision, the unknown-property
   decision, and how to regenerate.
5. Gates: `npm ci`, `npm run lint`, `npx astro check`, `npm run build`,
   `npm run test:audit`, `npm run format:check`,
   `BACKEND_SCHEMA_PATH=<backend>/news_collector/contracts/frontend_schema.py npm run check:contract-sync`.
6. Open the PR, wait for checks, merge, report the merge commit.

**STOP** if `z.toJSONSchema` cannot represent the structural schema (report the
unrepresentable node); if a valid fixture cannot be made to pass both Zod and
the JSON Schema without changing the schema; if a date representation cannot
match the corpus and Pydantic.

## Phase B — backend (PR second, amended 2026-10-20)

**Branch**: `advisor/175-schema-parity`. Base: current `main` after F merges.
**Do not add `jsonschema`** (absent from the venv; a lock change is out of
scope). Prove the artifact↔Pydantic contract structurally; the artifact↔corpus
validation lives in the frontend Ajv tests (merged), so the three layers are
covered transitively.

1. Add `tests/test_post_schema_parity.py`:
   - Resolve `../noticiencias/src/schemas/post.schema.json` and
     `../noticiencias/tests/fixtures/publication-contract-corpus/`; skip when
     the frontend is absent **unless** `CI_EXPECTED_FRONTEND_SCHEMA` is set
     (then fail closed).
   - **Expectation matrix** (do not use a generic "all invalid reject" loop):
     | fixture | Pydantic `AstroPost` | JSON Schema (frontend Ajv, merged) |
     |---|---|---|
     | valid/v1-complete, valid/v2-complete, defaults, additional-property-stripped | accept | accept |
     | invalid/v2-empty-summary-points, invalid/v2-too-many-summary-points | reject | reject (structural) |
     | invalid/v2-missing-{summary-points,glossary,fact-check,confidence,sources} | reject | accept (superRefine semantic gaps) |
     | invalid/v2-missing-why-it-matters | accept | accept (stale corpus label, P0-06/DEC-003) |
     | edge date-formats (3 values) | accept | accept |
     | edge source-objects (2 items) | accept | accept |
     | derived `2026-08-12T00:00:00Z` | accept | accept |
     | `2026-13-40`, `not-a-date`, `2026-02-30` | reject | reject |
     | `ftp://` sources[].url | reject | accept (format: uri; named divergence) |
     Assert each row with the fixture name; the semantic-gap rows assert the
     **divergence itself** (schema accepts, Pydantic rejects) and reference the
     frontend test that pins it. Never mark a semantic gap as a failure of the
     contract.
   - **Structural parity**: `AstroPost.model_json_schema()` vs the artifact:
     property names, required set, enum sets, basic types, `social`
     `additionalProperties: false`, top-level extras allowed. Allowlist only:
     date `anyOf`/`oneOf`, descriptions/titles/defaults, Zod numeric bounds,
     and the Pydantic before-validator null nuance. Assert the allowlist is
     explicit and the lists are otherwise empty.
   - Do **not** try to validate the JSON Schema with Python (no `jsonschema`).
2. `.github/workflows/ci.yml`: the unit/type jobs (both `type` and `test`)
   already fetch `src/content.config.ts` + `src/schemas/post.ts`; add
   `src/schemas/post.schema.json` and
   `tests/fixtures/publication-contract-corpus/` to their sparse checkouts and
   copy them to `../noticiencias/src/schemas/` and
   `../noticiencias/tests/fixtures/publication-contract-corpus/` (mkdir -p).
   Keep `CI_EXPECTED_FRONTEND_SCHEMA: "1"`.
3. `docs/PIPELINE_CONTRACTS.md`: short section (source of truth, regeneration
   command `npm run schema:update`, structural scope, the semantic gap list).
4. Gates: `make test`, `make test-contracts`, `make test-boundaries`,
   `make lint`, `make type` (committed), `make docs-check`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.
   Simulate the CI layout with only the copied frontend files; present → green,
   missing → fail closed.

**STOP** if a corpus fixture disagrees structurally (not one of the listed
semantic gaps); if the structural comparison needs a broad allowlist; if the
frontend artifact is missing in CI.

## Done criteria

- [ ] Committed, deterministic `src/schemas/post.schema.json` generated from `postStructuralSchema`
- [ ] Date representation matches the corpus and Pydantic (`date`/`date-time`)
- [ ] Frontend: valid/invalid/edge corpus agrees between Zod and Ajv
- [ ] Backend: the same corpus agrees between Pydantic and the JSON Schema
- [ ] Structural field/required parity asserted with explicit, documented differences
- [ ] No post content or production runtime change
- [ ] Merge order F then B; ledger row 175 updated by the reviewer

## Next (not here)

- Retire the regex parser only after a release window with the generated
  contract green.
- Cross-field refinements as JSON Schema `if/then` only if evidence requires
  them (the corpus does not today).
