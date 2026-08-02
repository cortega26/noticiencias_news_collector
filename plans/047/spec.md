# Plan 047: Spike the reader correction loop — spec

## Outcome: DONE (spike)

Decision-only spike: a documentation analysis plus a synthetic contract
prototype. No production endpoint, queue, content, or real reporter
record was changed. The spike's recommendation (INTEGRATE, not build
from scratch) is backed by concrete owner/workflow analysis, a versioned
lifecycle contract, a privacy/abuse threat table, and a dependency-based
review date.

## What was in scope for this pass

Per the plan's Steps 1-3 and 6 (ownership, lifecycle contract,
privacy/abuse, build/no-build decision) — everything a spike can prove
without touching production:

1. **Step 1 (owner/current workflow)** — done: documented in
   `docs/spikes/reader-correction-loop.md` § "Owner and current workflow".
2. **Step 2 (lifecycle contract)** — done: `ReportEnvelope v1` documented
   in the same file, § "Lifecycle contract".
3. **Step 3 (privacy/abuse analysis)** — done: 9-threat table with
   mitigations, § "Privacy and abuse analysis".
4. **Step 6 (build/no-build decision)** — done: INTEGRATE recommendation
   with rationale, dependencies, effort estimate, and review date,
   § "Build/no-build decision".
5. **Contract prototype** — `tests/spikes/test_reader_correction_contract.py`
   (15 synthetic tests, all passing — count verified by running pytest,
   not assumed from the ledger).

## Goals actually achieved

1. **`docs/spikes/reader-correction-loop.md`** (107 lines) contains all
   four claimed sections:
   - **Ownership**: triage owner is the Operator (editorial team); intake
     path is `ReportForm.astro` → Worker `workers/src/handlers/report.ts`
     → optional R2/email (plan 023); current workflow is manual; 4 top
     failure modes and unanswered questions listed; volume explicitly
     flagged as unmeasured (endpoint production-disabled pending plan 023).
   - **Lifecycle contract `ReportEnvelope v1`**: `report_id` (opaque
     UUID), `public_url`, `refinery_id` (resolved from backend, not
     trusted from user), `content_revision`, `type` (5 values), bounded
     `description`, `evidence_refs` (never fetched), separated
     `consent`/`contact`, `idempotency_key = sha256(url:type:content_revision)`,
     append-only `events`, and an **8-state machine** (verified by
     counting the distinct states in the document): `received`, `triaged`,
     `duplicate`, `rejected`, `accepted`, `correction_proposed`,
     `correction_published`, `closed` — 7 allowed transitions and 3
     terminal states (duplicate, rejected, closed). (The ledger's
     "7-state machine" is inaccurate; the document defines 8 states.)
   - **Privacy/abuse**: exactly 9 threat rows, each with a concrete
     mitigation (spam/flooding → idempotency key + rate limit; forged
     identity → backend-resolved `refinery_id`; PII → contact deleted on
     closure; queue enumeration → opaque UUIDs; etc.) plus a
     data-minimization paragraph.
   - **Decision**: INTEGRATE — justified by existing building blocks
     (Worker handler, `PublicationIdentityResolver`, plan 021 callback),
     explicit rejection of a first-party queue as over-engineering for
     unmeasured volume, dependencies (plan 023 before production intake;
     plan 021 callback wiring), a 3-5 day effort estimate, and a concrete
     review date. Not vague or generic.
2. **`tests/spikes/test_reader_correction_contract.py`** — 15 tests,
   substantive, not trivial:
   - lifecycle happy path (5 transitions, event log length asserted);
   - invalid transitions rejected (`skip triage`, `close before
     published`, transitions out of terminal states);
   - terminal states (duplicate, rejected, closed) enforced;
   - idempotency key equality across same report and inequality across
     different URL/type;
   - privacy: `contact` deleted on closure, no contact leak into events;
   - identity resolution (refinery_id present/absent cases).
   Run: `.venv/bin/python -m pytest tests/spikes/test_reader_correction_contract.py -v`
   → **15 passed**.

## What was NOT touched

- No production endpoint, queue, content, or reporter record changed:
  `git show --stat 35dd467` (the spike's own commit) touches exactly two
  files — `docs/spikes/reader-correction-loop.md` and
  `tests/spikes/test_reader_correction_contract.py`.
- Later edge-case hardening in `e73377f` extended the spike test file
  (+4 tests) alongside plan 017's unrelated UI-slice changes; it added no
  production code for this spike.
- The report intake endpoint remains production-disabled (plan 023
  PARTIAL) — this spike changed no wiring.

## Verification

- [x] `docs/spikes/reader-correction-loop.md` read end-to-end: all 4
      claimed sections present and substantive.
- [x] `pytest tests/spikes/test_reader_correction_contract.py -v` →
      15 passed (counted from test output, not the ledger).
- [x] 8 distinct states counted directly from the document's transition
      diagram (the ledger's "7-state" figure is corrected to 8 in
      `plans/README.md`).
- [x] `git show --stat 35dd467` confirms docs+tests only — no production
      code in the spike commit.
