# Plan 014: Fix Refinery source-editor data loss + null-component crash + per-rerun N+1

> **Executor instructions**: Three fixes in one file (`apps/refinery/admin_panel.py`).
> Do each as its own commit. Run every verification before moving on. Honor STOP
> conditions. Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- apps/refinery/admin_panel.py`
> If it changed, compare each "Current state" excerpt to the live code; on a
> mismatch for a given fix, STOP for that fix.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (Streamlit UI; `apps/refinery/` is excluded from `make type` and runs under a separate `.venv`)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

Three concrete defects in the editorial admin UI: (A) editing a source **silently wipes** its metadata, (B) viewing a candidate with a null score component **crashes the page**, and (C) the candidate list issues one DB query per article on **every** Streamlit rerun. (A) is data loss, (B) is a hard crash on real data, (C) is avoidable latency that grows with list size.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| AST parse (refinery isn't in mypy) | `.venv/bin/python -c "import ast; ast.parse(open('apps/refinery/admin_panel.py').read()); print('ok')"` | `ok` |
| Lint | `make lint` | exit 0 |
| Refinery tests | `.venv/bin/pytest tests/decompose_refinery -q` (+ any you add) | pass |

(`make type` does not cover `apps/refinery/`. Rely on AST parse + lint + targeted tests.)

## Scope

**In scope:** `apps/refinery/admin_panel.py` (the three regions below) and tests you add.
**Out of scope:** the source-registry schema, the DB layer, other tabs. Do not change the `_group`/sources YAML format — only stop dropping values.

## Git workflow

- Branch: `advisor/014-refinery-robustness`
- One commit per fix; `fix(refinery): …` style.
- Do NOT push or open a PR.

---

## Fix A — Source editor wipes metadata on edit (data loss)

### Current state
```python
# apps/refinery/admin_panel.py:2860-2935  (source editor form)
default_data = current_sources.get(selected_source_id, {}).copy()
...
credibility = st.slider("Score Credibilidad", 0.0, 1.0,
                        float(default_data.get("credibility_score", 0.8)))   # (this one is correct)
category = st.selectbox("Categoría", [ ...8 options... ], index=0)            # <-- ignores existing
update_freq = st.selectbox("Frecuencia Actualización", [ ...4 options... ], index=0)  # <-- ignores existing
group_tag = st.selectbox("Grupo (...)", [ ...5 options... ], index=1)         # <-- ignores existing
...
new_entry = {
    "name": name, "url": url, "credibility_score": credibility,
    "category": category, "update_frequency": update_freq,
    "language": "en",                 # <-- hardcoded, drops existing
    "description": "Added via UI",     # <-- hardcoded, drops existing
    "typical_delay": 0,                # <-- hardcoded, drops existing
    "_group": group_tag,
}
current_sources[new_id] = new_entry    # <-- FULL REPLACE: drops every other key
```
Editing an existing source to fix its URL resets category/frequency/group to the first option and overwrites language/description/typical_delay with literals, and the full-dict replace drops any keys not listed (e.g. `blacklisted`, `blacklist_reason`).

### Steps
1. **Preselect the existing value** for each selectbox. Helper:
   ```python
   def _index_of(options, value, default=0):
       try:
           return options.index(value)
       except (ValueError, TypeError):
           return default
   ```
   Define the options lists once (variables), then pass `index=_index_of(cat_options, default_data.get("category"))` etc. for category, update_frequency (`default_data.get("update_frequency")`), and group (`default_data.get("_group")`, default 1).
2. **Preserve, don't replace.** Build `new_entry` by copying `default_data` first, then overlaying the edited fields:
   ```python
   new_entry = dict(default_data)  # keep blacklist flags & any other keys
   new_entry.update({
       "name": name, "url": url, "credibility_score": credibility,
       "category": category, "update_frequency": update_freq, "_group": group_tag,
   })
   # only set language/description/typical_delay defaults when creating a NEW source
   if is_new:
       new_entry.setdefault("language", "en")
       new_entry.setdefault("description", "Added via UI")
       new_entry.setdefault("typical_delay", 0)
   ```
   (For an edit, existing `language`/`description`/`typical_delay` survive untouched.)

**Verify:** add a unit test for `_index_of` (pure function): `_index_of(["a","b","c"], "b") == 1`, `_index_of(["a"], "zzz") == 0`. Put it in `tests/decompose_refinery/` following that suite's import pattern. `grep -n "index=0,  # Should try to match existing" apps/refinery/admin_panel.py` → no matches (the apologetic comment is gone). AST parse + `make lint` clean.

---

## Fix B — `float(None)` crash on null score components

### Current state
```python
# apps/refinery/admin_panel.py:525-535
components = selected_art.get("components") or {}
source_cred = float(components.get("source_credibility", 0.0))   # crashes if value is None
recency     = float(components.get("recency", 0.0))
quality     = float(components.get("content_quality", 0.0))
engagement  = float(components.get("engagement_potential",
                                   components.get("cognitive_engagement_norm", 0.0)))
