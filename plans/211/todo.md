# Plan 211 — todo

- [x] Spec y tabla de defectos observados (#406, #402, #398, #391)
- [x] `news_collector/editorial/source_integrity.py` (puro)
- [x] Cableado en `prepare_editorial_draft` + `evidence_text` en `PublicationArtifactInput`
- [x] Pasar `content` como evidencia desde `ai_editor.prepare_article`
- [x] Prompt de enriquecimiento (`config/prompts.yaml`)
- [x] `tests/unit/editorial/test_source_integrity.py` + prueba de cableado
- [x] `make lint && make type && make test && make quality-gate`
- [x] Fila en `plans/README.md`
- [ ] Pendiente tras el merge: evidencia con una ejecución real aislada (`make llm-canary`), porque cambia un prompt de la cadena LLM
