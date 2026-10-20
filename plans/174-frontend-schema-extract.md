# Plan 174: Extract the structural post schema (060 Phase 6, step 1)

> Execute step by step; run every verification; stop on STOP conditions.
> **Drift check (frontend)**: `git diff --stat 56957484..origin/main -- src/content.config.ts scripts/check-contract-sync.js tests/`
> (use the current frontend `origin/main`; read the live files first).

## Status

- **Priority**: P2 (060 Phase 6)
- **Effort**: M
- **Risk**: MEDIUM (content validation is the publication gate; the contract-sync parser is line-based)
- **Depends on**: none
- **Category**: frontend schema / contracts
- **Planned at**: backend `62281a05`, frontend `a1a13741`, 2026-10-20

## Why this matters

`src/content.config.ts` (304 lines) contains the full structural Zod schema
**and** the Astro-specific refinements. 060 Phase 6 wants the structural schema
in its own module so a neutral JSON Schema can be generated and parity with the
Pydantic mirror can be proven. This first step only **extracts** the structure;
it must not change validation behaviour, and the line-based
`scripts/check-contract-sync.js` must keep extracting the same top-level fields.

## Current state (read the live files first)

- `src/content.config.ts` — imports `z` from `astro/zod`, defines module-scope
  constants (`SOCIAL_ID_RE`, comment blocks) and `posts = defineCollection({
  schema: z.object({ ... }).superRefine(...) })` (the object starts ~line 65).
- `scripts/check-contract-sync.js` — line-based extraction of top-level Zod
  fields from `src/content.config.ts`; comments inside the object body are not
  supported (hence the module-scope comment blocks).
- `tests/content-config-schema.test.ts` — frontend schema cases.
- The backend mirror is `news_collector/contracts/frontend_schema.py`
  (`AstroPost`), used by the backend parity test (strict field-name equality).
- Node modules are not installed in the main checkout; use `npm ci` in your
  worktree (network, minutes).

## Scope

**In scope (frontend repo only)**: new `src/schemas/post.ts` (or a similar
clearly named module), `src/content.config.ts` (import the structural schema,
keep the refinements), `scripts/check-contract-sync.js` (read the schema from
the new module), `tests/` for the parser/schema, `docs/` only if a path is
documented.

**Out of scope**: JSON Schema generation, parity tests, Pydantic changes,
retiring the regex parser, any post content, the backend repo.

## Steps

1. **Understand the parser before moving anything**: locate the top-level
   field-extraction logic in `scripts/check-contract-sync.js`; record which
   file/path it reads and how it handles comments/indentation. If updating it
   to read a module is a major rewrite, STOP (report the exact limitation).
2. Create `src/schemas/post.ts`:
   - import `z` from `astro/zod` (do not add a second Zod instance);
   - move the structural `z.object({...})` **verbatim** (field names, types,
     defaults, constraints, `.strict()`/`.optional()` calls);
   - export it (e.g., `postStructuralSchema`);
   - move only the module-scope constants it needs (`SOCIAL_ID_RE`, etc.).
     Keep the explanatory comments wherever they are allowed; if the parser
     cannot skip comments in the new module, keep those comments outside the
     object as today.
3. `src/content.config.ts`: import the structural schema, keep the existing
   `.superRefine(...)`/date/semantic refinements exactly as they are, and pass
   the composed schema to `defineCollection`. The exported collections and
   every refinement behaviour must be identical.
4. Update `scripts/check-contract-sync.js` to read the new module (and keep
   working if the schema is re-exported from `content.config.ts`). Preserve the
   extracted top-level field set; no new/stale fields.
5. Tests:
   - `tests/content-config-schema.test.ts` unchanged/绿色 (it validates through
     the collection);
   - add a parser test asserting the extracted field set is identical to the
     expected list (or keep the existing parity test green);
   - build the site and compare a sample of generated pages before/after
     (hashes) — no content/HTML change expected.
6. Gates: `npm ci`, `npm run lint`, `npx astro check`, `npm run build`,
   `npm run test:audit`, `npm run check:contract-sync` (with the backend
   sibling path), `npm run format:check`.

## Done criteria

- [ ] Structural schema lives in `src/schemas/post.ts`; refinements stay in `content.config.ts`
- [ ] Same top-level fields, same validation behaviour (schema tests + build)
- [ ] `check-contract-sync` extracts the same field set and the backend parity test passes
- [ ] 940 frontend tests, lint, astro check and build green
- [ ] No content/backend change; diff limited to the in-scope files
- [ ] Ledger row 174 updated by the reviewer

## STOP conditions

- The parser cannot read the module without a major rewrite (report the
  limitation; do not retire/weaken it).
- Moving the schema requires a second `zod` instance or an Astro API change.
- Any validation behaviour changes (a post that passed/failed differently).
- A post/frontmatter needs editing → STOP.

## Next slices (do not do here)

- JSON Schema generation (`z.toJSONSchema` or an approved generator) with
  explicit date handling.
- Zod/JSON Schema/Pydantic parity on a shared corpus.
- Retire the regex parser only after a release window of parity.
