# AGENTS.md --- Noticiencias Backend (News Collector)

Version: 2.3 (Tightened Exceptions, Canonical ID Protection, Doc Roles)
Status: Active & Binding Supersedes: Version 2.2

---

## Authority & Governance

Hierarchy of authority:

1.  SOURCE_OF_TRUTH.md
2.  This AGENTS.md
3.  ARCHITECTURE.md
4.  RUNBOOK.md
5.  Inline documentation

This document may evolve only through the Architectural Amendment
Procedure (Section 12).

---

# 0) Architectural Intent

The backend is designed to be:

- Deterministic in identity
- Contract-driven across boundaries
- Resistant to silent regression
- Safe for autonomous refactoring
- Evolvable without structural decay

---

# 1) Structure of Power (Visual)

This diagram is a **governance model**, not a runtime dependency graph.

```mermaid
flowchart TB
  SOT[SOURCE_OF_TRUTH.md\n(Constitution)] --> AG[AGENTS.md\n(Backend Law)]
  AG --> AR[ARCHITECTURE.md\n(Implementation Model)]
  AR --> RB[RUNBOOK.md\n(Ops Procedures)]
  RB --> CODE[Code / Tests / CI\n(Executable Evidence)]
  AG --> CODE
```

Rule: If a lower-authority document conflicts with a higher-authority
one, the higher authority prevails.

---

# 2) Architectural Status

Enforced milestones:

- S1 --- System Decomposition
- S2 --- Canonical Identity & URL Determinism
- D1 Phase 1 & 2 --- Contract Boundaries

All associated invariants are active.

---

# 3) Core Architectural Laws

## LAW-1: Contract-Driven Boundaries (Critical)

All cross-boundary data MUST use Pydantic models under:

    news_collector/contracts/

Forbidden:

- Raw dict propagation across boundaries
- Inline schema definitions
- Post-validation mutation
- Implicit structural assumptions

---

## LAW-2: Adapters Layer Exclusivity (Critical)

All structural transformations MUST occur in the **Adapters Layer**.

Allowed structure:

    news_collector/contracts/adapters/
        __init__.py          # Expose stable public adapter API
        validation.py
        scoring.py
        export.py
        ...

A single adapters.py file is permitted only if size remains
maintainable.

System and domain layers MUST NOT construct cross-boundary payloads
manually.

**Adapter Rule:** Adapters may transform shape and types, but MUST NOT
implement business rules. Business rules belong in domain/components.

---

## LAW-3: System Layer Is Pure Orchestration (Structural)

`news_collector/system/` may:

- Wire dependencies
- Control execution flow
- Emit semantic events
- Route errors

It MUST NOT:

- Apply domain logic
- Shape contract payloads
- Serialize artifacts
- Embed scoring logic
- Implement validation rules

---

## LAW-4: Canonical Identity Determinism (Critical)

Canonical identity includes:

- Slug
- Publication date
- Canonical URL
- refinery_id
- Filename

Rules:

- Derived deterministically
- Persisted on first publication
- Reused on update
- Independent of runtime time
- Independent of execution order

Forbidden in identity path:

- `datetime.now()`
- Randomness
- Execution-order-dependent mutations

### LAW-4A: Canonical ID Generation Is Protected (Critical)

If `refinery_id` is generated algorithmically (hash/derivation), then:

- The generation algorithm MUST be treated as part of canonical
  identity.
- Changes to the algorithm MUST NOT retroactively change existing
  `refinery_id` values.
- If a new algorithm is introduced, it MUST be versioned explicitly
  (e.g., `refinery_id_v2`) and the system MUST:
  - Preserve old IDs for existing artifacts
  - Use the versioned ID deterministically for new artifacts
- Any migration or rewrite of canonical IDs requires explicit human
  approval and must include a compatibility plan.

---

## LAW-5: Domain Purity & Dependency Direction (Structural)

The domain is the system's semantic core. It must be stable, testable,
and transport-agnostic.

**Dependency direction is inward**:

- `system/` depends on domain
- `contracts/` depends on domain (via adapters)
- domain depends on neither `system/` nor `contracts/`

Therefore domain/components MUST NOT import:

- `news_collector.system.*`
- `news_collector.contracts.*`

### Allowed exceptions (must be explicit and documented)

Only the following are permitted, and only if they keep the domain
**pure**:

1.  **Pure utilities**:
    - Must be **purely functional** (same input → same output)
    - Must have **zero side-effects**
    - Forbidden inside utilities:
      - File I/O, network I/O, database access
      - Reading environment variables
      - Logging/metrics emission
      - Time access (`now()`, timestamps) unless passed in as an
        argument
      - Randomness unless passed in as an argument
    - Recommended location: `news_collector/domain/utils_pure/` (or
      equivalent)
