# Spec — Social Distribution (paquete 1: contrato social + stamping editorial)

> Fuente maestra: `SOCIAL_DISTRIBUTION_IMPLEMENTATION_PLAN.md` (investigación 2026-09-05),
> §8 (identidad y detección), §9 (contrato de frontmatter), §25 (plan archivo por archivo),
> §26 pasos 1–3 (checklist ordenada).
>
> Alcance de este paquete: **solo** el contrato social cruzado (Zod + Pydantic + snapshot)
> y la asignación/preservación determinista de la decisión editorial al escribir Markdown.
> **Fuera de alcance en este paquete:** `social-manifest.json`, metadata X en `buildHead`,
> `dist-sanity`, publisher, proveedores (Buffer/Bluesky), workflows, runbook, DNS, rollout.

## 0. Estado del workspace al iniciar (paso 1 de §26)

Capturado antes de cualquier edición. No se sobrescribe trabajo ajeno (plan 081 en curso
en ambos repos, ramas `advisor/*`).

| Repo | Ruta | Rama | HEAD | Árbol |
|---|---|---|---|---|
| Frontend | `noticiencias` | `advisor/011-noticiencias-perf` | `790ce629445252fd86ef02052c0674c42edf2c69` | 11 archivos de docs modificados (plan 081) — no tocar |
| Backend | `noticiencias_news_collector` | `advisor/002-env-hygiene` | `e97b61511b60c3cf66e97b1e01db4430e421a76b` | ~70 archivos de docs/context modificados + `plans/080`, `plans/081` sin trackear (plan 081) — no tocar |

Reglas de preservación aplicadas:
- No `prettier --write .` / `lint-fix` / `black` global (reformatearía ediciones sin commit).
- No `git stash`; inspección de HEAD con `git show HEAD:<path>`.
- No cambio de rama; los cambios de este paquete se agregan al árbol actual, sin commit.
- No se toca `data/exports/latest_articles.json` ni ningún `context/modules/*.md`.

## 1. Objetivos y criterios de aceptación

1. `AstroPost` (backend) y `src/content.config.ts` (frontend) aceptan un objeto
   `social` **opcional, no nullable**, con exactamente las claves `publish` (bool
   estricto, default `false`) e `id` (string, `^[0-9a-f]{64}$`, opcional; obligatorio
   y no vacío cuando `publish` es `true`; validado también si `publish` es `false`).
   Claves extra dentro de `social` son error. `social: {}`, `social: {publish:false}`
   y ausencia son válidos. `social: null` es inválido. — §9
2. `npm run check:contract-sync` (modo `--strict`) pasa con el snapshot regenerado.
   El parser reconoce `social` y `SocialConfig`/objeto inline `social` como modelos
   anidados equivalentes (mismos nombres de campo, tipos, opcionalidad, defaults).
3. El corpus histórico completo sigue validando sin cambios (`astro check`,
   `check:editorial-fields`, tests BE de contrato). Ningún artículo existente gana
   `social` de forma automática. **No hay backfill.**
4. Adaptador puro `contracts/social_publication.py`:
   - Reintento / cambio de título ⇒ mismo `social.id`.
   - Archivo anterior con `social` (incluido `publish:false`) ⇒ se preserva **exacto**.
   - Archivo anterior **sin** `social` ⇒ se conserva la ausencia.
   - Archivo nuevo con `source_url` válida ⇒ `social = {publish:true, id:<hash>}`.
   - Archivo nuevo sin `source_url` ⇒ `social = {publish:false}` (opt-in editorial manual).
   - Cualquier `social` producido por el LLM se descarta: el LLM no decide autorización.
5. `target_repo_writer.write_article` aplica el adaptador en el límite que escribe
   Markdown: lee el archivo destino anterior si existe, parsea frontmatter
   generado/anterior, llama al adaptador y reserializa **solo** el frontmatter
   preservando el cuerpo byte a byte. YAML anterior ilegible/no parseable **bloquea**
   la escritura (no se interpreta como archivo nuevo).
6. El cuerpo "golden" no cambia; `refinery_manifest.json`, pruning y firmas siguen igual.

## 2. Identidad social (`social.id`) — §8

