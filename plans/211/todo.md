# Plan 211 — todo

- [x] Spec y tabla de defectos observados (#406, #402, #398, #391)
- [x] `news_collector/editorial/source_integrity.py` (puro)
- [x] Cableado en `prepare_editorial_draft` + `evidence_text` en `PublicationArtifactInput`
- [x] Pasar `content` como evidencia desde `ai_editor.prepare_article`
- [x] Prompt de enriquecimiento: probado en A/B real y descartado (ver spec); `config/prompts.yaml` no cambia
- [x] `tests/unit/editorial/test_source_integrity.py` + prueba de cableado
- [x] `make lint && make type && make test && make quality-gate`
- [x] Fila en `plans/README.md`
- [x] Sin cambio de la cadena LLM: no requiere `make llm-canary`
- [x] Evidencia de una ejecución real aislada (A/B de `sources` con `qwen3-next`): las reglas deterministas descartaron las 2 URLs inventadas
