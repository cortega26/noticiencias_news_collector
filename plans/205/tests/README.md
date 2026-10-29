# Plan 205: tests

Los tests viven en la suite existente para que corran en `make test`:

- `tests/unit/editorial/test_fact_check_correction.py`: bucle de política, todas las ramas.
- `tests/unit/editorial/test_fact_check_verification.py` (`TestAutomaticCorrectionIntegration`
  y `test_plan_205_prompts_declare_their_output_contract`): integración en `process_article`.

```bash
.venv/bin/python -m pytest -q --no-cov tests/unit/editorial/test_fact_check_correction.py tests/unit/editorial/test_fact_check_verification.py
```
