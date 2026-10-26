# Plan 200 — modelos por etapa tras la baja de Nemotron Super

## Contexto (auditoría E2E del 2026-10-26)

- `nvidia/nemotron-3-super-120b-a12b`, modelo principal configurado, responde
  404 "Function … Not found for account" desde el 2026-10-20 (último éxito
  2026-10-19). Todo el trabajo editorial cayó en silencio a Gemini, Groq,
  Cloudflare y OpenRouter, con fallos propios (Gemini 4/4, Groq 429/413) y un
  crítico editorial con veredicto incompleto.
- El preflight no lo detectó: `NvidiaProvider.check_health` solo lista
  `/models`, que incluye el modelo aunque la cuenta no pueda llamarlo.
- La verificación de hechos usa un modelo local de 50 GB (`qwen3-next:80b`) que
  el kernel mató por memoria en cada afirmación; todas quedaron `uncertain`.
- Prueba en vivo del catálogo con la clave del proyecto: responden
  `nemotron-3-ultra-550b-a55b` y `nemotron-3.5-lightning-30b-a3b`; kimi-k2.6 y
  mistral-large-2 dan 404; glm-5.3, step-5-preview, deepseek-v4.1-flash y
  gemma-4-31b no responden en 120–150 s.

## Objetivo

1. **Redacción** (traducción, edición, titulares, críticos): Nemotron Ultra
   con razonamiento completo.
2. **Verificación de hechos**: cadena propia sin el modelo del redactor
   (`groq` → `gemini` → `cloudflare` → Ollama), conservando la independencia
   verificador/redactor y sin depender de memoria local.
3. **Fetching**: scoring sin cambios (Groq primero). Preselección: Lightning
   con razonamiento bajo **solo si** su coincidencia Top-5 con Ultra no es
   peor que la de Ultra consigo mismo; si no, Ultra con razonamiento bajo.
4. **Alerta**: el preflight hace una llamada de 1 token al modelo
   configurado; 401/403/404/422 detienen la publicación con un mensaje que
   indica cambiar `[nvidia].model`. Timeouts y 5xx no bloquean.
5. Apéndice del ADR-0010 con la decisión forzada.

## Verificación

- Tests: `probe_model` (200/404/401/503/timeout), `NvidiaHealthChecker` ante
  404, cadena del verificador sin el redactor, verificador local sin cadena.
- Medición de preselección: 8 lotes reales × 2 corridas por modelo.
- Gates: test, contracts, boundaries, lint, type, docs.
- E2E real: repetir la publicación del artículo 4021.

## Resultado de la medición de preselección (2026-10-26)

8 lotes reales de 25 candidatos × 2 corridas, prompt de producción de
`PreScorer`, `reasoning_effort = "low"`:

| | Ultra | Lightning |
| --- | --- | --- |
| Coincidencia Top-5 consigo mismo | 0,70 | 0,62 |
| Coincidencia con Ultra | — | 0,54 |
| Latencia p50 / máx. | 17 s / 34 s | 63 s / 89 s |

Decisión: la preselección sigue en el modelo principal (ahora Ultra) con
razonamiento bajo; no se añade endpoint para Lightning.
