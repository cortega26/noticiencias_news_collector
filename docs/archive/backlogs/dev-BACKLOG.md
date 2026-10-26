# Backlog (Non-Critical Tech Debt)

## Tech Debt

- [x] **Config Consolidation**: `apps/refinery` uses its own `.env`. Merge into central `config.toml`. **DONE** — `apps/refinery/admin_panel.py` now loads the root `.env`; a detected `apps/refinery/.env` only triggers a migration warning ("ya no se usa como fuente de configuración").
- [ ] **Model Deduplication**: `CollectorArticleModel` (Pydantic) and `Article` (SQLAlchemy) share 90% fields but drift. Use `sqlmodel` or automated mapping.
- [ ] **Scorer Redundancy**: `PreScorer` (used in collectors) overlaps with `BasicScorer` (used in system). Unify into `ScoringService`.
- [x] **Logging Standardization**: Some modules use `logging.getLogger`, others use `NewsCollectorLogger` wrapper. Unify. **DONE** — all 50 modules using the logger go through `NewsCollectorLogger` (`utils/logger.py`); zero direct `logging.getLogger` call sites remain.
- [x] **Dependency Audit**: `requirements.txt` lists `pandas` and `streamlit` but they are only for auxiliary tools. Move to `dev` dependencies.

## Wishlist

- [x] **Mutation Testing**: Re-enable `mutmut` (present in pyproject.toml) to find weak tests. **DONE** — already enabled and running: `[tool.mutmut]` mutates `utils/text_cleaner.py` + `utils/url_canonicalizer.py`, CI job `.github/workflows/mutation.yml` (weekly + manual dispatch) installs mutmut fresh and runs the smoke suite then `mutmut run`. Verified locally 2026-08-13: 402 mutations, 283 killed, 118 survived — the surviving mutants are the weak-test signal; new-test coverage for those two utils is the follow-up if they ever gate.
- [ ] **Contract Tests**: Add schema generation for the scraping output to ensure downstream consumers (Refinery) don't break.
- [ ] **FastAPI Migration**: `serving/` module is barebones. Migrate to a proper `routers/` structure.
