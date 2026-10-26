# Plan 199 — titulares con gancho sin perder rigor

## Contexto (verificado 2026-10-26)

Los titulares de octubre se volvieron sosos por dos causas:

1. **Reescritura manual** (frontend PR #345, 2026-10-24): 8 titulares ya
   publicados se reescribieron metiendo la salvedad dentro del titular
   ("Shanidar A: una lesión compatible con una lanza, sin autor conocido" en
   lugar de "¿Fue herido a propósito o por accidente el neandertal de
   Shanidar?").
2. **Reglas del pipeline** (commit `fa7adb72`, 2026-10-22):
   - se eliminó "preservar la intención del titular original";
   - se exige conservar calificadores "en cada variante", titular incluido;
   - el crítico juzga las cuatro variantes juntas, su rechazo bloquea el
     artículo y sus instrucciones piden "reemplazar la formulación
     especulativa por una afirmación factual" (logs 2026-09-23 a 2026-10-12).

El rigor de esos cambios era correcto (por ejemplo, "Las sesiones largas de
eSports dañan tu espalda" afirmaba causalidad desde una encuesta); el error
fue resolverlo quitando el gancho.

## Objetivo

Que el pipeline produzca titulares que despierten interés y sigan siendo
fieles a la evidencia, y corregir los 8 titulares afectados.

Criterios de aceptación:

1. Prompt `headline`:
   - La incertidumbre se expresa **sin matar el gancho**: forma de pregunta,
     verbo prudente ("podría", "apunta a", "sugiere") o sujeto acotado ("en
     ratones"). El detalle de la salvedad va en `excerpt` y en el cuerpo.
   - Se recupera, matizada, la regla de aprovechar el ángulo del titular
     original cuando el cuerpo y la evidencia lo respaldan.
   - Se agrega una lista de "titular plano" a evitar (etiqueta + dos puntos +
     descripción técnica; negación como eje del titular; jerga sin anclaje) con
     pares antes/después reales.
2. Prompt `headline_critic`:
   - La fidelidad se juzga con rigor sobre `direct`; las variantes `question`
     y `benefit` solo se rechazan por afirmaciones falsas o sensacionalismo.
   - Una pregunta o un verbo prudente cuentan como incertidumbre conservada.
   - `regenerate_instruction` debe proponer una corrección que **conserve el
     gancho** (otro patrón o un matiz), nunca "sustituir por una afirmación
     factual" plana.
   - Esquema JSON sin cambios (el código lo valida).
3. Sin cambios de código ni de esquema; tests existentes en verde.
4. Frontend: PR con propuestas para los 8 titulares, cada una justificada
   frente al cuerpo, para revisión del titular antes de fusionar.

## Verificación

- `make test`, `make lint`, `make docs-check`.
- Revisión manual de los prompts resultantes.
- Prueba en vivo opcional: regenerar titulares de 2–3 artículos con el
  pipeline (no publica) y comparar.
