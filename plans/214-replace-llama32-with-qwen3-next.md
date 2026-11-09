# Plan 214 — Sustituir `llama3.2` por `qwen3-next:80b-a3b-instruct-q4_K_M`

## Objetivo

Retirar `llama3.2` del proyecto y de la instalación local de Ollama. Las etapas
baratas (`headlines`, `scoring`, `pre_scorer`) usaban `llama3.2:latest`, un modelo
de 3B sin soporte de razonamiento ni actualizaciones; el resto del pipeline ya usa
`qwen3-next:80b-a3b-instruct-q4_K_M` (MoE de 80B con 3B parámetros activos,
instruct, sin razonamiento).

Criterios de aceptación:

- `config.toml` (`[scoring].llm_model`, `[ollama].headlines_model`) y los valores de
  ejemplo de `.env.example` apuntan a `qwen3-next:80b-a3b-instruct-q4_K_M`.
- El panel de administración, `scripts/bench_qwen35_json.py`,
  `scripts/quality_gate_refresh.py`, los comentarios y los tests vivos ya no
  mencionan `llama3.2`.
- `git grep -i llama3.2` solo devuelve registros históricos (ver abajo).
- `make lint`, `make type` y `make test` pasan.
- `ollama rm llama3.2:latest` ejecutado **después** de fusionar este cambio.

## Decisiones

- **Un solo modelo residente.** `resolve_ollama_stage_models` ya asigna Qwen3 Next
  a seis etapas; alternar con un segundo modelo obliga a descargar y recargar unos
  50 GB. Con un solo modelo el servidor evita esas recargas.
- **No se usa `qwen3.5:4b`.** Es un modelo de razonamiento: en una sonda local
  (2026-11-09) gastó los 300 tokens de presupuesto en "pensar" y no devolvió
  respuesta, a 7,9 tokens/s. No es adecuado para las etapas JSON cortas.
- **Registros históricos intactos.** No se reescriben porque falsearían de qué
  modelo salieron: `tests/data/editorial_eval/baseline.jsonl` (metadatos de
  captura), `quality_gate/golden/**` (snapshots), `plans/080/**` (resultados),
  `archive/**`, `latest-log.txt`, la nota histórica de otro plan en `plans/README.md`, la auditoría
  `docs/audits/OLLAMA_MODEL_CONCORDANCE_AUDIT.md` (usa `llama3.2` como ejemplo de
  alias) y `spec-nvidia-routing-fix.md`.
- **Los ids de prueba del registro** (`test_model_registry.py`) pasan a tags fijados
  de Qwen3.5; la lógica que prueban no depende del nombre.

## Riesgo

`scoring` es la etapa de mayor volumen. Pasar de un 3B denso a un MoE de 80B (unos
13 tokens/s en CPU en esta máquina) puede alargar las corridas de puntuación. Se
espera compensar con la ausencia de recargas, pero **no está medido**: vigilar la
duración de `scoring` en las primeras corridas. Si se degrada, usar un modelo
intermedio fijado en `[scoring].llm_model` (un cambio de una línea).

## Verificación

| Comprobación | Comando | Resultado esperado |
|---|---|---|
| Sin referencias vivas | `git grep -i llama3.2 -- . ':!uv.lock' ':!tests/data' ':!quality_gate/golden' ':!plans/080' ':!archive' ':!latest-log.txt' ':!docs/audits' ':!spec-nvidia-routing-fix.md' ':!plans/214-*' ':!plans/README.md'` | vacío |
| Calidad | `make lint && make type && make test` | verde |
| Ledger | `make plans-ledger-check` | OK |
