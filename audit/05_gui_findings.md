# Phase 5 — GUI Config Editor E2E

## Summary
- Added pytest coverage that exercises saving and reloading through `ConfigEditor` using real file persistence.
- Verified the CLI `python -m noticiencias.config_manager --explain` reflects GUI edits, ensuring both interfaces stay in sync.
- Documented the recommended validation loop so operators confirm GUI changes from headless shells.

## Test Evidence
- `pytest tests/gui/test_gui_config_persistence.py`

## Key Assertions
| Scenario | Checkpoints |
| --- | --- |
| GUI save on temporary config | `database.connect_timeout` updated to 42 in TOML, `collection.async_enabled` toggled true, CLI `--explain` shows new value sourced from file |
| GUI reload after external write | `_reload()` refreshes widgets with `database.connect_timeout=99` and `collection.async_enabled=True` from disk |

## Documentation Updates
- README `Herramientas de soporte` now instructs validating GUI edits via the CLI explain command for provenance confirmation.
