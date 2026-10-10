# Sistema de Calidad Editorial y Auditoría

Este documento describe el sistema de control de calidad editorial implementado en Noticiencias para evaluar el rigor epistémico y la claridad de los artículos generados por IA.

## Componentes

### 1. Filtros Epistémicos (Editor)

El prompt del Editor ha sido actualizado para imponer distinciones estrictas entre:

- **Evidencia Directa**: Lo que el estudio observó realmente (ej. en ratones, en células, en humanos).
- **Inferencia**: La interpretación de los autores.
- **Especulación**: Posibles implicaciones futuras.

**Reglas Clave:**

- Si un estudio es preclínico (animales/células), debe mencionarse explícitamente.
- Se prohíbe el lenguaje terapéutico absolutista ("cura", "prueba") sin ensayos clínicos fase 3.

Desde 2026-10-09, el crítico editorial de Stage 4 también compara el borrador
con una muestra representativa y acotada del título y contenido original,
cuando están disponibles. Recibe además `content_mode`, para distinguir texto
completo de resumen o fallback. Los textos fuente se delimitan como datos no
confiables y el mensaje de sistema indica al modelo que ignore instrucciones
que aparezcan dentro de ellos. Esta es una mitigación de *prompt injection*,
no una garantía de que un modelo nunca siga instrucciones maliciosas. La
revisión busca ampliaciones no respaldadas,
experiencias personales atribuidas a la voz equivocada y paráfrasis cercana
sin utilidad adicional clara; no exige entrevistas ni contexto inventado.
La muestra puede ser parcial y no constituye una verificación independiente
ni una prueba de plagio. El crítico conserva sus siete puntajes y su ciclo
limitado de reparación; agotado este, el resultado sigue siendo consultivo y
no bloquea por sí solo la publicación. El checkpoint versionado obliga a
revisar de nuevo los artículos que solo tenían aprobación del crítico previo.
Una aprobación de emergencia por falta de prompt o error de infraestructura
sigue permitiendo publicar, pero no se guarda como revisión superada; un
reanálisis posterior puede volver a intentarlo. Una aprobación del crítico
significa solo que ese modelo devolvió un veredicto válido según el umbral
configurado; no equivale a revisión humana, comprobación independiente ni
garantía de exactitud. Una falla técnica es fail-open para que la etapa siga,
pero no se registra como aprobación ni como checkpoint revisado.
Si el proveedor falla al reparar un rechazo de Stage 4, se conserva el borrador
original y la etapa continúa con una advertencia; tampoco se registra una
revisión superada. El crítico y su reparación siguen siendo asesoría automática.

### 2. Auditor Editorial (Lightweight Auditor)

Es un componente no bloqueante que audita una muestra de artículos para verificar el cumplimiento de las normas editoriales.

**Configuración (`config.toml`):**

```toml
[editorial_auditor]
enabled = true
sampling_rate = 0.2  # 20% de los artículos
blocking = false     # No detiene la publicación si falla la auditoría
```

**Triggers de Ejecución:**
El auditor se ejecuta si:

1. La categoría es Salud, Medicina o Biología.
2. El contenido contiene palabras clave sensibles ("cura", "tratamiento", "terapia", "fármaco").
3. Por muestreo aleatorio (definido por `sampling_rate`).

**Output:**
El auditor genera un puntaje y un reporte JSON almacenado en `data/article_metadata/{id}/auditor_score.json`.

### 3. Sistema de Puntaje (Scoring)

Se rastrean las siguientes métricas:

- `epistemic_rigor_score`: (0-10) Distinción entre hechos y especulación.
- `clarity_score`: (0-10) Claridad y estructura.
- `speculation_control_score`: (0-10) Manejo de afirmaciones futuras/terapéuticas.
- `engagement_score`: (0-10) Interés narrativo.

Los promedios móviles se guardan en `data/article_metadata/auditor_rolling_average.json`.

## Flujo de Trabajo

1. **Refinery Engine** procesa el artículo (Traducción -> Edición).
2. Se genera el contenido refinado.
3. Los controles previos al PR incluyen el crítico y la verificación de afirmaciones.
4. Se crea el PR. El auditor opcional se envía después, si corresponde por sus triggers.
5. El auditor guarda resultados y estado en disco. Con `blocking = false`, sus
   puntuaciones en caché son informativas y no bloquean reintentos; con bloqueo
   explícito se aplican los controles descritos en `docs/EDITORIAL_MODES.md`.

Los archivos de auditoría son artefactos bajo el directorio de datos configurado,
no una prueba de publicación en la web. `audit_unavailable` o `audit_failed`
no deben confundirse con una puntuación válida. El prompt expresa criterios
editoriales; no garantiza por sí solo que el texto generado los cumpla.

## Mantenimiento

- Los prompts del auditor están en `config/prompts.yaml`.
- La lógica de triggers y muestreo está en `news_collector/components/editorial/auditor.py`.
