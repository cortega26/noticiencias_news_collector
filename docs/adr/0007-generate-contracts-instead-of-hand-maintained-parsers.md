# ADR-0007: Generate Contracts Instead of Hand-Maintained Parsers

**Date**: 2026-08-22
**Status**: Proposed
**Deciders**: Engineering team

---

## Context

Two hand-maintained contract mirrors currently sit between the backend and
its consumers, and both are measured drift-detection gaps (plan 060's
evidence baseline, "Contract parser" and "Admin types" rows):

1. Frontend `scripts/check-contract-sync.js` is a 1,488-line regex parser
   that reads both the Python `AstroPost` model and the TypeScript
   `content.config.ts` Zod schema and compares field names by pattern
   matching source text. It has no access to real type information from
   either language and can silently miss shape mismatches that don't happen
   to trip its regexes.
2. Frontend `apps/admin/src/lib/types.ts` is a handwritten TypeScript mirror
   of the backend admin HTTP API (`news_collector/serving/api.py`), with
   `apps/admin/src/lib/api.ts` casting response JSON into those handwritten
   types at runtime with no verification that the cast is accurate.

Both are drift risks by construction: nothing forces the hand-maintained
side to change when the source of truth changes, and the regex parser is
itself a maintenance burden independent of what it's checking.

---

## Decision

Adopt native, documented schema-generation tooling instead of continuing to
extend the custom regex parser or the handwritten type mirror:

- For the admin HTTP contract: FastAPI's `app.openapi()` /
  Pydantic's `BaseModel.model_json_schema()` produce the authoritative
  OpenAPI document directly from the backend's actual route and model
  definitions. This document drives TypeScript client generation via
  `openapi-typescript`, consumed through a typed `openapi-fetch` client —
  replacing the handwritten `apps/admin/src/lib/types.ts` mirror and the
  unverified casts in `api.ts`.
- For the publication schema: the frontend's Zod schema
  (`src/content.config.ts`) remains the structural authority (per ADR-0003,
  frontend Zod is publication-input authority). Zod 4's `z.toJSONSchema()`
  generates a neutral JSON Schema from it, which is compared against the
  backend Pydantic `AstroPost` model's own JSON Schema output on a shared
  valid/invalid fixture corpus (built by the frontend half of this phase, at
  `tests/fixtures/publication-contract-corpus/` in the frontend repo). This
  replaces `check-contract-sync.js`'s regex-based field comparison with a
  structural, generated comparison.

Reference implementations (link these, do not invent alternates):

- FastAPI OpenAPI generation and `app.openapi()`:
  https://fastapi.tiangolo.com/how-to/extending-openapi/
- Pydantic `BaseModel.model_json_schema()`:
  https://docs.pydantic.dev/latest/concepts/json_schema/
- Astro content collection schema behavior:
  https://docs.astro.build/en/reference/modules/astro-content/
- Zod 4 JSON Schema conversion: https://zod.dev/json-schema
- `openapi-typescript` CLI: https://openapi-ts.dev/cli
- typed `openapi-fetch` client: https://openapi-ts.dev/openapi-fetch/

This ADR records the target state. Phase 6 of the master plan
(`plans/060/spec.md`, "Phase 6: Generate admin and publication contracts")
implements it. The regex parser (`check-contract-sync.js`) is retired only
after one full release window of proven parity between the generated
comparison and the existing check — this ADR does not authorize immediate
removal of the existing gate.

---

## Consequences

**Positive**:
- The admin HTTP contract and its TypeScript client become generated from
  the actual backend route/model definitions — a route or field change is
  automatically reflected, eliminating an entire class of silent drift.
- The publication schema comparison becomes structural (real JSON Schema
  diffing on a fixture corpus) instead of regex text matching, catching
  shape mismatches the current parser cannot see.
- Removes the 1,488-line regex parser's ongoing maintenance burden once the
  generated comparison has proven parity.

**Negative**:
- Introduces new build-time dependencies (`openapi-typescript`,
  `openapi-fetch`, Zod 4's `toJSONSchema`) that must be kept current.
- The parallel-run window (regex parser plus generated comparison) is
  temporary extra CI cost and requires the fixture corpus to stay
  representative of real drift cases.
- Generated TypeScript types from OpenAPI can be less ergonomic than
  handwritten types for admin-GUI-specific usage patterns; call sites may
  need adaptation.

---

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Keep the hand-maintained mirror/parser | Rejected — proven drift risk; that risk is the reason this ADR exists |
| Generate the frontend Zod schema from the backend Pydantic model | Rejected — inverts the ownership rule already established in ADR-0003: frontend Zod is publication-input authority, not a derived artifact |
| Generate the backend Pydantic model from the frontend Zod schema | Rejected — inverts the same rule from the other direction; this ADR does not change ADR-0003, it implements its next step |
