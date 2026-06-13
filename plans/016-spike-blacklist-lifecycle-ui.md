# Plan 016: Spike — bring the source-blacklist lifecycle into the Refinery Sources tab

> **Executor instructions**: A **design/spike plan**. Deliverable = an investigation
> note (resolving a two-store consistency question) + a thin, auth-gated UI slice —
> NOT the full feature. Honor STOP conditions. Update `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- scripts/audit_sources.py news_collector/config/sources.py news_collector/storage/models.py apps/refinery/admin_panel.py`

## Status

- **Priority**: P3
- **Effort**: M (spike-scoped)
- **Risk**: MED (writes to source state — must be auth-gated)
- **Depends on**: plan 013 Fix 1 (blacklist persistence) and plan 014 Fix A (edit must not drop blacklist keys) should land first — see Maintenance notes
- **Category**: direction
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

Disabling a failing source is a routine maintenance task that today requires dropping to a CLI (`audit_sources.py suggest-blacklist`, then `blacklist <id>`). The Sources tab shows health but has no affordance to see blacklist candidates or act on them, and no feedback loop. This spike designs that surface — but its **first job is to resolve a real consistency hazard**: blacklist state is stored in **two places**.

## Grounding evidence — and the two-store problem

- **DB store**: `scripts/audit_sources.py:71-100` (`cmd_suggest_blacklist`) queries the
  ORM `Source` model: `Source.blacklisted.isnot(True)` + `Source.consecutive_failures >= min_failures`.
  `cmd_list_failing:40-67` reads `Source.status` / `Source.consecutive_failures`. So
  **failure counts and one blacklist flag live in the DB.**
- **YAML store**: `cmd_blacklist` (`audit_sources.py:108-141`) writes `blacklisted` /
  `blacklist_reason` / `blacklisted_date` into **`sources.yaml`** via `save_sources`
  (and `news_collector/config/sources.py:250-258` validates those YAML fields on load).
  So **the human-applied blacklist decision lives in YAML.**
- **UI**: `apps/refinery/admin_panel.py:2730` ("Gestión de Fuentes RSS") — the Sources
  tab; add/edit/delete + health, but no blacklist flag/candidate/bulk action
  (`grep "blacklist" apps/refinery/admin_panel.py` → none).

**The hazard**: `Source.blacklisted` (DB) and `sources.yaml` `blacklisted` can disagree.
A UI blacklist action must pick the authoritative store and keep them consistent — and
must not be silently undone by a source edit (plan 014 Fix A).

## Spike deliverables

1. **Investigation note** `docs/spikes/blacklist-lifecycle-ui.md` that **first** resolves:
   which store is authoritative (YAML config vs DB `Source.blacklisted`), how they're
   meant to relate, and whether the collector reads YAML, DB, or both at runtime to skip
   blacklisted sources. Cite `file:line`. Then sketch the UI lifecycle.
2. **A thin, read-only-first UI slice**: surface in the Sources tab a **read-only**
   "blacklist candidates" list (sources with `consecutive_failures >= N`, reusing the
   `cmd_suggest_blacklist` query) and each source's current blacklist flag. Adding the
   *write* action (a single auth-gated blacklist button writing to the authoritative
   store via the existing `save_sources`/ORM path) is OPTIONAL in this spike and only if
   the consistency question is cleanly resolved (see STOP).
3. **Recommendation**: the smallest safe lifecycle (read-only candidates only? single
   blacklist button? bulk?) and the consistency fix needed before any bulk write.

## Open questions the note must answer

- Which store does the **collector** consult to skip a blacklisted source at runtime —
  YAML, DB, or both? (Search collectors/source-loading for `blacklisted`.) This decides
  the authoritative store.
- Can a UI write reuse `save_sources` (YAML) or must it also update `Source.blacklisted`
  (DB) to take effect? If both, they must be written atomically/consistently.
- What's the existing auth gate for write actions in the Sources tab (the Reset flow at
  `admin_panel.py:1690` uses one) — reuse it.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| AST parse | `.venv/bin/python -c "import ast; ast.parse(open('apps/refinery/admin_panel.py').read()); print('ok')"` | `ok` |
| Lint | `make lint` | exit 0 |
| Refinery tests | `.venv/bin/pytest tests/decompose_refinery -q` | pass |

## Scope

**In scope:** `docs/spikes/blacklist-lifecycle-ui.md`; a read-only candidates section in the Sources tab; optionally ONE auth-gated single-source blacklist button (only if consistency is resolved).

**Out of scope:** bulk blacklist writes; changing the blacklist data model; the collector's skip logic; the frontend repo.

## Git workflow

- Branch: `advisor/016-blacklist-lifecycle-spike`; commits: note, then read-only slice. Do NOT push.

## Steps

### Step 1: Resolve the two-store question (the spike's core)
Read the collector source-loading path, `config/sources.py`, and the `Source` model. Document the authoritative store and the runtime read path in the note. **If the two stores can disagree with real consequence, that inconsistency is itself a finding — record it.**

### Step 2: Read-only candidates slice
Add a Sources-tab section listing blacklist candidates (reuse the `cmd_suggest_blacklist` query via the DB session the tab already uses) and each source's current blacklist flag. No writes yet.

### Step 3: (Optional) one auth-gated write
Only if Step 1 yields a single authoritative, consistent write path: add one blacklist button (with the Reset flow's auth gate + a confirmation + reason input) that writes via the existing `save_sources`/ORM path. Otherwise document why it's deferred.

**Verify:** AST parse + `make lint` + `make test` green; the read-only slice renders.

## Done criteria

- [ ] `docs/spikes/blacklist-lifecycle-ui.md` resolves the authoritative-store question with `file:line` evidence + a recommendation
- [ ] Read-only blacklist-candidates view in the Sources tab (reusing the suggest query)
- [ ] Any write action is auth-gated and writes one authoritative, consistent store — or is explicitly deferred with reasoning
- [ ] AST parse + `make lint` + `make test` green; only in-scope files changed
- [ ] `plans/README.md` row updated

## STOP conditions

- The YAML and DB blacklist stores can disagree and no single authoritative path is clear → deliver the note + read-only slice, **defer all writes**, and report the inconsistency as a bug to fix first.
- A write action would require changes beyond the existing `save_sources`/ORM helpers → report.

## Maintenance notes

- Sequence with the bug plans: **plan 013 Fix 1** makes `blacklist` actually persist to
  YAML, and **plan 014 Fix A** stops source edits from dropping `blacklisted` keys. A UI
  blacklist feature is unsafe until both land — note this dependency prominently.
- A reviewer should confirm no write path can leave the two stores inconsistent.