`social.id` = SHA-256 hex minúscula (64 chars) de los bytes UTF-8 de:

```
"noticiencias.com/social/v1\n" + NFC(strip(source_url_string))
```

- `source_url_string` es **la cadena `source_url` tal como aparece en el frontmatter
  generado** (la URL guardada), no se siguen redirects ni se eliminan parámetros.
  Decisión explícita (LAW-B5): al momento del stamping esa cadena ya viene
  normalizada por Pydantic `HttpUrl.__str__` aguas arriba (host en minúscula,
  `/` final en host desnudo). Usar la representación del frontmatter mantiene la
  derivación autoconsistente: regenerar el mismo archivo produce el mismo string y
  el mismo `id`. La estabilidad ante reintentos ya está garantizada además por la
  ruta de preservación (si un intento previo escribió el archivo, la derivación
  nunca corre).
- `strip` = recorte de whitespace en extremos. `NFC` = `unicodedata.normalize("NFC", …)`.
- **Puerta de activación (revisión 2026-09-06).** La derivación solo corre si
  `source_url` es una cadena sin whitespace interno que `urllib.parse.urlsplit`
  resuelve a esquema `http`/`https` **y host no vacío**. Un prefijo `startswith`
  no basta: `"http://"` empieza por el esquema y no tiene host, y hashearlo
  estamparía `publish: true` sobre basura. La comprobación es estructural; no se
  resuelve DNS ni se sigue ningún redirect. Sin host ⇒ `publish: false`.
- La caja del esquema **no** forma parte de la validación (`HTTPS://…` se acepta):
  `source_url` ya viene normalizada por `pydantic.HttpUrl` aguas arriba y la
  identidad hashea la cadena almacenada tal cual.
- **Colisión por diseño:** dos artículos con la misma `source_url` obtienen el
  mismo `social.id`. Es intencional (identidad = fuente), pero significa que el
  rechazo de IDs duplicados en el manifiesto (§20.3 del plan, paquete 4) es la
  única defensa contra una colisión en el ledger.
- Contenido manual sin `source_url`: el editor genera la identidad **una sola vez**
  (SHA-256 de `"noticiencias.com/social/v1\nmanual\n" + uuid4()` en minúscula) y la
  fija en el frontmatter entre comillas. Esa acción es editorial y **no** forma
  parte de este paquete; el adaptador solo deja `publish:false` para nuevos sin fuente.

## 3. Cambios de implementación

### 3.1 `news_collector/contracts/frontend_schema.py` (MODIFY)

- Nuevo modelo `SocialConfig(BaseModel)`:
  - `model_config = ConfigDict(extra="forbid")`.
  - `publish: bool = Field(default=False)` + `@field_validator("publish", mode="before")`
    que rechaza cualquier valor cuyo tipo no sea `bool` (bloquea `"true"`, `0`, `1`,
    `None`). Se anota `bool` (no `StrictBool`) para que el parser de
    `check-contract-sync` reconozca el tipo (no entiende `StrictBool`).
  - `id: Optional[str] = Field(default=None, pattern=SOCIAL_ID_PATTERN)` con
    `SOCIAL_ID_PATTERN = r"^[0-9a-f]{64}$"`.
  - `@model_validator(mode="after")` — si `publish` es `True`, `id` debe ser string
    no vacío que cumpla el patrón. Si `publish` es `False` e `id` viene, el patrón
    del `Field` ya lo valida.
- `AstroPost`: nuevo campo `social: Optional[SocialConfig] = None`.
  - Distinción ausencia vs `null` explícito: `@field_validator("social", mode="before")`
    que rechaza `None` **solo cuando la clave estuvo presente** en la entrada. Se
    implementa con un validador `mode="before"` sobre `social` que recibe el valor
    crudo: si es `None` se lanza `ValueError` (Astro/Zod tampoco acepta `null`).
    La ausencia total de la clave nunca llega al validador ⇒ queda `None` por default.
  - No se altera el tratamiento global de extras de `AstroPost` (sigue ignorando).
- Sin bump de `SCHEMA_VERSION` (extensión compatible y opcional).

### 3.2 `news_collector/contracts/social_publication.py` (CREATE)

