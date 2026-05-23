# Todo: Fix Deprecated Streamlit use_container_width parameter

- [x] **Phase 1: Implement parameter replacement**
  - [x] Replace `use_container_width=True` with `width="stretch"` in `apps/refinery/admin_panel.py`.

- [x] **Phase 2: Establish regression guards**
  - [x] Add static analysis test `test_no_deprecated_streamlit_args` to `tests/test_ui_contracts.py`.
  - [x] Add guideline about deprecated Streamlit arguments in `docs/AGENTS.md` under Section 3.5.

- [x] **Phase 3: Validation**
  - [x] Run `make lint` (verifying `check-deprecated` target passes).
  - [x] Run `make test` (verifying test suite and the new static analysis check pass).
