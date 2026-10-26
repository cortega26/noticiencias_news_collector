# Backlog de Noticiencias (backend)

Estado: vivo
Actualizado: 2026-10-25
Frontend: [`docs/BACKLOG.md` del sitio](https://github.com/cortega26/noticiencias/blob/main/docs/BACKLOG.md)

Este es el único lugar donde se registra **qué falta por hacer** en este repositorio. El gate de AdSense se define y se prioriza en el backlog del frontend; aquí solo figura lo que depende del backend.

## Reglas

- **Solo trabajo abierto.** Al cerrar un ítem, se quita de aquí y la evidencia queda en el plan correspondiente.
- **No sustituye al ledger ni a los registros por plan.** El estado de cada plan vive en [`plans/README.md`](../plans/README.md) (validado por `make plans-ledger-check`). Los `spec.md` y `todo.md` de cada plan o tarea los exige [`docs/AGENTS.md`](AGENTS.md) §0.1 como registro de ejecución: se enlazan, no se fusionan aquí.
- **Cada estado lleva fecha y fuente.** Si dos fuentes se contradicen, se escribe «por verificar»; no se adivina.
- **Dueño:** _Titular_ (decide, aprueba, tiene las cuentas) o _Agente_ (implementa y deja evidencia).
- **Archivo:** los backlogs cerrados están en [`archive/backlogs/`](archive/backlogs/).

## 1. Prioridad absoluta: aporte del backend al gate de AdSense

El gate (G1 a G5), su reloj y su criterio de cierre están en el backlog del frontend, §1. Lo que corresponde al backend es G2, la cadena editorial.

| #   | Ítem                                                                                                                                                                        | Dueño                                         | Estado (fecha)                                                                                                                                                                                                  | Se cierra cuando                                                                                          |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| B1  | Plan 191, pipeline editorial basado en evidencia: comparación vieja/nueva con un candidato real configurado y aceptación humana semántica                                    | Titular (aceptación) y Agente                 | PARTIAL en el ledger. Controles de ingeniería fusionados (#388, #389). No hay candidato real aceptado; los candidatos anteriores quedaron retenidos por seguridad (24-oct). Evidencia: [191/evidence.md](../plans/191/evidence.md) | Ejecución real revisada y aceptada por el titular; fila 191 del ledger en DONE                            |
| B2  | Prueba real del crítico editorial con un proveedor autorizado                                                                                                               | Titular (credenciales y autorización) y Agente | Pendiente: no hay credenciales de proveedor en el entorno. `make llm-canary` prueba el scoring, no el crítico editorial modificado                                                                              | Ejecución acotada de la ruta editorial con credenciales autorizadas; no se sustituye con una recolección de producción |
| B3  | Plan 190, procesamiento editorial independiente de la imagen: reconciliar el ledger                                                                                         | Agente                                        | La fila dice PARTIAL y «merge pendiente», pero el [PR #382](https://github.com/cortega26/noticiencias_news_collector/pull/382) ya está en `main` (verificado el 25-oct): **fila desactualizada**; el rollout, **por verificar** | Fila 190 actualizada con la evidencia de integración y el estado real del rollout                          |

## 2. Depende del titular

- [ ] Rotar las dos credenciales expuestas y decidir si se purga el historial de git (aviso «Read first» de [`plans/README.md`](../plans/README.md); el plan 194 repite que la rotación es acción de operador). Borrar los valores no deshace la exposición.
- [ ] Autorizar y proveer credenciales para la prueba real del crítico (B2).
- [ ] Plan 048, registry de enriquecimiento: mantener el etiquetado manual (cada 50 registros; eran 44 el 23-sep) y decidir al llegar a ≥200.
- [ ] Plan 084, texto alternativo con modelo de visión (solo hay spec): confirmar un modelo multimodal y fijar un presupuesto mensual de llamadas.
- [ ] Benchmark LLM con ranking ciego pendiente ([todo-llm-routing-benchmark](../todo-llm-routing-benchmark.md), 5 casillas abiertas, **sin reverificar**).
- [ ] Prueba en vivo del panel de publicación con `SERVING_RELOAD=0` ([todo-live-publication-progress](../todo-live-publication-progress.md)).
- [ ] Bluesky: crear la cuenta y definir `BLUESKY_DID` y `BLUESKY_PDS_URL`; además, `workflow_dispatch` con `mode=reconcile` no llega al CLI ([archive/social-distribution/todo.md](../archive/social-distribution/todo.md), 2 casillas abiertas).
- [ ] Copia de los respaldos fuera de la VM de OCI ([todo-oci-hosting-migration](../todo-oci-hosting-migration.md), opcional).

## 3. Planes abiertos del ledger (secundarios al gate)

| Plan | Título                                                                                  | Estado en el ledger                  | Casillas abiertas | Nota                                                                                                                                                 |
| ---- | --------------------------------------------------------------------------------------- | ------------------------------------ | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 191  | Pipeline editorial basado en evidencia                                                  | PARTIAL                              | 1                 | Ver B1                                                                                                                                               |
| 190  | Procesamiento editorial independiente de la imagen                                      | PARTIAL                              | 1                 | Ver B3                                                                                                                                               |
| 193  | Gate de seguridad de happy-dom del admin                                                | PARTIAL                              | n/a               | **Por verificar:** #389 (corrección de happy-dom) y #392 (preflight) ya están en `main`; probablemente la fila debe pasar a DONE                      |
| 188  | Evidencia de cierre de informes                                                         | TODO                                 | n/a               | P2. Reglas puras que exigen un intento de publicación COMPLETED y evento de despliegue                                                                |
| 060  | Fiabilidad y arquitectura de la publicación entre repositorios                          | IN_PROGRESS                          | 26 (+2 en fase 4c) | Programa grande por fases; el detalle está en [plans/060/todo.md](../plans/060/todo.md)                                                              |
| 048  | Registro de enriquecimiento curado                                                      | PARTIAL                              | 4                 | Depende del etiquetado manual (§2)                                                                                                                   |
| 117  | Evaluación de respaldo de fetch alojado                                                 | TODO (standby)                       | 5                 | Solo se ejecuta si una fuente derrota la escalera local completa (puerta de entrada en el spec)                                                       |
| 084  | Texto alternativo de portada con modelo de visión                                       | Sin fila (solo spec, por diseño)     | 13                | Depende de la decisión del titular (§2)                                                                                                              |

Casillas sin marcar en planes que el ledger da por DONE: 080 (3) y 108 (3). **Por verificar** y reconciliar.

## 4. Seguridad y deuda técnica

- [ ] **F-0024 (S2):** condición de carrera TOCTOU entre la comprobación de existencia y la escritura en `refinery_engine.py`. Mitigada en parte por B-01 y B-05; no tiene ítem propio. Es el único hallazgo abierto de la auditoría de marzo ([Findings_Ledger](audits/Findings_Ledger.md)).
- [ ] **Dependabot:** 2 alertas altas abiertas el 25-oct en `tools/editorial_eval/package-lock.json` (`@azure/msal-node` y `node-forge`). Corregir o justificar por escrito; no descartar solo para poner verde el panel.
- [ ] **Deuda técnica no crítica** (heredada de `docs/dev/BACKLOG.md`, ver [archivo](archive/backlogs/dev-BACKLOG.md)):
  - Deduplicar `CollectorArticleModel` (Pydantic) y `Article` (SQLAlchemy), que comparten ~90 % de los campos.
  - Unificar `PreScorer` y `BasicScorer` en un `ScoringService`.
  - Pruebas de contrato: generar el esquema de la salida del scraping para proteger a los consumidores (Refinery).
  - Migrar `serving/` a una estructura de `routers/`.

## 5. Casillas abiertas en registros por tarea (no reverificadas)

Estos pares `spec-*` y `todo-*` de la raíz son los registros de ejecución de tareas sueltas. Se conservan donde están. Las casillas abiertas de abajo son **probablemente obsoletas** en su mayoría (muchas son pasos de proceso como «abrir PR»); revisar antes de actuar.

| Registro                                                                                | Abiertas | Contenido                                                                  |
| --------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------- |
| [todo-internal-review-guardrails](../todo-internal-review-guardrails.md)               | 7        | Sin resumir                                                                |
| [todo-llm-routing-benchmark](../todo-llm-routing-benchmark.md)                         | 5        | Ver §2                                                                     |
| [todo-test-suite-audit](../todo-test-suite-audit.md)                                   | 5        | Sin resumir                                                                |
| [todo-llm-health-weights-fix](../todo-llm-health-weights-fix.md)                       | 3        | Sin resumir                                                                |
| [todo-admin-stack-ports](../todo-admin-stack-ports.md)                                 | 2        | Prueba e2e de la colisión de puertos; fusionar tras resolver hilos         |
| [todo-editorial-grounding](../todo-editorial-grounding.md)                             | 2        | Opcionales: conversión de unidades y `fact_check` con otro proveedor       |
| [todo-editorial-quality-lifts](../todo-editorial-quality-lifts.md)                     | 2        | Refrescar el inventario y abrir PR (pasos de proceso)                      |
| [todo-alt-text-nonblocking](../todo-alt-text-nonblocking.md)                           | 1        | Paso de proceso sobre el par spec/todo                                     |
| [todo-live-publication-progress](../todo-live-publication-progress.md)                 | 1        | Ver §2                                                                     |
| [todo-llm-canary](../todo-llm-canary.md)                                               | 1        | Opcional: ejecutar el canary en un workflow programado                     |
| [todo-llm-provider-chain](../todo-llm-provider-chain.md)                               | 1        | Fase 2 fuera de alcance: reordenar la cadena adaptativamente               |
| [todo-llm-run-report](../todo-llm-run-report.md)                                       | 1        | PR-C: verificación de anclaje editorial (primero como aviso)               |
| [todo-oci-hosting-migration](../todo-oci-hosting-migration.md)                         | 1        | Ver §2                                                                     |

**Registros con 0 casillas abiertas** (candidatos a archivar; propuesta, no ejecutada): todo, todo-admin-api-surface, todo-flaky-tests, todo-logs-warnings-concurrency, todo-nvidia-routing-fix, todo-refinery-gui, todo-refinery-gui-phase3, todo-refinery-gui-phase4, todo-refinery-gui-phase4-addendum-source-editor y todo-webhook-inbox-pull, cada uno con su par `spec-*`.
