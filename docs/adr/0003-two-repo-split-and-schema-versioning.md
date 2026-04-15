# ADR-0003: Two-Repo Split and Schema Versioning

**Date**: 2025-01-01  
**Status**: Accepted  
**Deciders**: Engineering team

---

## Context

The Noticiencias product consists of two distinct concerns:

1. **Content collection and enrichment** — scraping, LLM enrichment, quality scoring, and export.
2. **Content rendering and delivery** — static site build, SEO, image pipeline, and CDN deployment.

Before the two-repo split these concerns lived in a single repository. That arrangement created coupling problems: front-end Astro/Node build tooling and back-end Python/SQLite tooling pulled in conflicting dependency expectations, CI jobs had to run on incompatible runtimes simultaneously, and deployments were blocked by unrelated test failures in the other layer.

A secondary consequence of co-location was that the content schema was implicitly shared: the Astro `posts` collection Zod schema and the Python `AstroPost` Pydantic model drifted independently because there was no enforced boundary.

---

## Decision

The project is structured as two sibling repositories with a **contract-mirror pattern**:

- `noticiencias` (front-end, Astro) owns the canonical `posts` schema via `src/content/config.ts`.
- `noticiencias_news_collector` (back-end, Python) mirrors that schema via `news_collector/contracts/frontend_schema.py` (`AstroPost`).
- Field parity between the two representations is enforced in CI by `tests/test_contracts_sync.py`, which sparse-checkouts the front-end `config.ts` and compares field names against `AstroPost`.

Schema evolution follows a **version bump protocol**:

1. A field change is proposed in the back-end `AstroPost` model first, because the back-end is the publisher.
2. The corresponding change is made to `src/content/config.ts` in a coordinated PR.
3. Both PRs reference each other and are merged in the same release window.
4. The `schema_version` integer in both the Zod schema and `AstroPost` is bumped.
5. `test_contracts_sync.py` must pass on both sides before either PR merges.

For breaking field removals or renames, the `schema_version` bump is **mandatory**. Additive optional fields are permitted without a version bump, provided the front-end schema defaults are set to make old content continue to build.

---

## Rollback

If the two-repo split proves operationally burdensome:

1. The back-end can be re-merged into `noticiencias` as a `collector/` subdirectory.
2. `AstroPost` in `frontend_schema.py` becomes the single authoritative schema; `src/content/config.ts` is generated from it.
3. CI jobs are unified under a matrix strategy across Node and Python runtimes.

The rollback path is documented here but is not the current intent.

---

## Consequences

**Positive**:
- Clean runtime separation: front-end uses Node 22/24, back-end uses Python 3.13.
- Independent deploy cadence: the front-end can deploy without re-running collection CI.
- `test_contracts_sync.py` provides a hard CI gate preventing silent schema drift.
- Each repo has a focused AGENTS.md, making agent-assisted work unambiguous.

**Negative**:
- Schema changes require coordinated PRs across two repos.
- Local end-to-end development requires both repos to be checked out.
- The sparse-checkout step in `test_contracts_sync.py` depends on the front-end repo being public and accessible from CI.

---

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Monorepo with workspaces | Node/Python tooling conflict in CI; no mature Python + Astro monorepo template available |
| Schema generated from `config.ts` | Requires a TypeScript-to-Python code-gen step; adds tooling complexity with little gain |
| Schema generated from `AstroPost` | Inverts the rendering authority — the front-end should own its own Zod schema |
| Copy-paste with no sync test | Acceptable only if field drift risk is tolerated; rejected because drift has already caused production bugs |
