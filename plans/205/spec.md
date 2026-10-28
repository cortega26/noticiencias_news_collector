# Plan 205: Corrección automática tras la verificación de datos

**Prioridad:** P1 · **Esfuerzo:** M · **Depende de:** 060 Fase 2c (verificador
independiente), 200 (cadena de modelos por etapa)

## Problema

Desde el plan 060 Fase 2c, la etapa 7 (`_verify_fact_check_claims`) compara
cada afirmación de `fact_check` con el contenido original de la fuente usando
un modelo independiente del redactor. Si alguna afirmación resulta
`disputed`, `_enforce_fact_check_gate` lanza
`GeneratedArticleValidationError(error_code="editorial_fact_check_disputed")`
y el artículo queda detenido sin ningún paso posterior. El operador ve:

> No publicado (proceso 96): Error procesando artículo: Fact-check verification
> disputed the following claim(s) ... Publication blocked pending correction.

Ese estado obliga a una persona a decidir. El propietario quiere que el
pipeline resuelva solo y que la decisión final sea binaria:

1. **Se publica con las correcciones**, o
2. **No se publica**, porque los errores cambian radicalmente lo que afirma el
   titular y no tiene sentido publicarlo.

## Objetivos (criterios de aceptación)

- **A1.** Cuando el verificador marca afirmaciones como `disputed`, el
  pipeline evalúa la gravedad con el modelo verificador (independiente del
  redactor): ¿el error contradice el titular o la tesis central?
- **A2.** Si la gravedad es "afecta al titular", el artículo se rechaza de
  forma definitiva con `error_code="editorial_fact_check_unpublishable"` y un
  mensaje en español que dice qué afirmación contradice la fuente y por qué.
- **A3.** Si no afecta al titular, el redactor recibe la fuente, las
  afirmaciones contradichas y el motivo del verificador, y reescribe el
  artículo corrigiendo o eliminando solo esos datos, sin añadir datos nuevos.
- **A4.** Tras cada corrección se regeneran titulares (etapa 5) y campos de
  enriquecimiento (etapa 6) a partir del cuerpo corregido, se vuelven a
  verificar **todas** las afirmaciones nuevas y se comprueba con el
  verificador que el cuerpo corregido ya no sostiene ninguna afirmación
  contradicha anteriormente (control residual). Así, un `fact_check` nuevo
  que simplemente omita el dato erróneo no basta para aprobar.
- **A5.** Máximo `MAX_FACT_CHECK_CORRECTIONS = 2` intentos de corrección. Si
  quedan afirmaciones contradichas con veredictos definitivos, el artículo se
  rechaza de forma definitiva (`editorial_fact_check_unpublishable`).
- **A6.** Cuando no queda nada contradicho, el artículo continúa hacia la
  publicación con el cuerpo, los titulares y el `fact_check` corregidos. El
  cuerpo corregido reemplaza la caché de la etapa 2 para que una reanudación
  no recupere el texto erróneo.
- **A7.** Una falla de infraestructura que impide decidir (el juicio de
  gravedad no responde o responde mal, el redactor falla, el control residual
  no es concluyente en el último intento) **no** se convierte en un rechazo
  definitivo: conserva el bloqueo reintentable actual
  (`editorial_fact_check_disputed`) con un mensaje que lo explica. Un fallo de
  red nunca debe descartar un artículo correcto ni publicar uno erróneo.
- **A8.** La decisión queda registrada en las notas de trazabilidad
  (`grounding_notes`) y en `last_source_support_verdict["corrections"]`:
  afirmaciones contradichas, motivos, juicio de gravedad y número de intentos.
- **A9.** El contrato del frontend no cambia: los elementos de `fact_check`
  siguen siendo `{label, status}`. El motivo del verificador nunca entra en el
  frontmatter.
- **A10.** `_enforce_fact_check_gate` se mantiene como última defensa: si por
  cualquier camino llega un `disputed` a la etapa de artefacto, sigue
  bloqueando.

## Diseño

### Módulo nuevo de política: `news_collector/components/editorial/fact_check_correction.py`

Sin red ni E/S (ley de arquitectura: la política vive en módulos puros). Sigue
el patrón de `editorial_critic_gate.run_critic_gate`: un bucle tipado que
recibe "hooks" del `EditorAgent`.

