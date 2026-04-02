# AGENTS.md — Noticiencias Backend (News Collector)

Status: Active and binding
Authority: Subordinate to `docs/SOURCE_OF_TRUTH.md`; authoritative over lower-level backend docs
Scope: `/home/carlos/VS_Code_Projects/noticiencias/noticiencias_news_collector`

This file defines reviewable engineering law for the backend. It exists to keep the codebase operable as the ingestion pipeline, Refinery workflows, contracts, storage, and publishing logic grow. It is intentionally specific. Rules that cannot be checked in code review do not belong here.

## 0) Mandatory Preflight

Before changing code:

1. Read this file fully.
2. Inspect the package boundaries touched by the change.
3. Classify the change using the matrix in Section 10.
4. Run the required validation for that class of change.

Do not ship "temporary compatibility", "quick manager", or "generic helper" layers. If a change cannot be explained in terms of the package responsibilities below, the design is not finished.

## 1) Actual System Shape

The backend is not a generic framework. It is a Python pipeline with clear responsibilities:

- `news_collector/contracts/`: sealed external and cross-boundary data shapes; adapters live here.
- `news_collector/system/`: orchestration, bootstrap, reporting, observability wiring.
- `news_collector/collectors/`: ingestion from feeds and source endpoints.
- `news_collector/enrichment/` and `news_collector/infrastructure/`: external I/O, enrichment strategies, HTTP clients, LLM/provider integrations, proxy/runtime concerns.
- `news_collector/storage/`: database engines, sessions, ORM models, persistence, and DB analytics.
- `news_collector/validation/`, `news_collector/scoring/`, `news_collector/taxonomy/`, `news_collector/editorial/`: decision rules and editorial heuristics.
- `news_collector/logic/workflows/` and `apps/refinery/`: Refinery-specific application flows and UI integration.
- `news_collector/serving/`: HTTP API surface.
- `tests/`: architectural proof, regression, property, integration, and security checks.

Governance must match this structure. Do not invent a cleaner architecture in documents while coding against a different one.

## 2) Architectural Laws

### LAW-B1: Boundaries must be typed

Rules:

- External boundaries and sealed internal boundaries must use explicit types.
- Use Pydantic models in `news_collector/contracts/` for API payloads, publication payloads, persisted article exchange, and other cross-subsystem contracts.
- New or modified public functions must not introduce fresh `dict[str, Any]` payloads as their primary boundary type when a contract or typed model is appropriate.
- Local parsing helpers may use raw dicts temporarily, but raw dicts must not leak across package boundaries once normalization is complete.

Review trigger:

- Any new ingress or egress shape needs either a contract, a typed dataclass/TypedDict with clear scope, or a strong reason why it remains local-only.

### LAW-B2: Adapters are the only shape-conversion choke point

Rules:

- Structural mapping between ORM models, raw source payloads, frontend publication payloads, and contracts belongs in `news_collector/contracts/adapters.py` or a clearly named adapter module under `contracts/`.
- Business rules do not belong in adapters.
- Validation may happen in adapters; editorial judgment, scoring heuristics, and persistence policy may not.
- Do not duplicate field-mapping logic in `system/`, `serving/`, `apps/refinery/`, or tests.

Reject in review:

- Hand-built export dicts in workflow code.
- Repeating `source_id`, metadata, or publication-field normalization outside adapter code.

### LAW-B3: Orchestration and decision logic must stay separate

Rules:

- `news_collector/system/` and `news_collector/logic/workflows/` coordinate steps, retries, batching, and dependency wiring.
- Scoring thresholds, editorial policy, taxonomy rules, validation heuristics, and source-specific content judgments belong in dedicated policy modules, not orchestration code.
- If a function both decides what is valid and performs I/O, split it into a pure decision path plus a thin I/O wrapper.
- `system/` may call collaborators; it must not become the place where rules are authored.

Legacy note:

- Existing internal-method coupling in `system/` is compatibility debt. Do not spread that pattern into new modules.

### LAW-B4: I/O must stay at the edges

Rules:

- Network calls belong in `collectors/`, `enrichment/`, `infrastructure/`, and the HTTP serving layer.
- Database engine/session lifecycle and write operations belong in `storage/`.
- File publication and artifact generation belong in explicit workflow/publisher paths, not in utility modules.
- Pure rule code in `validation/`, `scoring/`, `taxonomy/`, and `editorial/` must be runnable without network, database, or environment access.
- Environment-variable lookups must happen at configuration/bootstrap boundaries, not deep inside core logic.

