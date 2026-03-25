# Remediation Plan — 2026-Q1

**Date**: 2026-03-25
**Scope**: Findings F-0012 through F-0029

---

## Focus

The audit found that the system has solid architectural concepts (Pydantic contracts, multi-layer dedup, circuit breakers, editorial policy) but the **publication chain lacks transactional atomicity**: between file write, git push, PR creation, and DB mark there are 4 irreversible operations with no recovery mechanism. This is the primary corruption vector.

The secondary focus is the **Streamlit UI as an error amplifier**: missing guards against double execution turn an accidental click into duplicate PRs, re-publications, or incoherent state.

The third focus is an **active XSS vulnerability** in the frontend search page — a low-effort fix for a real security issue.

## Prioritization criteria

1. State corruption risk
2. Broken atomicity
3. Non-idempotency
4. Security vulnerabilities
5. Lost traceability
6. Editorial/publication duplication
7. Test gaps in critical paths
8. Structural debt
9. Secondary improvements

## Strategy

**Surgical first, structural second.** Each fix must be a small, verifiable, independent PR. Close corruption vectors with minimal changes first. Harden invariants with tests second. Improve observability last.

---

## Horizons

### Horizon A — Immediate fixes (1-2 weeks)

**Goal**: Eliminate active corruption, security, and duplication vectors.

**Findings covered**: F-0014 (XSS), F-0013 (double-click), F-0016 (PR 422), F-0023 (return value), F-0028 (re-publish), F-0022 (dispatcher), F-0026 (suppress).

**Why this horizon**: Low-effort (S/M) changes that close critical/high risks without architectural change. Each is an independent PR.

**Implementation risk**: Minimal. All are additive or local substitutions.

**Expected result**: System stops producing duplicate PRs from double-click, stops ignoring existing PRs, closes XSS, gains visibility into failed collectors.

### Horizon B — Structural hardening (3-6 weeks)

**Goal**: Make the publication chain recoverable from partial failures; close dedup gaps.

**Findings covered**: F-0012 (atomicity), F-0015 (git rollback), F-0018 (slug order), F-0019 (content hash), F-0021 (slug collision), F-0025 (manifest), F-0024 (TOCTOU), F-0029 (reset tx), F-0017 (JSON stale).

**Why this horizon**: Requires coordinated changes (publishing state in DB, operation reordering in refinery_engine, dedup logic change). Each needs integration tests.

**Implementation risk**: Medium. The operation reordering in process_single_article must preserve the happy path. The `publishing` state requires DB migration.

**Expected result**: A failure mid-publication leaves detectable, recoverable state. Dedup covers cross-source syndication. Frontend detects slug collisions at build time.

### Horizon C — Operational maturity (6-10 weeks)

**Goal**: Test hardening, coverage expansion, observability.

**Findings covered**: F-0020 (test coverage), F-0027 (velocity mode).

**Why this horizon**: Depends on Horizon B being implemented (atomicity tests need the `publishing` state). Observability changes don't reduce direct risk but make the system operable.

**Implementation risk**: Low. Tests and logging changes with no business logic modifications.

**Expected result**: Regressions in publication, dedup, and idempotency caught automatically.

---

## Recommended execution sequence

### Wave 1 — Independent PRs (parallel)

| PR | Items | Rationale |
|----|-------|-----------|
| PR-1 | A-01 (XSS fix) | Active security vuln. Frontend-only. |
| PR-2 | A-02 (double-click guard) | Streamlit-only. No publication logic change. |
| PR-3 | A-03 (check published before publish) | Streamlit-only. Additive guard. |
| PR-4 | A-05 + A-06 (log fixes) | Both are observability in same layer. Combinable. |
| PR-5 | B-02 (move slug persist after policy) | Single-method reorder. Small PR. |
| PR-6 | B-04 (slug uniqueness frontend) | Frontend-only. |

### Wave 2 — Sequenced

| PR | Items | Dependency |
|----|-------|------------|
| PR-7 | A-04 (PR 422 detection) | None, but better with PR-4 merged (logging) |
| PR-8 | B-03 (content hash dedup) | None. Merge before C-02. |
| PR-9 | B-05 + B-06 + B-07 (manifest, reset tx, JSON timestamp) | None. Three small hardening fixes. |

### Wave 3 — Main structural change

| PR | Items | Dependency |
|----|-------|------------|
| PR-10 | B-01 (publishing state + recovery) | PR-7 (A-04) merged. |

### Wave 4 — Validation

| PR | Items | Dependency |
|----|-------|------------|
| PR-11 | C-02 (E2E idempotency test) | PR-8 (B-03) merged. |
| PR-12 | C-01 (coverage expansion) | PR-10 (B-01) merged. |
| PR-13 | C-03 (velocity threshold) | None. |

### What NOT to mix in the same PR

- A-01 (XSS) with any backend change. Frontend-only; mixing complicates review and rollback.
- B-01 (publishing state) with B-02 or B-03. B-01 is the largest change; if it fails, must not drag other fixes.
- Tests (C-01, C-02) with code fixes. Tests should validate already-merged code.

---

## Implementation risks

### R1: Guards block legitimate operations
The double-click guard (A-02) and publish-check (A-03) could block legitimate re-processing if session_state gets stuck or if an article needs correction after publication.
**Mitigation**: session_state resets on browser refresh. Implement explicit Force Reprocess path in A-03.

### R2: Publishing state introduces double-write
B-01 adds mark_as_publishing before the chain plus mark_article_published at the end. If mark_as_publishing fails, publication doesn't start. If recovery has a bug, articles get stuck in `publishing` forever.
**Mitigation**: Add timeout — if article is in `publishing` for >1 hour, allow re-processing. Test recovery path independently.

### R3: PR 422 recovery picks wrong PR
A-04 converts a 422 error into success by finding an existing PR. If the branch name collided with a different article's branch, the wrong PR would be associated.
**Mitigation**: Branch names include the article slug (deterministic). Verify PR title matches current article before returning URL.

### R4: Content hash dedup produces false positives
B-03 runs content hash dedup for all articles. If normalization is too aggressive, different articles could hash identically.
**Mitigation**: SHA256 has extreme collision resistance. Monitor for rejected articles after deploying; add length guard if false positives appear.

### R5: Structural fix breaks happy path
B-01 changes the publication state machine. A bug in the new recovery logic could prevent normal publication.
**Mitigation**: Implement as additive code (check at start, mark before git ops). Don't modify the existing happy path. Integration test covers both recovery and normal paths.

---

## What NOT to do now

| Don't | Why |
|-------|-----|
| Migrate to PostgreSQL | Fixes work on both SQLite and PostgreSQL. Migration adds risk without closing any finding. |
| Introduce saga/outbox pattern | A `publishing` state flag is sufficient. The system has a single publication process, not distributed transactions. |
| Rewrite Streamlit app | Double-click and state issues are fixed with 6-line guards. Framework migration is weeks of work for no finding closure. |
| Expand test coverage to all modules | Extend to storage/ and logic/workflows/ first (most critical). Other modules can wait for future cycles. |
| Refactor process_single_article | The method is large but the surgical fixes (B-01, B-02) are safer as local changes. A full refactor during remediation maximizes regression risk. |
| Add article versioning | Git history already provides content versioning. DB-level versioning is a feature, not a remediation. |
| Add confirmation modals in Streamlit | Streamlit lacks native robust modals. The checkbox+button pattern already used for Reset is sufficient. |
