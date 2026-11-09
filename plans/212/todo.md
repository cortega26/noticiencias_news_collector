# Plan 212 — todo

- [x] Spec, tabla de defectos y calibración con contenido real
- [x] `news_collector/editorial/evidence_gate.py` (puro) + `fold_text` público en `grounding.py`
- [x] Cableado en `RefineryEngine._enforce_publication_gates` (ruta nueva y reanudada)
- [x] Falla cerrada: fuente corta y defecto del chequeador
- [x] `tests/unit/editorial/test_evidence_gate.py` y `tests/unit/logic/workflows/test_evidence_gate_wiring.py`
- [x] Ajuste del test consultivo de grounding (fuente corta)
- [x] Fila en `plans/README.md`
- [ ] `make lint && make type && make test && make quality-gate` (ver estado en el PR)
- [ ] Fase 2: reescritura acotada antes de bloquear (requiere `llm-canary`)
- [ ] Fase 3: texto completo de preprints en la ingesta
- [ ] Fase 4: verificación de afirmaciones del cuerpo (plan 209)
