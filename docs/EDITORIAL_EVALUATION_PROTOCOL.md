# Protocolo para evaluar calidad editorial

## Propósito y estado

Este protocolo sirve para medir el comportamiento editorial actual con revisión
humana reproducible. Los pesos de scoring permanecen congelados hasta completar
una comparación pareada con evidencia suficiente. El protocolo no convierte
una salida de LLM en una etiqueta humana ni en consenso.

`tests/data/editorial_eval_seed.jsonl` es una semilla de diez casos sintéticos,
pendientes de revisión humana. Los casos codifican clases de error ya
documentadas, como atribución de testimonios y extrapolación de resultados
preclínicos. No son reproducciones de artículos reales ni constituyen un corpus
etiquetado, una evaluación ejecutada o evidencia de desempeño.

## Unidad y dimensiones de revisión

La unidad es un paquete versionado que contiene el texto fuente disponible, el
modo de contenido que recibió el sistema, el borrador producido y la versión de
los prompts, modelos y configuración editorial. Cada revisor evalúa por
separado:

1. **Atribución:** quién observó, dijo, concluyó o realizó cada acción; marcar
   atribución correcta, incorrecta, ambigua o no aplicable.
2. **Alcance de evidencia:** si el borrador conserva población, modelo,
   contexto y límites de la fuente; marcar respaldado, ampliado sin respaldo o
   insuficiente para juzgar.
3. **Cifras y magnitud:** si números, proporciones, duración y unidades son
   fieles, conversiones equivalentes, no respaldadas o imposibles de verificar.
4. **Certeza y causalidad:** si mantiene el grado de incertidumbre, asociación
   frente a causalidad y estado de publicación de la fuente.
5. **Decisión editorial:** aceptar, corrección menor, corrección sustantiva o
   abstenerse por falta de fuente suficiente.

La decisión general no reemplaza las dimensiones. Un caso con texto fuente
parcial puede ser `abstenerse` aunque el borrador parezca plausible.

## Muestra y selección

Para el primer piloto, congelar 30 paquetes antes de revisar resultados: 15
seleccionados al azar de publicaciones recientes y 15 seleccionados por riesgo
editorial (salud/ciencia preclínica, cifras o magnitudes, testimonios y fuentes
con texto parcial). Guardar el método, fecha de corte, lista de identificadores,
modo de fuente y SHA-256 de cada paquete. Evitar duplicados del mismo artículo,
fuente o evento entre divisiones.

Mantener la semilla sintética como conjunto de desarrollo. No mezclarla con los
30 paquetes publicados ni presentarla como estimación de calidad de producción.
Si una fuente original no puede conservarse o verificarse, registrar esa
limitación y no asignar una etiqueta de contenido como si la evidencia estuviera
disponible.

## Etiquetado y desacuerdos

- Dos personas revisan cada paquete independientemente, sin ver puntajes,
  recomendaciones ni etiquetas de LLM durante la primera ronda.
- Registrar las dos etiquetas humanas con identificador de revisor, fecha y
  justificación breve vinculada a una frase del paquete.
- Un tercer revisor adjudica los desacuerdos sustantivos y conserva ambas
  etiquetas iniciales. La etiqueta adjudicada se guarda en otro campo.
- Los resultados automáticos se guardan aparte, con proveedor/modelo, versión,
  fecha, prompt y salida estructurada. Nunca se copian a campos humanos ni se
  cuentan como un voto adicional.
- Publicar acuerdo por dimensión, desacuerdos y ejemplos adjudicados. Con esta
  muestra pequeña, las métricas de acuerdo son descriptivas y no demuestran
  consenso general.

El esquema de la semilla reserva `human_review` y `automatic_assessments` como
campos separados. `design_target` solo documenta por qué se incluyó el caso;
no es una respuesta correcta ni una etiqueta de referencia.

## Evaluar el comportamiento actual

1. Congelar código, configuración, prompts y corpus por SHA antes de ejecutar.
2. Ejecutar el flujo editorial actual una vez por paquete y guardar el borrador,
   advertencias, modo de fuente, decisiones deterministas y salida automática.
3. Completar primero las dos revisiones humanas a ciegas y luego comparar las
   salidas actuales con las etiquetas adjudicadas.
4. Informar errores por dimensión, falsos positivos de revisión, abstenciones,
   resultados por modo de fuente y ejemplos concretos. Conservar las etiquetas
   originales y el artefacto de resultados.
5. No ajustar pesos usando solo esta semilla, un único modelo, una evaluación
   hecha por LLM o una muestra no congelada. Cualquier propuesta de cambio
   requiere comparación pareada, revisión humana y aprobación editorial
   documentada.

Las reglas deterministas de seguridad editorial pueden justificarse por
política y evidencia concreta, independientemente de un cambio estadístico de
scoring. Por ejemplo, preservar si un resultado viene de células, animales o
personas; conservar la atribución de testimonios; y señalar una fuente
insuficiente son controles separables de los pesos de ranking.

## Formato de los casos semilla

Cada línea de `editorial_eval_seed.jsonl` es JSON independiente con `source_text`,
`draft_text`, `source_mode`, `design_target`, `human_review` y
`automatic_assessments`. Los diez casos son sintéticos. Los campos humanos
permanecen vacíos hasta que revisores humanos realicen y registren el trabajo.
