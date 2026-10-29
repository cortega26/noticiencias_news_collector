# Plan 206: estado

- [x] Diagnóstico: la muestra de 6.000 caracteres omite el dato (artículo 3712)
- [x] Prueba decisiva con modelos reales: con la fuente completa los tres veredictos son correctos
- [x] Comprobado: 413/errores de cliente pasan al siguiente proveedor
- [x] Spec
- [x] Verificación por lotes con fuente completa e ids
- [x] Gravedad y corrección con el mismo presupuesto de fuente
- [x] Prompt `fact_check_verification` para varias afirmaciones
- [x] Tests reescritos y de regresión
- [x] Prueba con modelos reales sobre el artículo 3712: 8 afirmaciones en 1
      llamada a Groq (4.348 tokens, 1,6 s). Detecta los dos errores inyectados
      ("3 de 89" → la fuente dice 14; "300 veces" → la fuente dice 30), confirma
      las 4 verdaderas, "in silico" pasa a `uncertain` (ya no bloquea).
- [x] `make test` (4592 pasan; fallan solo los 2 de `test_daily_publish.py`,
      ya rojos en `main`), `make lint` limpio
- [ ] Seguimiento: una afirmación inventada que la fuente no menciona
      ("probado en pacientes con alzhéimer") queda en `uncertain` y no bloquea.
      Es la regla 4 del prompt; cambiarla es una decisión editorial aparte.
- [x] PR #420
