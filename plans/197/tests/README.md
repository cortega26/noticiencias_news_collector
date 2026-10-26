# Plan 197 — pruebas

Cambio solo de documentación; la prueba son los gates existentes:

```
.venv/bin/python scripts/check_doc_drift.py
.venv/bin/python scripts/validate_plans_ledger.py
.venv/bin/python scripts/generate_inventory.py --output reports/audit/00_inventory.generated.json --sample-size 10 --compare-to audit/00_inventory.json --fail-on-drift
```

Resultados de la última ejecución: ver `todo.md`.
