# AGENTS.md — Noticiencias Backend (News Collector)

> **Audience:** AI Agents, Data Engineers, and Autonomous Refactoring Systems  
> **Authority:** This document is **binding**. It defines non‑negotiable architectural law for the backend.  
> **Hierarchy:** This document is **subservient only** to `SOURCE_OF_TRUTH.md`. If a conflict exists, `SOURCE_OF_TRUTH.md` prevails.

---

## 0) Architectural Status (As‑Built)

This backend has passed the following milestones and they are considered **closed and enforced**:

- **S1** — System Decomposition (Bootstrap / Pipeline / Observability)
- **S2** — Canonical Identity & URL Integrity
- **D1 Phase 1 & 2** — Data Contracts Definition and Boundary Adoption

Any change MUST preserve these invariants.

---

## 1) Core Architectural Laws

### LAW‑1: Data Contracts Are Mandatory

All data crossing **any system boundary** MUST be encapsulated in a Pydantic model defined in:

```
news_collector/contracts/
```

There are **no exceptions**.

Forbidden:

- Passing raw dictionaries across boundaries
- Creating ad‑hoc schemas inline
- Mutating payloads after validation

---

### LAW‑2: Adapters Are the Only Conversion Layer

All transformations from:

- ORM → Contract
- External input → Contract
- Contract → Legacy consumer

MUST occur **exclusively** inside:

```
news_collector/contracts/adapters.py
```

System code (`system/`) may **never** construct payloads manually.

---

### LAW‑3: System Layer Is Orchestration Only

The `news_collector/system/` package is restricted to:

- Dependency wiring
- Execution order
- Error routing
- Event emission

It MUST NOT:

- Validate raw data
- Shape payloads
- Embed business rules
- Perform serialization logic

---

### LAW‑4: Canonical Identity Is Immutable (S2)

Once an article is published:

- Its filename
- Its date
- Its URL
- Its `refinery_id`

are **permanent**.

Re‑processing MUST reuse the original artifact.  
Time‑based regeneration is forbidden.

---

## 2) Contract Boundaries (D1)

The following boundaries are **sealed**:

| Boundary   | Method                   | Contract                   |
| ---------- | ------------------------ | -------------------------- |
| Validation | `_execute_validation`    | `ArticleValidationPayload` |
| Scoring    | `_execute_scoring`       | `ScoringInputModel`        |
| Export     | `export_latest_articles` | `ExportContractV1`         |

Adapters MUST be used at all three.

---

## 3) Testing & Verification Law

### Contract Tests

```
make test-contracts
```

- Validates schema correctness
- Enforces coverage ≥ 80%
- Uses **typed mocks only**

### Boundary Tests

```
make test-boundaries
```

- Confirms contracts are used
- NO coverage requirement
- Behavioral assertions only

### System Tests

```
make test-system
```

- Guards S1 refactor
- Ensures orchestration stability

---

## 4) Agent Behavior Rules

Agents MUST:

- Read `SOURCE_OF_TRUTH.md` first
- Treat this document as law
- Refuse tasks that violate contracts
- Escalate ambiguity instead of guessing

Agents MUST NOT:

- “Make tests pass” by weakening contracts
- Silence validation errors
- Reintroduce dict‑based pipelines
- Mix observability with logic

---

## 5) Change Governance Matrix

| Change Type                             | Allowed Autonomously   |
| --------------------------------------- | ---------------------- |
| Contract Addition (Backward Compatible) | ⚠️ With Tests          |
| Contract Modification                   | ❌ Human Review        |
| Adapter Refactor                        | ⚠️ With Boundary Tests |
| System Refactor                         | ❌ Must preserve S1    |
| Scoring Logic                           | ❌ Human Approval      |
| Validation Rules                        | ❌ Human Approval      |

---

## 6) Future Work (Explicitly Out of Scope)

- D1 Phase 3 (Model‑native components)
- D2 Runtime Contract Telemetry
- Breaking schema migrations

These REQUIRE explicit user authorization.

---

### LAW‑5: Canonical URLs Are Deterministic & Immutable

The canonical URL (slug) of an article:

- MUST be deterministic (derived from source date + title)
- MUST NOT depend on processing time (`now()`)
- MUST be persisted in the DB (`canonical_slug`) on first creation
- MUST be re-used from DB on all subsequent updates

Processing an article 100 times must result in the **exact same URL** 100 times.

---

**End of AGENTS.md — Backend Law**