```python
MAX_FACT_CHECK_CORRECTIONS = 2

@dataclass(frozen=True)
class DisputedClaim:
    label: str
    reason: str            # motivo del verificador ("" si no lo dio)

@dataclass(frozen=True)
class SeverityJudgement:
    headline_affected: bool | None   # None = no se pudo determinar
    reason: str

@dataclass(frozen=True)
class DerivedArticle:
    content: str
    headlines: dict[str, Any]
    enrichment_fields: dict[str, Any]

@dataclass(frozen=True)
class FactCheckCorrectionHooks:
    verify: Callable[[list[dict]], list[dict]]          # etapa 7 sobre claims
    reasons: Callable[[], dict[str, str]]               # motivos del último verify
    judge_severity: Callable[[list[DisputedClaim], dict[str, Any]], SeverityJudgement]
    correct: Callable[[str, list[DisputedClaim]], str]  # cuerpo corregido
    rederive: Callable[[str], DerivedArticle]           # etapas 5 y 6
    still_asserted: Callable[[str, DisputedClaim], bool | None]

@dataclass(frozen=True)
class FactCheckCorrectionOutcome:
    article: DerivedArticle
    verified_fact_check: list[dict]
    record: dict[str, Any]   # trazabilidad (A8)

def run_fact_check_correction(
    article: DerivedArticle,
    verified_fact_check: list[dict],
    hooks: FactCheckCorrectionHooks,
    *,
    max_corrections: int = MAX_FACT_CHECK_CORRECTIONS,
) -> FactCheckCorrectionOutcome
```

Algoritmo:

```
pendientes = disputed(verified)            # con motivos
historial  = {}                            # todas las afirmaciones contradichas vistas
si no hay pendientes -> devolver sin cambios (camino feliz, sin llamadas extra)
para intento en 0..max_corrections:
    gravedad = judge_severity(pendientes, titulares actuales)
    si gravedad.headline_affected es True  -> rechazo definitivo (A2)
    si gravedad.headline_affected es None  -> bloqueo reintentable (A7)
    si intento == max_corrections           -> rechazo definitivo (A5)
    cuerpo = correct(contenido, pendientes) (excepción -> bloqueo reintentable)
    articulo = rederive(cuerpo)
    verified = verify(articulo.enrichment_fields["fact_check"])
    pendientes = disputed(verified)
    para cada afirmación del historial no presente en pendientes:
        r = still_asserted(cuerpo, afirmación)
        True -> se añade a pendientes; None -> inconclusa
    si pendientes vacío:
        si hubo inconclusas -> bloqueo reintentable (A7)
        si no -> éxito (A6)
```

Las inconclusas del control residual se tratan con cautela: no permiten
publicar, pero tampoco producen un rechazo definitivo. Se vuelve a intentar en
la siguiente ejecución.

Errores: el módulo lanza `GeneratedArticleValidationError` (se importa de
`editorial_publication_artifact`, donde ya vive) con dos códigos:

- `editorial_fact_check_unpublishable`: decisión definitiva "no se publica".
- `editorial_fact_check_disputed`: no se pudo decidir por infraestructura;
  reintentable (mismo código que hoy, con un mensaje nuevo).

El rechazo definitivo ocurre **antes** de gastar intentos de corrección
cuando el titular está afectado. El juicio de gravedad se repite en cada
intento porque una corrección puede regenerar titulares nuevos y aparecer
afirmaciones contradichas nuevas.

### Cambios en `EditorAgent` (`ai_editor.py`)

1. `_verify_fact_check_claims` guarda el motivo del verificador en
   `self.last_fact_check_reasons: dict[str, str]` (por `label`), sin tocar los
   dicts de las afirmaciones (A9). El motivo se recorta a 500 caracteres.
2. `_judge_fact_check_severity(disputed, headlines, source_content,
   content_mode)` usa el prompt `fact_check_severity` a través de
   `_send_fact_check_prompt` (modelo verificador independiente). Si responde
   algo distinto de un booleano en `headline_affected`, o falla, devuelve
   `None`.
3. `_correct_disputed_claims(content, disputed, source_content, context)`
   usa el prompt `fact_check_correction` con el modelo redactor
   (`_send_prompt`, `self.editor_model`), limpia con
   `_extract_markdown_content`, exige cuerpo publicable y pasa la revisión
   técnica `_critic_pass` (igual que la reparación editorial). Si falla, lanza
   `GeneratedArticleValidationError("editorial_fact_check_disputed")`.
