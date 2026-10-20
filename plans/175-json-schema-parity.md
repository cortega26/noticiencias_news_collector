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
- `jsonschema` is available in the backend venv; Ajv 8.20.0 + ajv-formats
  3.0.1 are the pinned frontend dev deps for the test (no runtime impact).
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

## Phase B — backend (PR second)

**Branch**: `advisor/175-schema-parity`. Base: current `main` after F merges.

1. Add `tests/test_post_schema_parity.py`:
   - Resolve `../noticiencias/src/schemas/post.schema.json` and the corpus;
     `pytest.skip` when the frontend is absent (CI checks out the frontend for
     the contract gate — verify the path/step and say so).
   - Load the JSON Schema with `jsonschema.Draft202012Validator` (formats: use
     `FormatChecker` if available; otherwise assert the date pattern manually).
   - For every valid fixture: `AstroPost.model_validate` passes **and** the
     JSON Schema validates it. For every invalid fixture: Pydantic raises
     `ValidationError` **and** the JSON Schema rejects it. Report any
     disagreement with the fixture path (this is the parity assertion).
   - Date formats: substitute each string into v2 and assert both pass.
   - Structural check: `AstroPost.model_json_schema()` top-level property names
     and required set match the JSON Schema's; allowed, explicitly listed
     differences (date union representation, descriptions/metadata,
     `additionalProperties`) must be asserted, not silently ignored.
   - Document cross-field invariants that JSON Schema does not encode; assert
     they are covered by existing Zod/Pydantic tests (add a focused assertion
     if the corpus lacks one).
2. `docs/PIPELINE_CONTRACTS.md`: one short section on the generated JSON
   Schema, its source of truth (`src/schemas/post.ts`), the regeneration
   command, and the known representation limits (cross-field refinements).
3. Gates: `make test`, `make test-contracts`, `make test-boundaries`,
   `make lint`, `make type` (committed), `make docs-check`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.

**STOP** if a corpus fixture disagrees between Pydantic and the JSON Schema in
a way that requires changing the contract (report the fixture and values); if
the frontend artifact is missing in CI; if the structural comparison needs a
broad allowlist (report it).

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
