# TODO — Plan 114 (series + transparency + search)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline (DONE 2026-09-16)
- [x] Drift check clean; backend aggregate file located (n=5)

## Step 1 — Series (DONE 2026-09-16)
- [x] 3 starter series, 21 posts tagged (IA en la práctica 7, Salud que importa 6, Espacio 8); dead-end placeholder gone
- [x] No schema change (`series` already optional in content contract)
- [x] `validate:content` green

## Step 2 — Transparency (DONE 2026-09-16)
- [x] Aggregates match backend file exactly (7.98/8.90/8.76/8.26, n=5 disclosed with small-sample caveat)

## Step 3 — Search budget (DONE 2026-09-16)
- [x] 122KB/150KB at 36 posts → ~10 posts headroom documented as trigger in check header; migration explicitly future work
- [x] `check:search-budget + build + dist` green

## Close-out
- [x] `validate_plans_ledger.py` → OK; row 114 updated