Allowed exception:

- `serving/` may perform read-only query composition against storage models because it is an edge adapter. Do not add write workflows there.

### LAW-B5: Canonical publication identity is deterministic and idempotent

Rules:

- `refinery_id`, slug, filename, canonical URL, and publication date are identity-bearing fields.
- Identity-bearing fields must come from persisted state or deterministic derivation from approved inputs.
- Runtime time, randomness, request order, and batch order must not change canonical publication outputs.
- Retrying the same publication workflow must not create a new canonical identity for the same article.
- If identity logic changes, the migration and compatibility plan must be explicit before code lands.

Allowed non-determinism:

- Trace IDs
- session IDs
- metrics timestamps
- logs

Not allowed in publication identity paths.

### LAW-B6: Batch workflows must fail explicitly, not mysteriously

Rules:

- Batch code must return or log per-item outcomes for success, skip, and failure cases.
- Continue-on-error behavior is allowed only when the result reports which items failed and why.
- Silent item drops are forbidden.
- Retries must be bounded and reserved for I/O failures, not validation bugs or deterministic logic errors.
- Idempotent write paths must tolerate reprocessing without creating duplicate persistent state.

### LAW-B7: Error handling must preserve signal

Rules:

- Boundary validation failures must raise explicit errors or return structured validation results.
- `except Exception` is allowed only when the exception is logged with context and then re-raised or converted into a typed result.
- Never use broad catches to hide partial corruption, skip tests, or make a pipeline "look successful".
- Returning `None` as a failure sentinel is allowed only when the caller can distinguish it unambiguously and the contract documents it.

Reject in review:

- `except Exception: pass`
- hidden fallback behavior that changes publication or scoring semantics
- retries wrapped around code that is not I/O

### LAW-B8: Utility sprawl is forbidden

Rules:

- `news_collector/utils/` is for narrow helpers with one stable responsibility.
- A helper that knows about SQLAlchemy models, article workflow policy, HTTP transport, or UI state does not belong in `utils/`.
- If a helper has one consumer, keep it local until reuse is real.
- Do not create "common", "base", or "helpers" modules that mix unrelated concerns.
- Prefer a small amount of duplication over a premature generic abstraction.

### LAW-B9: New abstraction layers require proof

Rules:

- Do not add a new package, base class, service, manager, or factory unless the change clearly owns one of these concerns:
  - lifecycle/composition
  - transport indirection
  - retry/backoff policy
  - caching
  - batch coordination
  - plugin-style replacement already needed by more than one concrete implementation
- "We may need this later" is not a valid reason.
- Inheritance is discouraged for business logic. Prefer composition and explicit collaborators.
- A new abstraction must reduce duplicated branching across at least two concrete call sites or replace a currently unstable boundary.

### LAW-B10: Performance-sensitive paths need deliberate review

Rules:

- The following areas are performance-sensitive and should be reviewed for repeated work and unbounded growth:
  - collector loops
  - enrichment fan-out
  - DB save/update batches
  - ranking queries
  - API pagination
  - publication/export generation
- Avoid repeated model validation, repeated JSON parsing, repeated DB round-trips, and N+1 query patterns inside loops.
- Pagination and sorted API results must remain deterministic.
- Memory growth in batch paths must be bounded; stream or chunk when practical.

## 3) Package Boundary Rules

### 3.1 `contracts/`

Must:

- define and validate boundary shapes
- host adapter functions for shape conversion

Must not:

- perform network I/O
- open DB sessions
- import orchestration modules
- bury business heuristics in field mapping

### 3.2 `system/`

Must:

- bootstrap collaborators
- coordinate pipeline stages
- emit observability and reporting events

Must not:

- define new schema objects that duplicate `contracts/`
- implement source-specific parsing
- own SQLAlchemy models or raw SQL
- author editorial/scoring policy

### 3.3 `storage/`

Must:

- own engine/session creation
- own ORM models and persistence behavior
- centralize DB writes and DB-specific optimizations

Must not:

- perform network calls
- absorb editorial policy because "the data is already here"

### 3.4 `collectors/`, `enrichment/`, `infrastructure/`

Must:

- isolate transport, scraping, HTTP, provider, and runtime integration concerns

Must not:

- decide final publication identity
- encode editorial publishing policy
- duplicate contract adapters

### 3.5 `logic/workflows/` and `apps/refinery/`

Must:

- compose workflows around contracts, policy modules, and persistence boundaries

Must not:

- become a second home for ad hoc schema definitions
- bypass contracts because the UI "already knows the shape"

### 3.6 `serving/`

Must:

- expose a stable read-oriented HTTP interface
- validate inputs explicitly
- paginate deterministically

Must not:

- mutate editorial state through convenience endpoints
- replicate workflow logic already present elsewhere

## 4) Testing Is Architectural Evidence

Tests are mandatory when a change touches behavior, not just when it feels risky.

Add or update tests when:

- changing a contract, adapter, or boundary signature
- changing source identity handling
- touching canonical publication logic
- changing batch behavior or retry behavior
- fixing a bug
- changing serving pagination/filter semantics
- moving logic across package boundaries

Prefer the narrowest test that proves the invariant:

- contract tests for shape
- unit tests for pure rules
- boundary tests for orchestration
- integration tests for storage and workflow coupling

## 5) Operational Validation

Baseline commands for meaningful code changes:

```bash
make lint
make type
make test
```

Add the relevant targeted gates:

- Contract or adapter changes:

```bash
make test-contracts
```

- Orchestration or workflow boundary changes:

```bash
make test-boundaries
```

- Publication/refinery output changes:

```bash
make quality-gate
```

- Config schema/doc generation changes:

```bash
make config-docs-check
```

- Dependency, security, or CI-hardening changes:

```bash
make quality
```

Run only the commands relevant to the change, but do not under-run the gate. If the touched code affects multiple areas, run the union of their checks.

## 6) Anti-Patterns Blocked in Review

Reject these changes unless the diff includes a concrete justification:

- New `manager`, `service`, or `factory` classes with no clear lifecycle or composition responsibility.
- New cross-package dict payloads instead of typed boundaries.
- Business logic added to `system/` because it was "already coordinating things".
- Database writes from serving or utility code.
- Transport/retry/env logic hidden inside rule modules.
- One-off helpers moved to `utils/` for discoverability.
- Generic plugin frameworks created before there are real plugins.
- "Fail open" behavior that silently changes publication or scoring semantics.
- New `asyncio.run(...)` calls below CLI or sync-compatibility boundaries.

## 7) Refactor Triggers

A refactor is required when:

- the same mapping logic appears in two modules
- the same decision rule appears in workflow code and a policy module
- a function needs both network and editorial reasoning to complete
- a helper name becomes too generic to reveal its real dependency surface
- batch behavior depends on hidden mutable module state
- tests have to mock half the system just to verify one rule

## 8) Decision Heuristics

Use these review heuristics consistently:

- Prefer explicit collaborators over hidden globals.
- Prefer a small amount of local duplication over a premature shared framework.
- Prefer pure functions for policy and heuristics.
- Prefer narrow adapters over "smart" models that know every layer.
- Prefer bounded workflow steps over giant orchestrators with many optional branches.
- Prefer deleting dead code paths over preserving them behind flags forever.

## 9) Review Checklist

Before considering a backend change complete, verify:

- Boundary types remain explicit.
- Adapters are still the only place where shape conversion happens.
- I/O stayed at the edge packages.
- Publication identity is still deterministic.
- Batch failure behavior is explicit.
- No new abstraction was added without concrete justification.
- Tests cover the changed invariant.
- The required validation commands for the change class were run.

## 10) Change Matrix

| Change type | Risk | Minimum requirement |
| --- | --- | --- |
| Documentation or comments only | Low | No code validation beyond sanity check |
| Pure rule change in validation/scoring/editorial/taxonomy | Medium | `make lint && make type && make test` |
| Contract/adapter/boundary change | High | Baseline + `make test-contracts` |
| Orchestration, workflow, collector, storage, or serving change | High | Baseline + `make test-boundaries` and relevant targeted tests |
| Publication identity, refinery publishing, config schema, dependency, or security change | Critical | Baseline + targeted gates + `make quality` where applicable |

When unsure, classify the change at the higher risk level.

## 11) Final Authority

This file is the backend review standard.

- Code that violates these boundaries is not complete.
- Simplicity is preferred, but not at the cost of hidden coupling.
- Growth is allowed only when the dependency surface stays legible and testable.