4. `_claim_still_asserted(content, claim)` usa el prompt
   `fact_check_residual` con el verificador; `{"still_asserted": bool}`;
   cualquier otra respuesta o error devuelve `None`.
5. En `prepare_article`, las etapas 5 y 6 pasan a una clausura
   `_derive_publishable(final_content) -> DerivedArticle` (mismo código,
   reutilizado por el bucle). Después de la etapa 7 se llama a
   `run_fact_check_correction`. Si hubo corrección, el cuerpo final se escribe
   en la caché de la etapa 2 (`_write_editorial_cache_if_valid`) y se borra el
   checkpoint técnico (`cache_s2_5`), que ya no corresponde al cuerpo.
6. `grounding_notes` añade la sección "Correcciones automáticas por
   verificación de respaldo" con el registro (A8).

Decisión: tras la corrección no se vuelve a ejecutar el crítico editorial
(etapa 4). La corrección cambia frases puntuales; volver a pasar el crítico
editorial podría activar su reparación y reintroducir el dato. La revisión
técnica (etapa 3) sí se ejecuta porque protege la integridad del texto
(traducción, truncado). En una reanudación, el crítico editorial vuelve a
evaluar el cuerpo corregido porque su checkpoint está ligado al hash del
contenido.

### Prompts nuevos (`config/prompts.yaml`)

- `fact_check_verification`: la salida pasa a ser
  `{"status": "...", "reason": "..."}`; `reason` es una frase breve que dice
  qué dice la fuente. Es compatible hacia atrás: sin `reason`, el motivo
  queda vacío.
- `fact_check_severity`: verificador. Entrada: titular, entradilla,
  afirmaciones contradichas con motivos y la fuente. Salida
  `{"headline_affected": bool, "reason": str}`. Criterio: `true` solo si el
  dato erróneo es lo que el titular o la entradilla prometen, o si sin él la
  noticia deja de sostenerse; los datos secundarios (cifras accesorias,
  detalles de método) son `false`.
- `fact_check_correction`: redactor. Corrige el dato según la fuente o
  elimina la frase si la fuente no da el dato correcto; no añade hechos
  nuevos; conserva el resto del texto, el formato y la voz; devuelve el
  artículo completo.
- `fact_check_residual`: verificador. Entrada: el artículo corregido y la
  afirmación. Salida `{"still_asserted": bool}`.

Cambiar `prompts.yaml` cambia `_cache_revision` y, por tanto, invalida una vez
las cachés editoriales existentes (comportamiento ya conocido y aceptado al
editar prompts).

## Fuera de alcance

- Cambiar el panel admin: ya muestra el texto de la excepción; los mensajes
  nuevos están escritos para leerse ahí.
- Marcar en la base de datos el artículo como descartado: hoy no existe ese
  estado editorial terminal y la decisión queda en `error_code` del intento.
- Cambiar el contrato del frontend.

## Verificación

| Qué | Cómo |
| --- | --- |
| Bucle puro, todas las ramas (A1–A7) | `tests/unit/editorial/test_fact_check_correction.py`: sin contradicciones (no llama a nada); titular afectado (rechazo, sin corrección); gravedad `None` (reintentable); corrección exitosa en el 1.er intento; corrección exitosa en el 2.º; persistente tras 2 intentos (rechazo); el control residual detecta el dato aún presente aunque el `fact_check` nuevo lo omita; residual inconcluso (reintentable); excepción del redactor (reintentable); el registro contiene intentos y motivos. |
| Integración en `process_article` | `tests/unit/editorial/test_fact_check_verification.py`: verificador `disputed` → gravedad `false` → corrección → `confirmed` → se publica con el cuerpo corregido y la caché de la etapa 2 queda reemplazada; gravedad `true` → `editorial_fact_check_unpublishable`; el test existente (todas las respuestas `disputed` sin `headline_affected`) sigue dando `editorial_fact_check_disputed`. |
| Motivos fuera del contrato | Test: los dicts de `fact_check` emitidos solo tienen `label` y `status`; `last_fact_check_reasons` guarda el motivo. |
| Prompts | Test: los cuatro prompts existen y declaran el formato de salida. |
| Regresión | `make test`, `make lint`, `make type`. |
