# Plan 119: Make the contract-sync gate see cross-field rules

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/contracts/frontend_schema.py` plus, in `../noticiencias/`, `git diff --stat a37798c..HEAD -- scripts/check-contract-sync.js src/content.config.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/118-contract-parity.md (the divergences this gate
  will assert on must be fixed first — otherwise the gate goes red by design)
- **Category**: tests
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

The cross-repo gate that is supposed to catch exactly the plan-118 class of
drift is structurally blind to it: `check-contract-sync.js` compares only
type/optionality/default/min/max per field and downgrades known mismatches
via `ALLOWED_DIVERGENCES` — it never examines `superRefine` (frontend) or
`model_validator` (backend) cross-field rules (v2 block, featured-rank
pairing, correction pair, social-id-required, doi-requires-primary,
image_alt). CI stays green while the two schemas diverge in exactly the
dimension that breaks builds. This plan adds a rule-level invariant table
(one case per cross-field rule, executed against both `AstroPost` and the
Zod schema) and shrinks `ALLOWED_DIVERGENCES` as plan 118 lands.

## Current state

Facts (verified 2026-10-11):

- Frontend `scripts/check-contract-sync.js:115-147`:
  `ALLOWED_DIVERGENCES` with entries including (line ~139)
  `'Zod adds .positive() constraint; Python relies on superRefine validator'`;
  `:144-147` downgrades `type_mismatch`/`constraint_mismatch` to warnings
  forever, including `--strict`; `:1171-1216` strict mode still honors the
  allowlist; `:1268` strict failure message.
- `compareFields` checks only type/optionality/default/min/max — no
  `superRefine`/`model_validator` handling (confirmed by grepping the
  script for `superRefine|model_validator|cross-field`: only the
  line-parser comment region at `:863` and the allowlist).
- `src/content.config.ts:1-20` module-scope comment: the line-based parser
  cannot skip `//` comments inside the `z.object` body — schema comments
  must live at module scope. Any gate change must respect this parser
  limitation (do not "fix" it by rewriting the parser's line model unless
  the invariant-table approach proves unworkable — and report first).
- The six cross-field invariants to enumerate: (1) v2 editorial block,
  (2) featured→featured_rank, (3) correction pair travels together,
  (4) social.id required when publishing (+ strict bool, null rejected),
  (5) doi requires primary role, (6) image_alt required without inline alt.

Repo conventions: the gate runs in frontend CI (`content-guard.yml`) and
via `npm run check:contract-sync` / `--strict`; backend contract tests via
`make test-contracts`. The gate must stay fast and deterministic (no
network, no LLM).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Frontend sync | `npm run check:contract-sync` (from `../noticiencias/`) | declared | exit 0 |
| Frontend strict | `npm run check:contract-sync -- --strict` (check exact flag in script help first) | declared | exit 0 |
| Backend contracts | `make test-contracts` | declared | pass |
| Backend lint | `make lint` | declared | exit 0 |

## Scope

**In scope** (the only files you should modify):

- Frontend `scripts/check-contract-sync.js` (invariant table + snapshot;
  shrink `ALLOWED_DIVERGENCES` for the plan-118-fixed entries)
- Frontend contract-sync test (`tests/contract-sync.test.ts` — extend)
- Backend: at most a shared fixture file if the invariant table needs one
  (prefer deriving cases from existing backend tests; new backend file only
  if unavoidable — and then it must be covered by `make test-contracts`)

**Out of scope** (do NOT touch, even though they look related):

- `src/content.config.ts` and `frontend_schema.py` rule logic — plans 118/120 own those.
- Rewriting the line-based schema parser — out unless the table approach
  is provably unworkable (STOP first).
- Adding new `ALLOWED_DIVERGENCES` entries — this plan only shrinks.

## Git workflow

Two repos are touched (gate lives in frontend). Work in the frontend
checkout for the gate change; backend only if a fixture is needed.

- Branch (frontend): `advisor/119-contract-gate`
- Commit style matches each repo's log (`chore:`/`fix:`).
- Do NOT push or open a PR unless the operator instructed it.
- Update the status row in the backend `plans/README.md` (this plan file
  lives there); note the frontend file change in the row if needed.

## Steps

### Step 0: Baselines

Confirm plan 118 is DONE (its validators exist in `frontend_schema.py`).
Run frontend `npm run check:contract-sync` (both modes) and backend `make
test-contracts` on unmodified checkouts; record outputs.

**Verify**: 118's rules exist; both gates green at baseline.

### Step 1: Build the invariant table

Add a small invariant table to the gate: one case per cross-field rule
(the six listed above), each case executable against BOTH sides — the Zod
schema (via the frontend's existing test harness, see
`tests/content-config-schema.test.ts` pattern) and `AstroPost` (via a
python probe the gate shells out to, or via cases mirrored in
`make test-contracts` with the gate asserting the backend suite passes —
prefer the latter: the gate asserts file-level evidence rather than
re-implementing pydantic).

Concretely: for each invariant, the gate checks (a) the frontend schema
rejects the violating payload, and (b) the backend contract test suite
contains a case rejecting the same violation (grep the backend test file
for the case name — brittle but explicit; document the coupling).

**Verify**: each of the six invariants fails-closed on at least one
negative probe you run by hand (temporarily violate each rule in a
fixture; confirm rejection; delete fixtures).

### Step 2: Shrink ALLOWED_DIVERGENCES

Remove the entries plan 118 fixed (`summary_points` min/max,
`featured_rank` positive, and any empty-item tolerance). Each removal must
keep the gate green — if removing one goes red, the underlying parity is
incomplete: STOP and report (do not re-allowlist to force green).

**Verify**: `check:contract-sync` normal + strict both exit 0 with the
smaller allowlist; the allowlist diff shows only deletions.

### Step 3: Full gates

Run the frontend contract-sync tests + backend `make test-contracts` +
`make lint` (backend, if touched).

**Verify**: all green.

## Test plan

- Extend the frontend contract-sync test with one test per invariant (6),
  each asserting both-sides rejection of the violating payload.
- Backend cases already exist from plan 118 (reference them by name in the
  gate's table — the gate greps for them).
- Verification: gate green in both modes; backend suite green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] Six invariants enumerated in the gate; six negative probes verified by hand during work
- [ ] `ALLOWED_DIVERGENCES` has fewer entries than at baseline (list the removed ones in the commit message)
- [ ] Frontend `check:contract-sync` (normal + strict) exits 0
- [ ] `make test-contracts` passes
- [ ] `git diff --name-only` (frontend) lists only `scripts/check-contract-sync.js` + its test; (backend) lists at most one fixture/test file
- [ ] Backend `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 118 is not DONE (its validators missing — sequencing violation).
- The line-parser limitation (`content.config.ts:1-20`) blocks the table
  approach (report; don't rewrite the parser).
- Shrinking the allowlist goes red (parity incomplete — report which entry).
- The gate cannot execute backend-side evidence without network/LLM
  (report; the gate must stay hermetic).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- Every new cross-field rule (either repo) must add one invariant row in
  the same PR — add this to the review checklist (the gate can't remind
  you itself).
- **Deferred:** replacing the line-parser with an AST parse — only if the
  table approach starts missing a second class of rules; unblocked by nothing.
