# ADR-0001: Adapter pattern as the only shape-conversion point

- **Date**: 2024-01-01
- **Status**: Accepted

## Context

Multiple layers of the pipeline (ingestion, scoring, publication, serving) need to
exchange data. Early versions of the collector had shape conversion scattered across
enrichment modules, scoring code, and publication helpers, causing the same field
mapping to be reimplemented in several places and making it hard to change the
external contract without a cross-repo grep.

## Decision

All shape conversion between external provider format and the internal domain model
must go through adapter functions in `news_collector/contracts/`. No other module
may perform field remapping, provider-specific key translation, or schema migration
directly.

Policy and scoring modules receive typed domain objects; they never inspect raw
provider payloads.

## Consequences

- A change to an upstream provider format has exactly one edit point.
- Scoring and editorial logic stay testable without live network access.
- The `contracts/` package becomes a dependency of almost every other package —
  it must stay lightweight (no I/O, no network imports).
- Reviewers reject shape conversion in scoring, enrichment, or publication modules
  (enforced by LAW-B2 in `docs/AGENTS.md`).

## Alternatives considered

| Option | Reason rejected |
|--------|-----------------|
| Inline mapping at each call site | Change surface proportional to number of consumers; already caused bugs |
| Separate DTOs per layer | Higher boilerplate; coupling risk moves to DTO-to-DTO converters |
| Pydantic validators doing conversion | Validation ≠ conversion; conflating them hides intent |
