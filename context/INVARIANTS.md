# INVARIANTS.md — Noticiencias Backend Architectural Invariants

## Authority Hierarchy

Authority order (highest to lowest):

1. SOURCE_OF_TRUTH.md
2. docs/AGENTS.md
3. Module invariants defined in context/modules/\*.md

SOURCE_OF_TRUTH.md is the absolute architectural authority.
If any invariant in lower-level documents contradicts SOURCE_OF_TRUTH.md,
SOURCE_OF_TRUTH.md MUST prevail without exception.

Lower authorities MUST NOT contradict higher authorities.

---

## Core System Invariants

### I-1: Data Contracts Are Mandatory

All system boundary crossings MUST use Pydantic models defined in:

news_collector/contracts/

Raw dictionaries MUST NOT cross system boundaries.

Derived from:

- SOURCE_OF_TRUTH.md
- docs/AGENTS.md LAW-1

---

### I-2: Adapters Are Exclusive Conversion Layer

Only news_collector/contracts/adapters.py may perform conversions between:

- ORM → contract
- external input → contract
- contract → storage/export

Derived from:

- SOURCE_OF_TRUTH.md
- docs/AGENTS.md LAW-2

---

### I-3: System Layer Is Orchestration-Only

Modules under news_collector/system/ MUST NOT:

- validate business payloads
- convert contracts
- embed scoring or editorial logic

Derived from:

- SOURCE_OF_TRUTH.md
- docs/AGENTS.md LAW-3

---

### I-4: Canonical Identity Is Immutable

Once assigned, the following MUST NEVER change:

- refinery_id
- canonical_slug
- artifact filename
- publication date

Derived from:

- SOURCE_OF_TRUTH.md
- docs/AGENTS.md LAW-4, LAW-5

---

### I-5: Database Is Canonical Identity Authority

storage/database.py is the persistence authority responsible for:

- canonical_slug persistence
- identity reuse
- canonical identity validation

Derived from:

- context/modules/storage_database.md

---

### I-6: Editorial Policy Enforcement Precedes Persistence

refinery_engine MUST enforce editorial policy prior to artifact creation or database persistence.

Derived from:

- context/modules/logic_workflows_refinery_engine.md

---

### I-7: Context Files Are Authoritative Prompt Context

Agents MUST use:

- context/MODULE_INDEX.md
- context/modules/\*.md
- context/INVARIANTS.md

instead of full source files unless explicitly required.

Agents MUST prefer context files over full source code to minimize token usage,
reduce hallucination risk, and preserve architectural invariants.

Derived from:

- context-engineering architecture

---

## Agent Operational Invariants

Agents MUST NOT:

- modify contract schemas without authorization
- modify adapters without boundary test validation
- modify canonical identity logic
- bypass editorial policy enforcement

Agents MUST:

- refuse tasks violating invariants
- escalate ambiguity instead of guessing

---

## Verification Commands

make test-contracts
make test-boundaries
make test-system