Módulo adaptador bajo `contracts/` (LAW-B2: "clearly named adapter module under
`contracts/`"). Puro: sin I/O de red, sin sesiones DB, sin imports de orquestación.

API:

```python
SOCIAL_ID_PATTERN: str                       # ^[0-9a-f]{64}$
SOCIAL_ID_RE: re.Pattern             # anclado con `\Z`, no `$` — ver nota abajo

# Nota (revisión 2026-09-06): `SOCIAL_ID_RE` se compila reemplazando `$` por
# `\Z`. El `re` de Python deja que `$` empate antes de un `\n` final, mientras
# que Pydantic (rust-regex) y el `RegExp.test` de Zod anclan a fin de entrada.
# Como el símbolo está en `__all__` y lo consumirán los paquetes 2/4 (manifiesto,
# ledger), no puede ser más permisivo que los dos contratos de esquema.

def derive_social_id(source_url: str) -> str
    # sha256(b"noticiencias.com/social/v1\n" + NFC(strip(source_url)).encode()).hexdigest()

def apply_social_decision(
    *,
    generated_frontmatter: Mapping[str, Any],
    previous_frontmatter: Mapping[str, Any] | None,   # None ⇔ no existe archivo previo
) -> dict[str, Any]
    # Devuelve un nuevo dict de frontmatter (copia superficial + clave `social`
    # resuelta). No muta las entradas. No escribe archivos ni resuelve rutas.

def stamp_social_frontmatter(
    generated_content: str,
    previous_content: str | None,
) -> str
    # Split determinista `---\n<fm>\n---<rest>` con la misma convención que
    # refinery_engine._has_quoted_date_only_frontmatter (`content.find("\n---", 4)`).
    # ORDEN (revisión 2026-09-06): previous_content se valida PRIMERO, antes de
    #   cualquier early-return del lado generado. Al revés, el único caso con
    #   ambos lados rotos (previo corrupto + generado sin fence o con YAML
    #   inválido) saltaba el guard y sobrescribía en silencio una decisión
    #   editorial guardada.
    # - previous_content presente pero sin frontmatter dict parseable ⇒ ValueError.
    # - generated_content sin frontmatter parseable ⇒ se devuelve intacto
    #   (no es tarea del stamping arreglar contenido inválido).
    #   Residual conocido y aceptado: con un previo VÁLIDO que tiene
    #   `social: {publish:false}` y un generado con YAML inválido, la decisión se
    #   pierde en el archivo escrito. Inalcanzable desde `ai_editor` (su propio
    #   safe_dump no puede emitir YAML inválido) y contenido por
    #   `validate_post_frontmatter_fast` ⇒ `persist_attempt(False)` ⇒ sin commit,
    #   así que el clobber nunca sale del clon efímero. No se añade un guard más:
    #   lanzar sobre contenido generado inválido metería reparación editorial en
    #   el adaptador, que su docstring descarta explícitamente.
    # - Si apply_social_decision no cambia el frontmatter ⇒ se devuelve
    #   generated_content intacto (bytes idénticos).
    # - Si cambia ⇒ se reserializa SOLO el frontmatter con
    #   yaml.safe_dump(..., allow_unicode=True, default_flow_style=False,
    #                   sort_keys=False, width=1000) y se reensambla
    #   "---\n" + nuevo_yaml + "\n---" + rest  (rest byte a byte, incluye el
    #   comentario de identidad de fuente que vive tras el frontmatter).
```

Reglas de `apply_social_decision`:

| previous | `source_url` en generated | Resultado `social` |
|---|---|---|
| `None` (nuevo) | `urlsplit` ⇒ esquema http/https **y host no vacío** | `{"publish": True, "id": derive_social_id(url)}` |
| `None` (nuevo) | ausente / no-str / con whitespace / sin host / otro esquema | `{"publish": False}` |
| dict con `social` no nulo | — | copia profunda de `previous["social"]` |
| dict con `social: null` | — | se elimina `social` (valor inválido en ambos esquemas; nunca se reactiva) |
| dict sin `social` | — | se elimina `social` del resultado (preserva ausencia) |

En todos los casos se descarta primero cualquier `social` de `generated_frontmatter`.

### 3.3 `news_collector/logic/workflows/target_repo_writer.py` (MODIFY)

`write_article`, tras el guard de path-traversal y **antes** de `write_text`:

```python
previous_content = None
if target_file_path.exists():
    try:
        previous_content = target_file_path.read_text(encoding="utf-8")
    except OSError as err:
        raise ValueError(f"cannot read previous target file {target_file_path}: {err}") from err
content = stamp_social_frontmatter(content, previous_content)   # puede lanzar ValueError
```

- `refinery_engine.py:589` ya captura `ValueError` de `write_article` y registra
  `file_written: False` ⇒ integra sin cambio en el llamador.
- `except Exception: pass` prohibido; los errores se propagan como `ValueError`.
- Manifest / pruning / firma / retorno intactos.

### 3.4 `.contract-snapshots/frontend_schema.snapshot.json` (FE, MODIFY regenerado)

`npm run sync:contract-snapshot` contra el `frontend_schema.py` actualizado. No se
edita el IR a mano.

### 3.5 `src/content.config.ts` (FE, MODIFY)

```ts
const SOCIAL_ID_RE = /^[0-9a-f]{64}$/;   // módulo, fuera del cuerpo del objeto
// dentro de z.object({ ... }):
social: z
  .object({
    publish: z.boolean().default(false),
    id: z.string().regex(SOCIAL_ID_RE, 'social.id must be 64 lowercase hex chars').optional(),
  })
  .strict()
  .optional(),
```

La regla cruzada "`id` obligatorio y no vacío cuando `publish` es `true`" se agrega
al `.superRefine()` **de nivel superior existente** (donde ya viven image_alt /
featured_rank / enrichment v2), con `path: ['social', 'id']`. Así `social` queda
como objeto plano trivialmente parseable por `check-contract-sync` (sin
`ZodEffects`). `z.boolean().default(false)` ya rechaza `'true'`, `1` y `null`.

## 4. Verificación

### Backend (`make` desde `noticiencias_news_collector/`)

```
make lint
make type
make test
make test-contracts
make test-boundaries
make quality           # clase Critical: identidad de publicación + contrato
make docs-check         # contracts/ tocado ⇒ doc activo en el mismo PR
```

Tests dirigidos:
- `pytest tests/unit/contracts/test_frontend_schema.py -q`
- `pytest tests/unit/contracts/test_social_publication.py -q`  (nuevo)
- `pytest tests/decompose_refinery/test_target_repo_writer.py -q`

### Frontend (`npm` desde `noticiencias/`)

```
npm run test:audit -- tests/social
npm run test:audit -- tests/content-config-schema tests/contract-sync
npm run check:contract-sync
npm run validate:content     # astro sync && astro check ⇒ corpus completo revalida
npm run check:doc-drift
```

### Casos cubiertos por tests (§20.1–2)

Contrato (FE `tests/social/contract.test.ts` + BE `test_frontend_schema.py`):
frontmatter sin `social`; `{}`; `{publish:false}`; `{publish:true, id:<64hex>}`;
`publish:'true'` (string) ⇒ falla; `publish:1` / `0` ⇒ falla; `publish:true` sin `id`
⇒ falla; `id` corto / con mayúsculas ⇒ falla; `id` válido con `publish:false` ⇒ ok;
clave desconocida en `social` ⇒ falla; `social: null` ⇒ falla; IR del snapshot
contiene `SocialConfig`/`social` con campos `publish`,`id`.

Adaptador (`test_social_publication.py`): nuevo con fuente ⇒ id determinista;
reintento mismo `source_url` ⇒ mismo id; título distinto ⇒ mismo id; fuente NFC vs
NFD equivalentes ⇒ mismo id; fuente con espacios en extremos ⇒ mismo id; nuevo sin
fuente ⇒ `{publish:false}` sin id; anterior `{publish:false}` ⇒ preservado;
anterior `{publish:true,id:X}` ⇒ preservado; anterior sin `social` ⇒ ausencia
preservada; `social` del LLM en generated ⇒ descartado; vector de hash independiente
(bytes conocidos) para no fijar un hash arbitrario.

Writer (`test_target_repo_writer.py`): archivo nuevo con `source_url` ⇒ obtiene
`social` y `publish:true`; archivo nuevo sin fuente ⇒ `publish:false`; reescritura
conserva `id` / `false` / ausencia y **cuerpo idéntico**; YAML previo inválido ⇒
`ValueError`, archivo no sobrescrito; error de lectura ⇒ `ValueError`;
pruning/manifest siguen; salida reserializada pasa `validate_post_frontmatter_fast`
y no dispara `_has_quoted_date_only_frontmatter`.

## 5. Invariantes / riesgos

- **LAW-B5**: `social.id` es determinista desde `source_url` persistida; runtime clock,
  orden y aleatoriedad no lo afectan. Cambio de identidad ⇒ plan explícito (este spec).
- **LAW-B2**: la decisión vive en un adaptador de `contracts/`; es derivación
  determinista + preservación, no juicio editorial ni scoring.
- **No backfill**: ausencia de `social` deshabilita distribución; correcciones de
  archivos antiguos sin el campo conservan la ausencia.
- **Reserialización**: solo cuando el adaptador cambia algo ⇒ la ruta
  "archivo existente, social sin cambio" queda byte a byte idéntica. Cuando cambia,
  las demás claves hacen round-trip YAML con los kwargs exactos del editor.
  Verificado: `yaml.safe_load ∘ yaml.safe_dump` (mismos kwargs) es idempotente
  sobre la salida real del editor, incluyendo un documento v2 completo (listas de
  dicts, strings largos, `date` nativa). Un archivo publicado que fue **editado a
  mano** con otro formateador YAML (p. ej. auditorías del plan 060: comillas y
  sangría de listas distintas) SÍ se reformatearía si se reserializa; en la ruta
  de producción eso no ocurre porque `write_article` siempre recibe salida fresca
  del editor, y el archivo anterior solo se **lee** (para su `social`), nunca se
  reserializa. Acoplamiento anotado: si el editor cambia sus kwargs de
  `yaml.safe_dump`, hay que actualizar `_dump_frontmatter` (comentado en el código).
- **Riesgo**: el editor (`ai_editor.py`) NO construye `AstroPost(**llm_dict)` — arma
  `model_dict` con campos calculados explícitamente y nunca añade `social`. Por eso
  agregar `social` a `AstroPost` no habilita al LLM ni rompe el gate del editor.
  (Verificado: `ai_editor.py` ~2366–2500; el `except ValidationError` de esa zona
  no tiene un `AstroPost(...)` asociado vigente.) Si esa construcción cambiara en el
  futuro para pasar JSON crudo del LLM, habría que descartar `social` antes de
  construir — anotado como riesgo, sin cambio de código en este paquete.

## 6. Bloqueos pendientes / notas para paquetes siguientes

- **Nada bloquea este paquete.** Los pasos 4+ de §26 (manifest, publisher,
  proveedores, workflows, cuentas Buffer/Bluesky, DNS) siguen fuera de alcance.
- **`create_branch` (github_publisher.py:247)** — la garantía "reintento en la
  rama de PR conserva `publish:false` puesto por el editor" (§8/§9) se cumple
  **solo si** la edición del editor está commiteada/pusheada a la rama
  `content/update-<slug>`: en ese caso `create_branch` hace
  `checkout -B <branch> origin/<branch>` + `rebase`, y `write_article` lee el
  archivo con esa edición. Si la rama remota no existe, resetea a `origin/<base>`
  (main) y solo se preservan decisiones ya mergeadas a main. Edición local sin
  push no está cubierta (flujo editorial no habitual).
- **Doc de contratos (paso 11)** — `docs/PIPELINE_CONTRACTS.md` debería documentar
  el campo `social`. `make docs-check` está verde sin ese cambio, y ese archivo
  está en edición sin commit por el plan 081; se deja para el paso 11 / operador
  para evitar colisión.
- **`make quality` completo** — no terminó en la sesión (semgrep + pip-audit con
  red). `lint`, `type` (mypy full, exit 0) y `bandit` (archivos nuevos) verdes por
  separado; sin dependencias nuevas ⇒ `pip-audit` no tiene nada nuevo que revisar.
- **`test:audit` FE** tiene 1 fallo PREEXISTENTE (`check-doc-drift.test.ts`) por
  refs `npm run typecheck` en docs sin commitear del plan 081. Ajeno a este paquete.
