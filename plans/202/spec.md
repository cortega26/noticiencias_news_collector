# Plan 202: imágenes de portada atractivas y generación automática

## Contexto

- El objetivo es publicar un artículo al día durante 4 semanas. Hoy el cuello
  de botella es la imagen: cada artículo sin imagen reutilizable queda en
  `waiting_for_image` hasta que alguien genera una a mano.
- El prompt v1 (`editorial_image_prompt_v1.md`) produce imágenes correctas
  pero genéricas. Sus causas:
  1. Toma la información de la fuente cruda en inglés y no del artículo
     editado. La "escena a representar" es la primera frase del resumen (una
     afirmación, no algo que se pueda ver).
  2. El dominio sale de la categoría del sitio: Marte quedó como `technology`.
  3. Repite en todos los encargos advertencias genéricas (arqueología,
     biosignaturas, beneficios clínicos), sin importar el tema.
  4. Se contradice: pide una ilustración conceptual y, a la vez, realismo
     fotográfico; pide un diagrama y, a la vez, que no haya rótulos.
  5. Tiene unas 25 prohibiciones genéricas que diluyen la dirección.
  6. Resultado: la imagen de la malaria tiene el aspecto genérico de render
     3D brillante; la nube de Marte ocupa una franja pequeña y no se distingue
     en una miniatura.

## Fase 1: dirección de arte (prompt v2)

- Paso nuevo `image_art_director.direct_art`, con su propia cadena de LLM
  (`purpose="image_brief"`). Lee el artículo editado en español (titular,
  bajada, puntos clave, glosario, nota de incertidumbre y cuerpo).
- Propone 3 ideas visuales, las puntúa (miniatura, fidelidad, originalidad) y
  desarrolla la mejor en un `ArtDirection` validado: idea, sujeto, entorno,
  estilo, composición, luz y paleta, notas de precisión, cosas que evitar y
  texto alternativo en español.
- Tres estilos fijos de la casa (`photo_editorial`, `scientific_illustration`,
  `conceptual_still_life`), para una identidad visual reconocible.
- Zona segura: el sitio recorta a 16:9, 16:10, 4:3 y 1:1. El sujeto queda
  completo en la mitad central del ancho.
- `render_prompt` arma un prompt corto y en positivo, con una sola línea de
  exclusiones universales (texto, logos, marcas de agua).
- Si la dirección de arte falla, se usa el prompt v1 y la espera sigue como hoy.
- **Puerta de calidad:** comparación lado a lado en 4 artículos reales
  (malaria, Marte, neandertal y coral). El propietario aprueba antes de la
  fase 2.

## Fase 2: generación automática (tras la aprobación)

- Generador que, para cada checkpoint en `waiting_for_image`, aplica la
  dirección de arte, ejecuta `codex exec` (imagegen, cuenta de ChatGPT) en
  una carpeta temporal aislada con un límite de 15 minutos, valida la imagen
  (formato, 16:9 y al menos 1200 px de ancho) y la registra con
  `stage_upload(image_origin="ai_generated")` y el texto alternativo
  generado. El reconciliador existente reanuda la publicación.
- Como máximo 2 generaciones por artículo, para proteger el cupo del plan.
  Si falla, el artículo sigue esperando y aparece en el admin.
- Se activa con un ajuste en `config.toml` (desactivado por defecto).
- Los campos v1 de encargos existentes no se reutilizan; `prompt_version`
  pasa a v2.

## Verificación

- Tests de `image_art_director` (análisis, validación, contexto y prompt).
- Comparación de las 4 imágenes, aprobada por el propietario.
- Fase 2: tests del generador con Codex simulado; E2E con un artículo real.