overall_score = float(selected_art.get("score", 0.0))
```
`.get(key, 0.0)` returns the default only when the key is **absent**. If the export has `"source_credibility": null`, `.get` returns `None` and `float(None)` raises `TypeError`, crashing the candidate render (this path is not wrapped in try/except).

### Step
Coalesce `None` to the default. Add a tiny helper and use it for all five conversions:
```python
def _as_float(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
```
Replace `float(components.get("source_credibility", 0.0))` with `_as_float(components.get("source_credibility"))`, and likewise for the others (including `overall_score`).

**Verify:** unit-test `_as_float(None) == 0.0`, `_as_float("1.5") == 1.5`, `_as_float("x") == 0.0`. AST parse + lint clean.

---

## Fix C — N+1 `is_article_published` per article on every rerun

### Current state
```python
# apps/refinery/admin_panel.py:2318-2345
if articles:
    refinery_db = DatabaseManager()
    for art in articles:
        art_id = str(art.get("id", art.get("title")))
        if not show_processed:
            try:
                numeric_id = int(art_id)
                if refinery_db.is_article_published(numeric_id):   # <-- one query per article, every rerun
                    filtered_count += 1
                    continue
            except ValueError:
                pass
```
For N candidates, this fires N queries on every Streamlit rerun (scroll, click, any widget change).

### Step
Compute the set of published IDs **once** before the loop, then check membership in memory.
1. Collect the numeric candidate IDs first:
   ```python
   candidate_ids = []
   for art in articles:
       try: candidate_ids.append(int(str(art.get("id", art.get("title")))))
       except (ValueError, TypeError): pass
   ```
2. Get published IDs in one query. Check `DatabaseManager` for an existing batch method (search the storage layer for something like `get_published_ids` / `articles_published_in(ids)` / a status filter). If one exists, use it. If not, add a small read-only method on the manager, e.g.:
   ```python
   # in news_collector/storage (the manager or article_repository):
   def published_ids_in(self, ids: list[int]) -> set[int]:
       if not ids: return set()
       with self._session() as s:
           rows = s.query(Article.id).filter(
               Article.id.in_(ids),
               or_(Article.published_url.isnot(None), Article.published_at.isnot(None)),
           ).all()
       return {r[0] for r in rows}
   ```
   **CORRECTED PREDICATE (2026-06-13):** the real `is_article_published`
   (`article_repository.py:266-273`) returns `published_url is not None or
   published_at is not None` — it does **NOT** use `processing_status == "published"`.
   Use `or_(published_url.isnot(None), published_at.isnot(None))` (add `or_` to the
   `from sqlalchemy import ...` line). Add the method to `ArticleRepository` AND a
   one-line delegate on `DatabaseManager` (mirroring `is_article_published`'s delegation).
3. In the UI loop, replace the per-article query with `if numeric_id in published_id_set:`.

**Verify:** the loop no longer calls `is_article_published` inside it (`grep -n "is_article_published" apps/refinery/admin_panel.py` → only the new batch usage or none in the hot loop). If you added a storage method, add a unit test for it under `tests/` (it touches the DB layer, which *is* in `make type` scope — so `make type` must stay green). AST parse + `make lint` clean.

> **STOP for Fix C** if adding a batch method means touching `news_collector/storage/` in a way that ripples beyond one small read-only method — report the options rather than reshaping the storage API. Fixes A and B can ship without C.

## Done criteria

ALL must hold:

- [ ] Fix A: selectboxes preselect existing values; `new_entry` preserves `default_data` keys; the "Simplified for now" comment is gone; `_index_of` test passes
- [ ] Fix B: all five `float(...)` conversions use the None-safe helper; helper test passes
- [ ] Fix C: the candidate loop does not query the DB per article (batched or via in-memory set); if a storage method was added it has a test and `make type` is green
- [ ] `apps/refinery/admin_panel.py` AST-parses; `make lint` exits 0
- [ ] New tests pass; `make test` exits 0
- [ ] Only `admin_panel.py` (+ optionally one small storage method) and test files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Any "Current state" excerpt no longer matches (drift) for that fix.
- Fix C requires more than a single small read-only storage method (report; A/B can still ship).
- Stubbing Streamlit to test the source-editor form is disproportionate — the pure helpers (`_index_of`, `_as_float`) are the testable seams; test those and report the form itself as manually verified.

## Maintenance notes

- A reviewer should confirm Fix A no longer overwrites `blacklisted`/other keys on edit (the bug interacts with the blacklist work in plan 013 — a source blacklisted via CLI must not be silently un-blacklisted by a UI edit).
- Fix C's batch predicate must exactly match `is_article_published`'s definition of "published" or the filter behavior changes.
