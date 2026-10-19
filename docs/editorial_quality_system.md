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
ni una prueba de plagio. El crítico conserva sus siete puntajes y añade un
veredicto separado de valor para el lector: `substantive` (síntesis útil),
`close_paraphrase` (paráfrasis cercana demostrable con muestra suficiente) o
`insufficient_source` (fuente insuficiente para juzgar). No se penaliza la
mera coincidencia temática ni se fuerza investigación o contexto inventado.
Un `close_paraphrase` válido impide la aprobación: cuando el modelo lo marca
reparable (el caso esperado), obliga a solicitar reescritura y, si el ciclo no
termina en un veredicto aprobatorio, `RefineryEngine._refine_article` detiene
la creación del PR con `E_EDITORIAL_VALUE_ADD`. Si el modelo lo marca
irreparable, no hay reescritura y la retención se aplica igual. Un fallo del
crítico al devolver un veredicto parseable es fail-open y no retiene; un fallo
del proveedor al reparar deja en pie el `close_paraphrase` y por eso sí
retiene. El resto de rechazos de calidad sigue siendo consultivo. El
checkpoint v3 obliga a revisar de nuevo los artículos que solo tenían
aprobación del crítico anterior.
Una aprobación de emergencia por falta de prompt o error de infraestructura
sigue permitiendo publicar, pero no se guarda como revisión superada; un
reanálisis posterior puede volver a intentarlo. Una aprobación del crítico
significa solo que ese modelo devolvió un veredicto válido según el umbral
configurado; no equivale a revisión humana, comprobación independiente ni
garantía de exactitud. Una falla técnica es fail-open para que la etapa siga,
pero no se registra como aprobación ni como checkpoint revisado.
Si el proveedor falla al reparar un rechazo de calidad de Stage 4, se conserva
el borrador original y la etapa continúa con una advertencia; tampoco se
registra una revisión superada. Esa continuación no aplica a un
`close_paraphrase`, que retiene como se explicó arriba. El crítico y su
reparación siguen siendo asesoría automática.

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

## Canary operacional del crítico editorial (Stage 4)

`scripts/editorial_critic_canary.py` es una herramienta de evidencia, no una
puerta. Envía un artículo claramente sintético por el crítico editorial real
(`EditorAgent._critic_editorial_pass`) y emite un único objeto JSON saneado con
sha de git, entorno, proveedor/modelo, resultado de transporte, parseo,
veredicto y latencia. No escribe base de datos, caché ni artefactos, y no
publica nada.

```bash
# Local (Ollama, sin costo; opción por defecto)
.venv/bin/python scripts/editorial_critic_canary.py --provider local

# Nube (cadena configurada de la app; puede costar dinero)
.venv/bin/python scripts/editorial_critic_canary.py --provider configured --require-keys
```

Qué prueba: que el proveedor responde y devuelve un veredicto que el parser real
acepta, y cuál es la decisión del crítico. Qué **no** prueba: la calidad del
artículo, la publicación, ni que una falla técnica equivalga a una aprobación.

Códigos de salida: `0` PASS, `1` FAIL (veredicto válido que rechaza el
artículo), `2` UNVERIFIED (fallo de transporte, de parseo o interno) y `3` error
de configuración (por ejemplo, `--require-keys` sin credenciales). `UNVERIFIED`
nunca debe leerse como aprobación: el crítico falla abierto para no bloquear por
infraestructura y el canary distingue explícitamente ese caso. No está conectado
a CI ni al Makefile (la disponibilidad y el costo del proveedor no son estables
en CI); ejecutarlo contra la nube es una decisión manual del operador.

