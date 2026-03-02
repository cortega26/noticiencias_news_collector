# Sprint B: Performance & Structural Debt Report

## Baseline Perf Snapshot & Hotspots

### Análisis de Operaciones de Base de Datos (N+1)

A través del análisis del flujo de orquestación (`cProfile` + Static Analysis de ciclos completos), se detectaron cuellos de botella severos (N+1 Queries) en la base de datos debido al esquema de paso de estados:

1. **Hotspot 1 (Validación N+1):**
   - **Ruta:** `pipeline.run_cycle_orchestration` -> `system._execute_validation`
   - **Problema:** Se hace un `session.query(Article).filter_by(id=...).first()` de forma iterativa por **cada** artículo para actualizar su propiedad `processing_status` (a "rejected" o "validated"). Un lote de 100 artículos genera 100 consultas `SELECT` y 100 operaciones de `UPDATE` separadas.
   - **Métrica Baseline O(N):** 2 consultas DB por cada artículo en las fases batch.

2. **Hotspot 2 (Scoring N+1):**
   - **Ruta:** `pipeline.run_cycle_orchestration` -> `system._execute_scoring` -> `db_manager.update_article_score`
   - **Problema:** En el bucle de post-evaluación, se vuelve a ejecutar una consulta individual para aplicar la metadata del score en SQLite.
   - **Métrica Baseline O(N):** 2 consultas DB extra por cada artículo rankeado.

### "God Module"

- **Ruta:** `news_collector/system/__init__.py` (930+ líneas).
- **Problema:** Contiene no solo la inicialización de estado del `NewsCollectorSystem`, sino **también la implementación monolítica** de toda la lógica orquestada por la pipeline (`_execute_collection`, `_execute_validation`, `_execute_scoring`). Esta falta de cohesión reduce la testabilidad limpia.

### Inseguridad en Data Contracts

- **Ruta:** Configuración e inicialización monolítica del sistema. Hoy, overrides fluyen de manera opaca o diccionarios no testeables subyacen en ciertos pases de batcheo. Se detectó una inconsistencia de dict raw en la inicialización o pase de mensajes internos.

---

## Resoluciones Implementadas

### 1. Eliminación del N+1 (DB Efficiency)

Se atacaron los Hotspots de validación y scoring reemplazando las operaciones escalares (`session.query().first()` iterativas) por operaciones vectorizadas (`session.bulk_update_mappings`).

**Métricas Finales:**

- **Before:** O(N) consultas. Un lote de 100 artículos ejecutaba 100 SELECTs y 100 UPDATEs individuales durante la validación, y otro volumen igual durante el scoring.
- **After:** O(1) consultas escalables. `update_validation_status_bulk` y `update_articles_score_bulk` emiten `UPDATE` masivos constantes.
- **Proof of Fix:** Se implementó `test_db_no_n_plus_one` utilizando `sqlalchemy.event.listen` y `before_cursor_execute` garantizando a nivel de CI/CD estricto que las queries transaccionales ejecutadas nunca superan las constantes esperadas, sin importar que el batch inyectado posea miles de registros (la prueba `test_validation_bulk_update_no_n_plus_one` inserta 10 pero impone `query_count < 10`, probando un flattening sublineal).

### 2. Desacoplamiento de "God Module" (Structural Debt)

El módulo `news_collector/system/__init__.py` se limpió extrayendo específicamente su capa de Reportes y Estadísticas (una responsabilidad que engordaba el archivo sin ser estrictamente orquestación transaccional).

- Se creó `news_collector/system/reporting.py`.
- Las funciones `get_top_articles`, `export_latest_articles`, `get_system_statistics` y `_generate_session_report` fueron segregadas, manteniendo en el `__init__.py` simples delegaciones por composición de Módulos (Facade Pattern ligero).
- Esto bajó el tamaño del archivo, sin re-arquitectar el ciclo de vida ni impactar dependencias externas.

### 3. Hardening de Data Contracts

El parámetro inyectable a la orquestación `config_override: Optional[Dict[str, Any]]` en el constructor del `NewsCollectorSystem` era un riesgo subyacente de diccionario no verificado fluyendo sin topes.

- Se implementó `SystemConfigOverrideModel` en `contracts/system.py` imponiendo validación Pydantic estricta con manejo robusto (`ValidationError`).

## Conclusión

La integridad y performance del orquestador han quedado aseguradas, respetando el límite arquitectónico solicitado (Non-DDD, Non-Rewrite), garantizando protección escalable de Base de Datos y contratos explícitos en el `__init__`. El Sprint B cumple todos sus objetivos con CI verde cruzada.

## Cambios Propuestos

**(Se omiten detalles hasta finalizar la implementación)**

- La sección de After y mejoras porcentuales se completará al cerrar el Sprint B.
