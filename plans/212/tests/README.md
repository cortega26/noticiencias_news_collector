Las pruebas viven en `tests/unit/editorial/test_evidence_gate.py` (reglas puras:
siglas, cifras, DOI, fuente corta, equivalentes, siglas definidas) y
`tests/unit/logic/workflows/test_evidence_gate_wiring.py` (el motor bloquea antes de
publicar en la ruta nueva y en la reanudada desde checkpoint, y falla cerrado si el
chequeador se rompe). Los fixtures son sintéticos: no se versiona texto de fuentes.