2.  **Ports/interfaces defined in domain** (preferred):
    - Domain defines an interface; outer layers implement it.

Any exception must include a short "Why this stays pure" note in code
comments.

**Domain Rule:** Domain code must be runnable and unit-testable without
database, network, or LLM dependencies.

---

# 4) Invariant Classification

Critical Invariants: - Contract boundaries - Canonical identity
determinism (including canonical ID generation protection) - Adapters
exclusivity

Structural Invariants: - Orchestration purity - Observability
separation - Domain purity (dependency direction inward)

Policy Invariants: - Coverage preservation - CI enforcement

Critical invariants cannot be modified autonomously.

---

# 5) Transitional / Legacy Policy

Some modules may predate Version 2.x compliance.

Rules:

1.  Transitional modules must be explicitly marked.
2.  Any modification to a transitional module MUST upgrade it to current
    laws.
3.  No new non-compliant surface area may be introduced.
4.  Transitional status cannot expand; it can only shrink.

---

# 6) Testing as Architectural Evidence

Tests encode invariants.

Agents MUST add tests when:

- Introducing a new Contract
- Modifying Adapter mappings
- Changing boundary method signature
- Fixing a bug (regression test required)
- Modifying identity path logic
- Introducing or altering domain rules
- Touching canonical ID generation logic (LAW-4A)

---

## 6.1 Coverage Policy

Coverage must not decrease for invariant-protecting paths.

Structural coverage \> Numeric coverage.

---

# 7) Minimum Enforcement Set (Mandatory After Audit)

The following MUST exist in CI:

1.  Boundary Test:
    - Fails if dict crosses a sealed boundary.
2.  Identity Determinism Test:
    - Same input processed multiple times → identical canonical
      identity.
3.  Canonical ID Protection Test:
    - Existing artifacts retain their `refinery_id` values across
      reprocessing and code changes.
4.  System Purity Test:
    - System layer does not perform payload shaping or validation.
5.  Adapter Mapping Tests:
    - Validate schema integrity and transformation correctness.
6.  Import Guard Test (Domain Purity):
    - Fails if domain/components imports `system/` or `contracts/`.

Without these, architectural law is considered partially unenforced.

---

# 8) Change Governance Matrix

Change Type Autonomous Allowed

---

Contract Addition (Backward Compatible) ⚠️ With Tests
Contract Modification ❌ Human Review
Adapter Refactor ⚠️ Boundary Tests
System Refactor ❌ Preserve S1
Domain Rule Changes ⚠️ Must add tests
Canonical ID Generation Logic ❌ Human Approval
Scoring Logic ❌ Human Approval
Validation Rules ❌ Human Approval
Test Addition ✅ Required
Contract Test Modification ❌ Human Review
Test Deletion ❌ Human Review

---

# 9) Autonomous Agent Enforcement

## LAW-6: Refusal Obligation

Agents MUST refuse if task:

- Breaks critical invariants
- Weakens validation
- Introduces dict boundary crossing
- Reduces invariant coverage
- Introduces identity nondeterminism
- Violates domain purity dependency rules
- Changes canonical ID generation without approval (LAW-4A)

Refusal must state: - Violated law - Explanation - Compliant alternative

---

## LAW-7: No Speculative Refactoring

No architecture collapse without explicit scope.

Optimization must preserve invariants.

---

## LAW-8: Escalation Over Assumption

Ambiguity in architectural decisions requires halt and clarification.

---

# 10) Document Roles (Non-Overlapping Responsibilities)

To prevent duplication and drift:

- **SOURCE_OF_TRUTH.md**: Mission, principles, ecosystem-level
  guarantees.
- **AGENTS.md**: What is **mandatory/forbidden**, enforcement
  obligations, refusal rules.
- **ARCHITECTURE.md**: The **how** --- diagrams, flows, implementation
  model mapping laws to code.
- **RUNBOOK.md**: Operational procedures --- run/debug/fix, incident
  handling.

AGENTS.md should remain compact and normative. ARCHITECTURE.md should
carry explanatory depth.

---

# 11) Out of Scope

- Breaking schema migrations
- Removing determinism guarantees
- Collapsing boundary layers
- Replacing contracts with primitives
- Weakening domain purity dependency direction
- Retroactive canonical ID rewrites

Require explicit approval.

---

# 12) Architectural Amendment Procedure

Amendment requires:

1.  Written proposal
2.  Impact analysis
3.  Invariant classification impact
4.  Human approval
5.  Version increment
6.  Changelog update

---

End of AGENTS.md ---
