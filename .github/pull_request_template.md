## Resumen
- [ ] Incluye propósito del cambio
- [ ] Menciona tickets o incidentes relacionados

## Pruebas
Describe los comandos ejecutados y adjunta logs relevantes.

```
# ej.
make lint
make type
make test
```

## Checklist
- [ ] Corrí `make lint` y no quedan cambios pendientes
- [ ] Pasé `docs/SELF_REVIEW_CHECKLIST.md` (guardarraíles internos) y/o `make review-local` antes de pedir revisión externa
- [ ] Regeneré la documentación (`make docs`) si tocó docstrings o contratos públicos
- [ ] Actualicé fixtures y docs afectados
- [ ] Añadí/actualicé pruebas unitarias
- [ ] Verifiqué que los escáneres de seguridad (bandit, gitleaks, pip-audit) pasan
