# Auditoría editorial adversarial — Noticiencias v2

> Producido por un asistente de IA externo distinto de Claude, comisionado
> por el operador (2026-08-24) siguiendo el prompt de auditoría adversarial
> en `/tmp/.../scratchpad/2b_adversarial_audit_prompt.md` (Phase 2b Step 1
> deliverable). Guardado aquí tal cual se recibió, como evidencia de la
> decisión registrada en `../../review/step2-review-outcomes.md`.

**Alcance.** Auditoría independiente de los 30 borradores de metadata del archivo `v2-corpus-draft-inventory.json`, usando exclusivamente el `source_url` suministrado para cada post. Cuando esa URL fue inaccesible, restringida, incorrecta o paywalled, la revisión se detuvo sin sustituir la fuente.

**Criterio.** `VERIFIED` = la fuente sostiene la afirmación; `CONTRADICTED` = la fuente dice algo incompatible; `UNSUPPORTED` = no pude encontrarla en la fuente; `PARTIALLY SUPPORTED` = sólo una parte o una versión más débil está sustentada. Los fragmentos citados son deliberadamente breves.

## Resultado ejecutivo

- **ACCEPT AS-IS:** 0
- **ACCEPT WITH EDITS:** 21
- **NEEDS REWRITE:** 3
- **DOWNGRADE TO v1:** 6

**Conclusión:** ninguno de los 30 borradores debería incorporarse sin cambios. El patrón dominante no es una sola alucinación puntual, sino una mezcla de (1) metadata de fuente sintetizada en vez de leída, (2) inferencias plausibles elevadas a hechos, (3) statuses mal calibrados, (4) `why_it_matters` que introduce consecuencias latinoamericanas no demostradas, y (5) statements de `confidence` que a veces describen incorrectamente el estado de revisión por pares.

---

### 2026-01-15-cursos-en-linea-abren-puertas-a-nuevas-carreras.md
**Source URL:** https://news.mit.edu/2026/how-online-mit-course-supply-chain-management-sparked-new-career-0115

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Kevin Power completó un curso MicroMasters de la MIT sobre gestión de cadenas de suministro.
  - Evidencia/nota: El perfil confirma que Power completó el track de cinco cursos MicroMasters; conviene decir «programa/track», no «un curso».
- **PARTIALLY SUPPORTED** — Tras el curso, Kevin Power fue aceptado en el programa de gestión de cadenas de suministro de la MIT.
  - Evidencia/nota: La fuente lo sitúa después «in the MIT SCM program», pero no formula literalmente la secuencia «tras el curso, fue aceptado».
- **CONTRADICTED** — Hoy Kevin Power trabaja como profesional en gestión de cadenas de suministro.
  - Evidencia/nota: La fuente lo describe actualmente como «current master's student» en Technology and Policy, no como profesional SCM en ejercicio.

**Sources block:** No. Título real: "How an online MIT course in supply chain management sparked a new career". Publisher: MIT News / MIT Center for Transportation and Logistics. Fecha: 2026-01-15.

**Other flags:**
- El tercer summary_point repite la afirmación contradicha sobre su ocupación actual.
- MicroMasters: la fuente respalda una credencial, pero no la formulación «credenciales acreditadas».
- Los beneficios específicos para reconversión profesional en América Latina son extrapolación editorial, no hallazgo de esta fuente.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-17-cientificos-descubren-adn-preservado-en-guepardos-momificados.md
**Source URL:** https://livescience.com/animals/cats/ancient-mummified-cheetahs-discovered-in-saudi-arabia-contain-preserved-dna-from-the-long-lost-population

**Source reachable:** yes

**Fact-check claims:**
- **UNSUPPORTED** — Se extrajo ADN de siete guepardos momificados encontrados en Arabia Saudita.
  - Evidencia/nota: La fuente dice que se hallaron siete guepardos momificados y que se obtuvo ADN antiguo, pero no establece que se extrajera ADN de los siete.
- **VERIFIED** — Los restos datan entre 100 y 4,000 años atrás.
  - Evidencia/nota: La fuente sitúa los restos entre aproximadamente «100 and 4,000 years» de antigüedad.
- **VERIFIED** — Los guepardos más antiguos están más estrechamente relacionados con subespecies del África Occidental que con las asiáticas.
  - Evidencia/nota: Los ejemplares prehistóricos aparecen más próximos a A. j. hecki, la subespecie de África noroccidental, que a la asiática.
- **VERIFIED** — La pérdida de diversidad genética del guepardo podría haber sido mayor de lo que se pensaba.
  - Evidencia/nota: La fuente plantea explícitamente que la pérdida de diversidad genética pudo haber sido mayor de lo supuesto; no debería figurar como `uncertain`.
- **VERIFIED** — Los guepardos para el rewilding en la península arábiga pueden obtenerse de la subespecie A. j. hecki, más abundante que la asiática.
  - Evidencia/nota: A. j. hecki se presenta como candidato práctico para rewilding y como mucho más abundante que la subespecie asiática; `needs_review` es demasiado débil.

**Sources block:** Parcialmente. El título coincide. Publisher debe escribirse "Live Science", no "Livescience". Completar fecha: 2026-01-16.

**Other flags:**
- El primer summary_point sobre «ADN de siete guepardos» excede lo que dice la fuente.
- El confidence reduce impropiamente la muestra a «7 especímenes» cuando el artículo también describe abundantes restos esqueléticos.
- Glosario: «permettant» es un error lingüístico; también hay un error gramatical en la definición de subespecie.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-18-nasa-se-prepara-para-un-paso-historico-en-la-exploracion-espacial-humana-con-artemis-ii.md
**Source URL:** https://nasa.gov/news-release/what-you-need-to-know-about-nasas-artemis-ii-moon-mission/

**Source reachable:** yes

**Fact-check claims:**
- **UNSUPPORTED** — Artemis II será la misión más larga y desafiante hasta la fecha
  - Evidencia/nota: No encontré en la fuente la afirmación «la misión más larga y desafiante hasta la fecha».
- **CONTRADICTED** — La misión enviará estadounidenses a Marte
  - Evidencia/nota: Artemis II no enviará estadounidenses a Marte; NASA habla de avanzar hacia «sending Americans to Mars» en misiones futuras.
- **VERIFIED** — Artemis II enviará seres humanos más allá de la Tierra que nunca antes
  - Evidencia/nota: NASA dice que Artemis II enviará humanos «farther from Earth than ever before».

**Sources block:** Sí en publisher; no en metadata completa. Título real: "What You Need to Know About NASA's Artemis II Moon Mission". Publisher: NASA. Fecha: 2026-01-16.

**Other flags:**
- Error central: Artemis II es la segunda misión de Artemis y la primera misión tripulada de Artemis; llamarla «segunda misión tripulada» es incorrecto.
- «Presencia lunar duradera» no equivale necesariamente a una «base permanente» como afirma el glosario.
- Minería espacial, telecomunicaciones regionales y resiliencia climática son extrapolaciones que la fuente no sustenta.
- **Verificado independientemente por Claude (2026-08-24) contra la fuente NASA real:** la cita atribuida a Isaacman en el cuerpo publicado del post ("Artemis II representa el avance hacia la establecimiento de una presencia lunar duradera y enviar estadounidenses a Marte") no existe en la fuente. La cita real de Isaacman es: "Artemis II will be a momentous step forward for human spaceflight. This historic mission will send humans farther from Earth than ever before." — no menciona Marte en absoluto. Esta es una cita fabricada atribuida a un funcionario real, ya publicada en el sitio en vivo.

**Recommendation:** **NEEDS REWRITE**

---

### 2026-01-23-descubren-los-arpones-mas-antiguos-una-revelacion-que-cambia-nuestra-perspectiva-sobre-la-caza-de-ballenas.md
**Source URL:** https://livescience.com/archaeology/some-of-the-oldest-harpoons-ever-found-reveal-indigenous-people-in-brazil-were-hunting-whales-5-000-years-ago

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Los arpones tienen aproximadamente 5.000 años de antigüedad.
  - Evidencia/nota: La datación de las herramientas ronda 4.710–4.970 años, por lo que «aproximadamente 5.000 años» es correcto.
- **CONTRADICTED** — Los arpones fueron hechos con costillas de ballenas azules y ballenas del sur.
  - Evidencia/nota: La especie está mal: la fuente identifica huesos de «humpback» y southern right whales, no ballena azul.
- **VERIFIED** — Los objetos se encontraron en el Museo Arqueológico Sambaquis de Joinville, Brasil.
  - Evidencia/nota: La colección fue estudiada en el Joinville Sambaqui Archaeological Museum.
- **UNSUPPORTED** — El hallazgo fue realizado por científicos brasileños.
  - Evidencia/nota: No encontré apoyo para atribuir el hallazgo específicamente a «científicos brasileños».
- **PARTIALLY SUPPORTED** — La evidencia indica caza activa de ballenas en Brasil hace 5.000 años.
  - Evidencia/nota: La evidencia general apoya caza activa, pero la propia fuente advierte que no está claro que esos arpones concretos se usaran para cazar ballenas.
- **VERIFIED** — Este descubrimiento muestra que la caza de ballenas no era exclusiva del Hemisferio Norte.
  - Evidencia/nota: El trabajo contradice la idea previa de que la caza de ballenas fuera exclusiva del hemisferio norte.

**Sources block:** No del todo. Título real en inglés: "Some of the oldest harpoons ever found reveal Indigenous people in Brazil were hunting whales 5,000 years ago". Publisher: Live Science. Fecha: 2026-01-23.

**Other flags:**
- El primer summary_point contiene la identificación errónea de ballena azul.
- El confidence dice que el artículo no muestra el estudio revisado por pares, pero la fuente identifica el trabajo publicado en Nature Communications.
- «Moléculas de hueso» es una entrada de glosario imprecisa para la metodología descrita.
- **Verificado independientemente por Claude (2026-08-24):** el cuerpo publicado del post ya afirma en su primer párrafo "científicos brasileños han descubierto arpones... hechos a partir de las costillas de ballenas azules y ballenas del sur" — ambos errores (autoría, especie) están en el texto publicado, no solo en el borrador de metadata.

**Recommendation:** **NEEDS REWRITE**

---

### 2026-01-24-thomas-edison-podria-haber-creado-el-grafeno-accidentalmente-en-1879.md
**Source URL:** https://arstechnica.com/science/2026/01/did-edison-accidentally-make-graphene-in-1879/

**Source reachable:** yes

**Fact-check claims:**
- **PARTIALLY SUPPORTED** — Thomas Edison pudo haber creado accidentalmente grafeno en 1879 al calentar filamentos de bambú a más de 2000 °C
  - Evidencia/nota: La posibilidad de que Edison produjera grafeno accidentalmente está planteada, pero el artículo enfatiza que no constituye prueba histórica definitiva.
- **VERIFIED** — Lucas Eddy, estudiante de posgrado de la Universidad de Rice, logró producir grafeno recreando el experimento de Edison con bombillas artesanales de bambú
  - Evidencia/nota: Lucas Eddy recreó la configuración histórica y obtuvo grafeno/turbostratic graphene usando filamentos de bambú carbonizado.
- **VERIFIED** — El filamento de bambú carbonizado de Edison duraba más de 1200 horas con una fuente de 110 voltios
  - Evidencia/nota: La fuente histórica citada describe filamentos que superaban las 1.200 horas con 110 V.
- **VERIFIED** — El grafeno tiene potencial para aplicaciones en baterías, supercondensadores, antenas, filtros de agua, transistores, células solares y pantallas táctiles
  - Evidencia/nota: La fuente enumera aplicaciones de grafeno en almacenamiento de energía, antenas, filtración, transistores, celdas solares y pantallas.
- **UNSUPPORTED** — El grafeno se aisló oficialmente por primera vez en 2004
  - Evidencia/nota: No encontré en la fuente suministrada la afirmación de que el grafeno «se aisló oficialmente por primera vez en 2004».

**Sources block:** No. Título real: "Did Edison accidentally make graphene in 1879?". Publisher: Ars Technica. Fecha: 2026-01-24.

**Other flags:**
- El glosario llama «patente de 1879» a una patente de Edison concedida en 1880; debe corregirse.
- El summary sobre el aislamiento de 2004 no procede de la fuente auditada.
- El confidence afirma ausencia de publicación revisada por pares, pero el artículo remite al trabajo experimental publicado en ACS Nano.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-25-investigadores-logran-la-superposicion-cuantica-mas-grande-registrada.md
**Source URL:** https://scientificamerican.com/article/quantum-physicists-just-supersized-schroedingers-cat/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Los investigadores lograron una superposición de alrededor de 7.000 átomos de sodio.
  - Evidencia/nota: El objeto en superposición contenía alrededor de 7.000 átomos de sodio.
- **VERIFIED** — Cada cluster tiene un ancho aproximado de 8 nanómetros.
  - Evidencia/nota: El cluster medía aproximadamente 8 nanómetros.
- **VERIFIED** — La distancia entre las dos ubicaciones en superposición fue de 133 nanómetros.
  - Evidencia/nota: La separación espacial alcanzó 133 nanómetros.
- **PARTIALLY SUPPORTED** — Este resultado indica que escalar sistemas cuánticos para computadoras podría ser más factible de lo esperado.
  - Evidencia/nota: La fuente vincula el experimento con la escalabilidad de sistemas cuánticos, pero no concluye que la computación cuántica sea ahora «más factible de lo esperado».
- **VERIFIED** — El gato de Schrödinger es un experimento mental propuesto por Erwin Schrödinger en 1935.
  - Evidencia/nota: El experimento mental de Schrödinger se sitúa en 1935.

**Sources block:** No exactamente. El titular renderizado es "Largest-ever 'superposition' supersizes Schrödinger's cat". Publisher: Scientific American. Fecha: 2026-01-25.

**Other flags:**
- El summary que afirma que «no se observó un límite práctico» es demasiado fuerte.
- Se puso en superposición un cluster de miles de átomos; no «miles de objetos» independientes.
- El glosario de ordenador cuántico afirma ventaja «exponencial» de forma general, algo técnicamente demasiado amplio.
- Aplicaciones a medicina, finanzas y seguridad no son resultado de este experimento.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-25-la-guarderia-un-lugar-donde-los-bebes-intercambian-microorganismos-y-desarrollan-su-microbioma.md
**Source URL:** https://scientificamerican.com/article/babies-who-attend-daycare-share-good-germs-too/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Los bebés en guardería comparten microorganismos entre sí.
  - Evidencia/nota: La fuente documenta intercambio de microorganismos entre bebés de guardería.
- **PARTIALLY SUPPORTED** — El 15-20% de las especies microbianas en los bebés proviene de sus compañeros de guardería.
  - Evidencia/nota: Tras cuatro meses, los niños compartían aproximadamente 15–20% de especies; decir que ese porcentaje «proviene» necesariamente de compañeros es algo más fuerte.
- **VERIFIED** — El uso de antibióticos durante el primer año reduce severamente la cantidad de cepas bacterianas en el microbioma infantil.
  - Evidencia/nota: El uso de antibióticos se asoció con una reducción severa de cepas y posterior recuperación rápida.
- **VERIFIED** — El impacto a largo plazo de la exposición a cepas microbianas de la guardería en la salud adulta es desconocido.
  - Evidencia/nota: La fuente dice que los efectos de salud a largo plazo siguen siendo desconocidos; no debería quedar como `uncertain`.

**Sources block:** Casi. Título real: "Babies who attend daycare share 'good' germs, too". Publisher: Scientific American. Fecha: 2026-01-25.

**Other flags:**
- El why_it_matters sugiere beneficios frente a enfermedades inmunológicas/metabólicas que el estudio no demostró; la propia fuente enfatiza que el efecto sanitario a largo plazo es desconocido.
- Las recomendaciones de higiene derivadas del intercambio con mascotas tampoco están establecidas por el artículo.
- Glosario: «Passage» es un error lingüístico.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-27-conoce-a-los-misteriosos-electridos.md
**Source URL:** https://arstechnica.com/science/2026/01/meet-the-mysterious-electrides/

**Source reachable:** no — HTTP 403 al intentar abrir el source_url

**Fact-check claims:**
- **NO AUDIT** — fuente no utilizable bajo las reglas de esta auditoría; no se sustituyó ni se adivinó su contenido.

**Sources block:** No auditable: la página suministrada no fue accesible.

**Other flags:**
- Auditoría detenida aquí conforme a la regla del prompt: no sustituí Ars Technica por otra fuente ni inferí el contenido.

**Recommendation:** **DOWNGRADE TO v1**

---

### 2026-01-27-desafio-global-contra-el-sarampion-por-falta-de-confianza-en-las-vacunas.md
**Source URL:** https://newscientist.com/article/2513398-to-halt-measles-resurgence-we-must-fight-the-plague-of-misinformation/

**Source reachable:** no — acceso restringido al source_url

**Fact-check claims:**
- **NO AUDIT** — fuente no utilizable bajo las reglas de esta auditoría; no se sustituyó ni se adivinó su contenido.

**Sources block:** No auditable: la página suministrada no fue accesible.

**Other flags:**
- Auditoría detenida aquí conforme a la regla del prompt; no se usó otra fuente para validar el contenido.

**Recommendation:** **DOWNGRADE TO v1**

---

### 2026-01-27-herramientas-empunadas-de-piedra-sofisticadas-descubiertas-en-china-datan-de-hace-160-000-anos.md
**Source URL:** https://livescience.com/archaeology/human-evolution/160-000-year-old-sophisticated-stone-tools-discovered-in-china-may-not-have-been-made-by-homo-sapiens

**Source reachable:** yes

**Fact-check claims:**
- **PARTIALLY SUPPORTED** — Las herramientas de piedra descubiertas en Xigou datan de al menos 160.000 años.
  - Evidencia/nota: El conjunto arqueológico cubre aproximadamente 160.000–72.000 años; decir que «las herramientas datan de al menos 160.000» generaliza en exceso.
- **VERIFIED** — Más de 2.600 herramientas de piedra fueron halladas en el sitio de Xigou.
  - Evidencia/nota: La fuente reporta más de 2.600 artefactos/herramientas de piedra.
- **VERIFIED** — El estudio fue publicado en la revista Nature Communications.
  - Evidencia/nota: El estudio se identifica como publicado en Nature Communications.
- **VERIFIED** — Las herramientas empuñadas son la primera evidencia de herramientas compuestas en el Este de Asia.
  - Evidencia/nota: Las piezas hafted/compuestas se presentan como la evidencia más temprana conocida de ese tipo en Asia oriental.
- **VERIFIED** — Los posibles creadores incluyen Denisovanos, H. longi, H. juluensis o H. sapiens.
  - Evidencia/nota: La fuente discute como posibles fabricantes denisovanos, H. longi, H. juluensis y H. sapiens temprano.

**Sources block:** No. El draft usa una traducción, no el título real de Live Science. Publisher: "Live Science", no "Livescience". La fecha 2024-09-24 del draft es errónea; el artículo es de 2026-01-27.

**Other flags:**
- El primer summary_point repite la edad como si todos los artefactos fueran de 160.000 años.
- Las conexiones con el poblamiento americano y el «patrimonio indígena latinoamericano» son extrapolaciones editoriales, no resultados del estudio.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-27-nuevas-plataformas-estratosfericas-podrian-revolucionar-la-conectividad-en-areas-remotas.md
**Source URL:** https://technologyreview.com/2026/01/27/1131780/stratospheric-internet-take-off/

**Source reachable:** no — acceso restringido al source_url

**Fact-check claims:**
- **NO AUDIT** — fuente no utilizable bajo las reglas de esta auditoría; no se sustituyó ni se adivinó su contenido.

**Sources block:** No auditable: MIT Technology Review bloqueó el acceso al artículo suministrado.

**Other flags:**
- Auditoría detenida conforme al prompt; no se sustituyó la fuente.

**Recommendation:** **DOWNGRADE TO v1**

---

### 2026-01-27-piezo1-identificado-como-sensor-de-ejercicio-interno-crucial.md
**Source URL:** https://sciencedaily.com/releases/2026/01/260127010149.htm

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Piezo1 se encuentra en la superficie de las células madre mesenquimales de la médula ósea.
  - Evidencia/nota: Piezo1 se describe como mecanosensor presente en células madre mesenquimales de médula ósea.
- **VERIFIED** — La activación de Piezo1 suprime la adipogénesis en la médula ósea.
  - Evidencia/nota: Su activación reduce/suprime la adipogénesis medular.
- **VERIFIED** — En Hong Kong, el 45 % de las mujeres y el 13 % de los hombres mayores de 65 años padecen osteoporosis.
  - Evidencia/nota: La fuente cita para Hong Kong aproximadamente 45% de mujeres y 13% de hombres mayores de 65 años.
- **VERIFIED** — Fármacos que imiten la activación de Piezo1 podrían prevenir o tratar la osteoporosis.
  - Evidencia/nota: La posibilidad de «exercise mimetics»/tratamientos que imiten esta vía está explícitamente planteada como línea terapéutica futura; `uncertain` es demasiado débil si se conserva el condicional.

**Sources block:** No. El título visible es "This discovery could let bones benefit from exercise without moving". Publisher: ScienceDaily (material de University of Hong Kong). Fecha: 2026-01-27.

**Other flags:**
- El confidence dice que no se sabe si el trabajo fue revisado por pares, pero la fuente identifica el estudio en Signal Transduction and Targeted Therapy y proporciona DOI.
- «Alternativa farmacológica al ejercicio» debe conservar lenguaje prospectivo; no existe todavía una terapia clínica demostrada.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-28-moltbot-asistente-personal-de-inteligencia-artificial-ofrece-funcionalidades-innovadoras-pero-tambien-plantea-desafios-de-seguridad.md
**Source URL:** https://techcrunch.com/2026/01/27/everything-you-need-to-know-about-viral-personal-ai-assistant-clawdbot-now-moltbot/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Moltbot fue creado por Peter Steinberger, un desarrollador austriaco.
  - Evidencia/nota: Peter Steinberger es identificado como desarrollador austríaco y creador del proyecto.
- **VERIFIED** — Moltbot se llamaba previamente Clawdbot antes de cambiar de nombre por un desafío legal de Anthropic.
  - Evidencia/nota: El cambio desde Clawdbot se atribuye a un desafío de marca/legal de Anthropic.
- **VERIFIED** — Moltbot puede ejecutar comandos arbitrarios en la computadora del usuario.
  - Evidencia/nota: La fuente señala que Moltbot puede ejecutar comandos arbitrarios en el equipo del usuario.
- **VERIFIED** — La versión pública de Moltbot se deriva de una herramienta llamada 'Clawd' construida por su creador.
  - Evidencia/nota: La versión pública deriva de una herramienta previa del creador llamada Clawd.

**Sources block:** Casi. Título real: "Everything you need to know about viral personal AI assistant Clawdbot (now Moltbot)". Publisher debe ser "TechCrunch", no "Techcrunch". Fecha: 2026-01-27.

**Other flags:**
- El summary atribuye conjuntamente al creador y a expertos una recomendación de aislamiento que conviene redactar con mayor precisión.
- Las proyecciones de compras/transformación cotidiana en América Latina son extrapolación editorial.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-28-observatorio-de-la-energia-oscura-refina-comprension-de-expansion-cosmica.md
**Source URL:** https://livescience.com/physics-mathematics/dark-energy/the-dream-has-come-true-standard-model-of-cosmology-holds-up-in-massive-6-year-study-of-the-universe-with-one-big-caveat

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — El Dark Energy Survey estudió 669 millones de galaxias durante seis años.
  - Evidencia/nota: El Dark Energy Survey usó seis años de datos de aproximadamente 669 millones de galaxias.
- **VERIFIED** — Los resultados son consistentes con el modelo estándar de cosmología donde la densidad de energía oscura es constante.
  - Evidencia/nota: Los resultados son compatibles con el modelo cosmológico estándar y también dejan espacio para modelos con energía oscura evolutiva.
- **VERIFIED** — El patrón de agrupación de galaxias no coincide exactamente con las predicciones del modelo estándar.
  - Evidencia/nota: La fuente destaca una discrepancia en el agrupamiento/clumpiness de galaxias respecto de la expectativa.
- **VERIFIED** — El Observatorio Vera C. Rubin en Chile permitirá nuevas pruebas de la gravedad y arrojará luz sobre la energía oscura.
  - Evidencia/nota: El Observatorio Vera C. Rubin aparece como instrumento clave para continuar probando el problema.

**Sources block:** No del todo. Publisher debe ser "Live Science". La fecha 2024-09-26 del draft es incorrecta: el artículo es de 2026-01-27. El título real comienza "'The dream has come true': Standard model of cosmology holds up…".

**Other flags:**
- El contenido central es razonablemente fiel; el mayor problema está en metadata de fuente y fecha.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-31-como-claude-code-esta-llevando-el-vibe-coding-a-todos.md
**Source URL:** https://scientificamerican.com/article/how-claude-code-is-bringing-vibe-coding-to-everyone/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — OpenAI lanzó Codex en 2021
  - Evidencia/nota: La fuente sitúa el lanzamiento inicial de GitHub Copilot/Codex en 2021.
- **VERIFIED** — El término 'vibe coding' fue acuñado por Andrej Karpathy en febrero de 2025
  - Evidencia/nota: Atribuye a Andrej Karpathy la expresión «vibe coding» en febrero de 2025.
- **PARTIALLY SUPPORTED** — Claude Code permite crear sitios web complejos de forma más rápida y efectiva que Codex
  - Evidencia/nota: La superioridad de Claude Code se presenta como experiencia/opinión del autor, no como comparación objetiva general.
- **VERIFIED** — El vibe coding está aumentando su popularidad entre no codificadores
  - Evidencia/nota: La fuente describe el auge de herramientas de programación asistida por IA entre personas con y sin experiencia tradicional.

**Sources block:** No. El titular visible es "Software is becoming something you speak into existence". Publisher: Scientific American. Fecha: 2026-01-31.

**Other flags:**
- El draft convierte una impresión personal del autor sobre Claude Code en una afirmación factual general.
- Las consecuencias específicas para freelancing y democratización en América Latina son inferencias editoriales.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-01-31-estudio-revela-menor-agrupamiento-de-galaxias-de-lo-esperado.md
**Source URL:** https://scientificamerican.com/article/largest-galaxy-survey-yet-confirms-that-the-universe-is-not-clumpy-enough/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — El estudio analizó datos de aproximadamente 150 millones de galaxias.
  - Evidencia/nota: El análisis usa alrededor de 150 millones de galaxias.
- **VERIFIED** — Detectó y estudió más de 1.500 explosiones de supernovas.
  - Evidencia/nota: También incorpora más de 1.500 supernovas.
- **VERIFIED** — Los resultados muestran menos agrupamiento de galaxias de lo esperado según la teoría estándar.
  - Evidencia/nota: Los datos principales del DES proceden de observaciones entre 2013 y 2019 en Cerro Tololo.
- **PARTIALLY SUPPORTED** — El estudio no permite concluir que la teoría estándar de la evolución del Universo sea incorrecta.
  - Evidencia/nota: La fuente presenta la discrepancia como un problema abierto, no como refutación del modelo estándar; la cautela del claim es razonable.
- **UNSUPPORTED** — El estudio reconoce límites como sesgos en la selección de galaxias e incertidumbre en la medición de distorsión de imágenes.
  - Evidencia/nota: No encontré en esta fuente la afirmación específica de que el estudio reconozca sesgos de selección y distorsión por lente como limitaciones de medición.
- **VERIFIED** — Las observaciones se realizaron entre 2013 y 2019 en el Observatorio Interamericano Cerro Tololo, Chile.
  - Evidencia/nota: La fuente sí reporta que la materia aparece menos agrupada de lo esperado.

**Sources block:** Casi. El título coincide sustancialmente. Publisher: Scientific American. Fecha faltante: 2026-01-31.

**Other flags:**
- El summary/confidence incorporan limitaciones metodológicas concretas que no aparecen en la fuente auditada.
- Conviene separar claramente «la discrepancia existe» de cualquier conclusión sobre nueva física.
- **Verificado independientemente por Claude (2026-08-24):** el cuerpo publicado del post ya contiene, casi verbatim, el párrafo de limitaciones no sustentado por la fuente ("sesgos en la selección de galaxias y la incertidumbre asociada con la medición de la distorsión de imágenes") — no es solo un artefacto del borrador de metadata.

**Recommendation:** **ACCEPT WITH EDITS** (reclasificado a DOWNGRADE — ver review/step2-review-outcomes.md)

---

### 2026-02-05-estudio-revela-que-un-tercio-del-cancer-es-prevenible-con-cambios-en-el-estilo-de-vida.md
**Source URL:** https://scientificamerican.com/article/these-two-habits-are-linked-to-more-than-a-third-of-all-cancer-cases/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — El estudio publicado en Nature Medicine encontró que el 38% de los nuevos casos de cáncer en 2022 se atribuyen a causas evitables.
  - Evidencia/nota: El análisis abarcó 36 tipos de cáncer en 185 países.
- **VERIFIED** — El tabaquismo fue responsable de alrededor del 15% de los casos prevenibles de cáncer.
  - Evidencia/nota: Aproximadamente 38% de los casos, unos 7,1 millones, se clasificaron como potencialmente prevenibles.
- **VERIFIED** — Las infecciones contribuyeron al 10% y el consumo de alcohol al 3% de los casos prevenibles.
  - Evidencia/nota: El tabaco explica alrededor de 15%, infecciones 10% y alcohol 3% de los casos globales analizados.
- **VERIFIED** — El análisis incluyó datos de 36 tipos de cáncer en 185 países.
  - Evidencia/nota: El estudio se identifica como publicado en Nature Medicine.

**Sources block:** No del todo. Scientific American corrigió posteriormente el titular; el visible ahora es "These two habits are linked to many cancer cases". Fecha original: 2026-02-05.

**Other flags:**
- El source title del draft conserva un titular anterior que la propia publicación corrigió.
- El framing regional de políticas de salud es razonable como relevancia, pero no es una conclusión directa del estudio.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-02-12-bienvenidos.md
**Source URL:** https://noticiencias.com/categorias/editorial

**Source reachable:** no — el source_url abre una página de categoría, no el artículo fuente

**Fact-check claims:**
- **NO AUDIT** — fuente no utilizable bajo las reglas de esta auditoría; no se sustituyó ni se adivinó su contenido.

**Sources block:** No. El URL apunta a la categoría "Editorial" de Noticiencias y no contiene el artículo que permitiría auditar las afirmaciones.

**Other flags:**
- Los cinco fact_checks quedan no auditables con la URL suministrada.
- No corresponde buscar otra página que «parezca» ser la correcta: la regla exige detenerse si la fuente proporcionada es inutilizable.

**Recommendation:** **DOWNGRADE TO v1**

---

### 2026-02-16-un-agujero-negro-se-forma-sin-explotar-una-estrella-masiva.md
**Source URL:** https://scitechdaily.com/a-massive-star-suddenly-vanished-and-left-a-black-hole-behind/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — La estrella M31-2014-DS1 está a aproximadamente 2,5 millones de años luz de la Tierra.
  - Evidencia/nota: M31-2014-DS1 se sitúa en Andrómeda, a unos 2,5 millones de años luz.
- **VERIFIED** — El brillo de la estrella disminuyó a una diezmilésima de su nivel original en longitudes de onda visibles y cercanas al infrarrojo.
  - Evidencia/nota: La estrella cayó hasta aproximadamente una diezmilésima de su brillo visible/infrarrojo previo.
- **VERIFIED** — El colapso directo de una estrella masiva puede formar un agujero negro sin una supernova visible.
  - Evidencia/nota: La interpretación central es colapso directo hacia un agujero negro sin supernova luminosa convencional.
- **VERIFIED** — El caso NGC 6946-BH1 fue reexaminado y también sugiere un colapso directo.
  - Evidencia/nota: La fuente reevalúa NGC 6946-BH1 como caso comparable.
- **CONTRADICTED** — La convectividad puede retrasar el colapso del núcleo de una estrella masiva.
  - Evidencia/nota: La convección no «retrasa el colapso del núcleo»: el núcleo colapsa rápidamente y la convección ralentiza la caída del material exterior.

**Sources block:** Sí en título y fecha sustancialmente. Publisher: SciTechDaily. Fecha: 2026-02-16.

**Other flags:**
- Debe corregirse «convectividad» por «convección» y, sobre todo, la causalidad física del último fact_check.
- El summary no debe sugerir que el núcleo tarda décadas en colapsar; la escala larga corresponde al material exterior.
- **Verificado independientemente por Claude (2026-08-24):** el cuerpo publicado repite el mismo error de física ("la convectividad puede detener o retrasar este colapso") — no es solo un artefacto del borrador de metadata.

**Recommendation:** **ACCEPT WITH EDITS** (reclasificado a DOWNGRADE — ver review/step2-review-outcomes.md)

---

### 2026-02-16-un-ingrediente-inesperado-puede-hacer-el-pan-mucho-mas-saludable.md
**Source URL:** https://scitechdaily.com/this-unexpected-ingredient-makes-bread-much-healthier/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Pan con 60 % de harina de girasol alcanzó 27,16 % de proteínas, frente al 8,27 % del pan convencional.
  - Evidencia/nota: La sustitución alta con harina de girasol elevó fuertemente el contenido proteico del pan.
- **VERIFIED** — Los niveles de antioxidantes en el pan aumentaron proporcionalmente a la cantidad de harina de girasol añadida.
  - Evidencia/nota: La fuente reporta más compuestos/actividad antioxidante con la harina de semilla de girasol.
- **VERIFIED** — Agregar el extracto acuoso de harina de semilla de girasol (SFE) preservó la textura del pan, manteniéndola cercana al pan de trigo tradicional.
  - Evidencia/nota: Con porcentajes altos también se observaron panes más densos, mostrando el trade-off tecnológico.

**Sources block:** No del todo. Publisher debe escribirse "SciTechDaily", no "Scitechdaily". Fecha faltante: 2026-02-16.

**Other flags:**
- El texto debe evitar convertir mayor proteína/antioxidantes en beneficios clínicos demostrados contra malnutrición o enfermedades crónicas.
- La atribución institucional debe reflejar con precisión la fuente (São Paulo Research Foundation y equipos del estudio), no simplificarse de forma engañosa.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-02-18-un-almacenamiento-de-datos-durable-y-coste-efectivo-para-preservar-informacion-durante-10-000-anos.md
**Source URL:** https://microsoft.com/en-us/research/blog/project-silicas-advances-in-glass-storage-technology/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — El vidrio utilizado es comúnmente encontrado en utensilios del hogar.
  - Evidencia/nota: Project Silica usa vidrio de borosilicato común como medio de almacenamiento.
- **VERIFIED** — El método permite almacenar cientos de capas de datos en una pieza de vidrio de 2 mm de espesor.
  - Evidencia/nota: Los datos se escriben en cientos de capas dentro de unos pocos milímetros de vidrio.
- **VERIFIED** — La escritura paralela a alta velocidad aumenta la velocidad de escritura.
  - Evidencia/nota: Microsoft describe escritura láser paralela de alta velocidad.
- **PARTIALLY SUPPORTED** — Se ha demostrado preservar música durante 10,000 años en colaboración con Global Music Vault.
  - Evidencia/nota: La vida útil de 10.000 años procede de pruebas de envejecimiento acelerado/proyección, no de una demostración temporal directa.
- **VERIFIED** — El artículo fue publicado en la revista Nature.
  - Evidencia/nota: La colaboración con Global Music Vault aparece como prueba de concepto para preservación de archivos musicales.

**Sources block:** No. Título real: "Project Silica's advances in glass storage technology". Publisher: Microsoft Research. Fecha: 2026-02-18.

**Other flags:**
- El lenguaje «demostró preservar por 10.000 años» debe cambiarse por «las pruebas aceleradas proyectan al menos 10.000 años».
- El confidence debe distinguir evidencia experimental acelerada de longevidad observada.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-03-27-el-error-de-redondeo-que-esconde-el-verdadero-terremoto-legal-para-meta-y-youtube.md
**Source URL:** https://theconversation.com/two-verdicts-in-two-days-how-american-courts-are-rewriting-the-rules-for-big-tech-and-children-279401

**Source reachable:** no — acceso restringido al source_url

**Fact-check claims:**
- **NO AUDIT** — fuente no utilizable bajo las reglas de esta auditoría; no se sustituyó ni se adivinó su contenido.

**Sources block:** No auditable: The Conversation no permitió recuperar la fuente suministrada.

**Other flags:**
- Auditoría detenida conforme al prompt; no se sustituyó la fuente por cobertura secundaria.

**Recommendation:** **DOWNGRADE TO v1**

---

### 2026-04-02-comunicacion-laser-como-desbloqueara-datos-gigantes-y-video-hd-para-las-misiones-lunares-tripuladas.md
**Source URL:** https://news.mit.edu/2026/lincoln-laboratory-laser-communications-terminal-launches-artemis-ii-0402

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — MAScOT será utilizado en la misión Artemis II para transmitir video HD desde la Luna.
  - Evidencia/nota: MAScOT se describe como demostración de comunicaciones ópticas para Artemis II, incluyendo video HD desde la vecindad lunar.
- **PARTIALLY SUPPORTED** — La demostración ILLUMA-T en la ISS logró un enlace láser en noviembre de 2023.
  - Evidencia/nota: ILLUMA-T fue lanzado a la ISS en noviembre de 2023; las pruebas de enlace ocurrieron durante los meses siguientes, no necesariamente en esa fecha exacta.
- **VERIFIED** — La LCRD fue lanzada por la NASA en 2021.
  - Evidencia/nota: La fuente remite a LCRD, lanzado en 2021.
- **VERIFIED** — El ancho de banda de la comunicación láser es significativamente mayor que el de la radiofrecuencia a distancias lunares.
  - Evidencia/nota: Se explica que los enlaces ópticos ofrecen mayor ancho de banda que radiofrecuencia.
- **CONTRADICTED** — La misión Artemis II tendrá una duración de aproximadamente 10 días en órbita lunar.
  - Evidencia/nota: Artemis II dura unos 10 días en total; no son «10 días en órbita lunar».
- **UNSUPPORTED** — La tecnología láser permitirá videoconferencias en tiempo real entre astronautas lunar y familiares en la Tierra.
  - Evidencia/nota: No encontré en la fuente la afirmación de videollamadas en tiempo real con las familias; sí menciona médicos, coordinación y livestream.

**Sources block:** No. Título real: "Lincoln Laboratory laser communications terminal launches on historic Artemis II moon mission". Publisher: MIT News. Fecha: 2026-04-02.

**Other flags:**
- «Desde la Luna» debe precisarse como desde la nave/vecindad lunar; Artemis II no aterriza en la superficie.
- Eliminar la afirmación de videollamadas familiares salvo que se aporte otra fuente.
- **Verificado independientemente por Claude (2026-08-24):** el cuerpo publicado ya plantea la pregunta retórica sobre "videoconferencias en tiempo real... con sus familias" (párrafo final) — presente en el texto publicado, aunque en forma especulativa/interrogativa, no como afirmación categórica.

**Recommendation:** **ACCEPT WITH EDITS** (reclasificado a DOWNGRADE — ver review/step2-review-outcomes.md)

---

### 2026-04-06-nuevos-experimentos-desafian-la-afirmacion-sobre-la-deteccion-de-materia-oscura.md
**Source URL:** https://wlab.yale.edu/posts/2026-03-31-experiments-refute-dark-matter-claim

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — El experimento DAMA/NaI observó una señal de modulación anual en 1997.
  - Evidencia/nota: DAMA/NaI reportó variabilidad/modulación anual desde finales de los años noventa.
- **VERIFIED** — Los experimentos ANAIS-112 y COSINE-100 no encontraron evidencia significativa de modulación anual en las regiones de energía relevantes.
  - Evidencia/nota: ANAIS y COSINE no observaron una modulación anual significativa compatible con la afirmación de DAMA.
- **CONTRADICTED** — Sophia Hollick combinó los datos de ANAIS-112 y COSINE-100 y encontró evidencia de la modulación observada por DAMA/LIBRA.
  - Evidencia/nota: El análisis combinado de Hollick reporta «no significant evidence of annual modulation», no evidencia positiva de modulación.
- **VERIFIED** — Maruyama, investigadora principal de COSINE-100, afirma que los resultados permiten usar detectores de yoduro de sodio para explorar materia oscura de baja masa.
  - Evidencia/nota: La fuente describe trabajo futuro con detectores sensibles a candidatos de materia oscura de baja masa.

**Sources block:** No. Título real: "Experiments Refute Dark Matter Claim". Publisher: Yale Wright Laboratory. Fecha: 2026-03-31.

**Other flags:**
- El tercer fact_check no debe conservar la misma frase con status `disputed`: la frase en sí está invertida respecto del resultado.
- Conviene reescribir el summary si repite que el combinado encontró una señal.
- **Verificado independientemente por Claude (2026-08-24):** el cuerpo publicado ya afirma correctamente lo contrario ("no mostró evidencia de la modulación observada por DAMA/LIBRA") — el error está confinado al `fact_check` del borrador de metadata, el texto publicado es correcto.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-04-24-sitios-web-ocultan-ordenes-secretas-que-manipulan-a-las-ia-sin-que-los-usuarios-lo-sepan.md
**Source URL:** https://security.googleblog.com/2026/04/ai-threats-in-wild-current-state-of.html

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Google's threat intelligence team searched the public web for indirect injections.
  - Evidencia/nota: Google describe un barrido amplio de la web pública usando Common Crawl y clasificación asistida por Gemini con validación humana.
- **VERIFIED** — They found experiments, not massive organized attacks.
  - Evidencia/nota: La publicación subraya que la mayoría de los casos observados son experimentos, bromas o intentos poco sofisticados.
- **PARTIALLY SUPPORTED** — The experiments were grouped into six categories (benign jokes, useful guidance, malicious optimization, etc.).
  - Evidencia/nota: Hay varias categorías, pero la taxonomía del draft no coincide: la fuente separa SEO, deterrence y subtipos maliciosos como exfiltración/destrucción.
- **VERIFIED** — Google runs red team tests on Gemini and offers bug‑bounty rewards for AI vulnerabilities.
  - Evidencia/nota: Google menciona red teaming y su AI Vulnerability Reward Program como defensas.
- **VERIFIED** — Indirect injections can cause an AI to follow hidden instructions that affect its output.
  - Evidencia/nota: La fuente explica que una indirect prompt injection puede inducir a un agente a obedecer instrucciones ocultas del contenido.

**Sources block:** No. Título real: "AI threats in the wild: The current state of prompt injections on the web". Publisher: Google Security Blog. Fecha correcta: 2026-04-23, no 2026-04-01.

**Other flags:**
- El titular de Noticiencias exagera el componente malicioso: la fuente insiste en que muchos casos son pruebas, bromas o intentos triviales.
- La taxonomía de seis categorías debe rehacerse con los nombres y jerarquía reales de Google.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-05-07-el-mit-descubre-que-la-automatizacion-no-mejora-la-productividad-como-se-creia.md
**Source URL:** https://news.mit.edu/2026/study-firms-often-use-automation-control-certain-workers-wages-0507

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — La automatización fue responsable del 52% del crecimiento de la desigualdad de ingresos desde 1980.
  - Evidencia/nota: La fuente atribuye a automatización alrededor de 52% del aumento de desigualdad observado entre 1980 y 2016.
- **PARTIALLY SUPPORTED** — Un 10% del aumento de la desigualdad se debe específicamente a empresas que eliminaron trabajadores con primas salariales.
  - Evidencia/nota: El artículo habla de «about 10 percentage points», no simplemente «10%»; el draft cambia la unidad.
- **VERIFIED** — Entre el 60% y el 90% de las ganancias potenciales de productividad se perdieron porque las empresas priorizaron recortar costos sobre mejorar la eficiencia.
  - Evidencia/nota: La mala asignación de automatización puede compensar entre 60% y 90% de las ganancias potenciales de productividad.
- **VERIFIED** — El estudio analizó décadas de datos laborales en 500 grupos demográficos y 49 industrias.
  - Evidencia/nota: El análisis cubre unas 500 categorías ocupacionales y 49 industrias.

**Sources block:** Sí. Título real: "When automation goes wrong". Publisher: MIT News. Fecha: 2026-05-07.

**Other flags:**
- Problema editorial importante: el titular/resumen «la automatización no mejora la productividad» es demasiado absoluto. La fuente dice que ciertas automatizaciones sí elevan productividad y que «menos automatización» no es siempre mejor.
- Corregir 10% por 10 puntos porcentuales donde corresponda.

**Recommendation:** **ACCEPT WITH EDITS**

---

### 2026-05-15-un-asteroide-de-700-metros-rota-cada-1-88-minutos-desafiando-teorias-astronomicas.md
**Source URL:** https://quantamagazine.org/rubin-tracks-skyscraper-size-asteroids-failed-supernovas-and-interstellar-visitors-20260515/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — El asteroide 2025 MN 45 tiene 700 m de diámetro y rota cada 1,88 minutos.
  - Evidencia/nota: El asteroide 2025 MN45 mide aproximadamente 700 m y gira una vez cada 1,88 minutos.
- **VERIFIED** — El Observatorio Vera C. Rubin generará 7 millones de alertas y 20 TB de datos cada noche cuando esté completamente operativo.
  - Evidencia/nota: Rubin genera del orden de millones de alertas y decenas de terabytes de datos por noche.
- **PARTIALLY SUPPORTED** — Rubin detectó el cometa interestelar 3I/ATLAS diez días antes que otros telescopios.
  - Evidencia/nota: 3I/ATLAS fue descubierto por ATLAS; datos de archivo de Rubin permitieron rastrearlo aproximadamente 10 días antes.
- **UNSUPPORTED** — Rubin ha observado supernovas fallidas donde estrellas masivas colapsan sin explotar.
  - Evidencia/nota: La fuente no dice que Rubin ya haya observado una supernova fallida confirmada; menciona un candidato y la capacidad futura del observatorio para encontrarlas.
- **VERIFIED** — Los datos de Rubin ayudarán a estudiar la energía oscura mediante el desplazamiento al rojo de galaxias.
  - Evidencia/nota: Los datos de redshift/estructura a gran escala se vinculan con estudios de energía oscura.

**Sources block:** Sí sustancialmente. Título: "Rubin Tracks Skyscraper-Size Asteroids, Failed Supernovas, and Interstellar Visitors". Publisher: Quanta Magazine. Fecha: 2026-05-15.

**Other flags:**
- Corregir el verbo sobre 3I/ATLAS: Rubin no fue el descubridor oficial.
- No presentar una supernova fallida como observación confirmada de Rubin si la fuente habla de candidato/capacidad futura.
- **Verificado independientemente por Claude (2026-08-24):** el cuerpo publicado ya afirma como hecho consumado "encontró supernovas fallidas, donde estrellas masivas colapsan en lugar de explotar" — el sobreclaim está en el texto publicado, no solo en el borrador de metadata.

**Recommendation:** **ACCEPT WITH EDITS** (reclasificado a DOWNGRADE — ver review/step2-review-outcomes.md)

---

### 2026-05-23-un-cohete-con-un-motor-apagado-y-otro-fallando-llego-al-espacio-y-volvio.md
**Source URL:** https://scientificamerican.com/article/spacex-launches-starship-v3-the-worlds-most-powerful-and-tallest-rocket-ever/

**Source reachable:** yes

**Fact-check claims:**
- **PARTIALLY SUPPORTED** — Starship V3 tiene una altura de 124 metros y generó 81 millones de newtons de empuje.
  - Evidencia/nota: La altura de 124 m coincide, pero la fuente redondea el empuje a unos 80 MN, no 81 MN.
- **VERIFIED** — Durante el lanzamiento, uno de los 33 motores Raptor del propulsor Super Heavy no se encendió.
  - Evidencia/nota: Uno de los 33 motores del booster no encendió; además hubo un problema separado en uno de los seis motores de la nave.
- **PARTIALLY SUPPORTED** — El escudo térmico de Starship resistió la reentrada y permitió un aterrizaje suave.
  - Evidencia/nota: La nave reentró y ejecutó maniobras de aterrizaje; la fuente no establece la cadena causal «el escudo resistió y por eso permitió un aterrizaje suave».
- **CONTRADICTED** — La NASA planea usar una versión modificada de Starship para llevar astronautas a la Luna en 2028 como parte de Artemis III.
  - Evidencia/nota: Artemis III aparece como misión de 2027 de acoplamiento/orbital; un alunizaje con Starship podría ocurrir después, tan pronto como 2028.
- **PARTIALLY SUPPORTED** — SpaceX está considerando construir centros de datos de inteligencia artificial en el espacio usando el vacío como refrigerante.
  - Evidencia/nota: La fuente menciona centros de datos/IA en el espacio, pero no respalda la afirmación específica de usar el vacío como refrigerante.

**Sources block:** Casi. Título: "SpaceX launches Starship V3—the world's most powerful and tallest rocket ever". Publisher: Scientific American. Fecha: 2026-05-22.

**Other flags:**
- Hay varias conflaciones centrales (Artemis III, alunizaje 2028, motor del booster vs motor de la nave, mecanismo del escudo térmico).
- Por densidad de correcciones, conviene rehacer todo el bloque en lugar de parchearlo.

**Recommendation:** **NEEDS REWRITE**

---

### 2026-06-12-los-chatbots-rescataron-a-elias-thorne-de-una-conversacion-casual-y-lo-convirtieron-en-una-ficcion-masiva.md
**Source URL:** https://404media.co/elias-thorne-chatbots-llms-chatgpt-lighthouse-keeper-story/

**Source reachable:** no — paywall tras la introducción

**Fact-check claims:**
- **NO AUDIT** — fuente no utilizable bajo las reglas de esta auditoría; no se sustituyó ni se adivinó su contenido.

**Sources block:** Metadata visible: 404 Media, "Chatbots Keep Telling Stories About Lighthouse Keeper 'Elias Thorne'. We Might Know Why", Samantha Cole, 2026-06-11. El cuerpo exige membresía.

**Other flags:**
- El prompt ordena detener la auditoría en una fuente paywalled; por eso no se validan los fact_checks aunque la introducción deje entrever parte del tema.

**Recommendation:** **DOWNGRADE TO v1**

---

### 2026-06-14-1-121-especies-marinas-nuevas-descubiertas-y-la-mayoria-ya-estaban-en-los-estantes-de-los-museos.md
**Source URL:** https://scientificamerican.com/article/ocean-census-reveals-more-than-1-100-new-species/

**Source reachable:** yes

**Fact-check claims:**
- **VERIFIED** — Se describieron 1.121 especies marinas nuevas entre mediados de 2025 y mediados de 2026.
  - Evidencia/nota: Ocean Census reportó 1.121 especies nuevas durante el periodo descrito.
- **VERIFIED** — El 728 de las 1.121 especies nuevas provienen de muestras almacenadas en museos.
  - Evidencia/nota: De ellas, 728 procedían de colecciones/archivos de museos.
- **VERIFIED** — La descripción taxonómica de una especie marina promedio toma más de 13 años.
  - Evidencia/nota: La fuente cifra en más de 13 años el tiempo medio entre recolección y descripción formal de una especie.
- **VERIFIED** — Menos del 0,001 % del fondo marino ha sido observado directamente por humanos.
  - Evidencia/nota: Se afirma que menos de 0,001% del fondo marino ha sido observado directamente.
- **CONTRADICTED** — Los toxinas de los gusanos cinta encontrados cerca de Marsella podrían servir para tratar el Alzheimer o la esquizofrenia.
  - Evidencia/nota: Los ribbon worms con toxinas se sitúan frente a East Timor; la referencia a Marsella corresponde a otro organismo, no a esos gusanos.

**Sources block:** No. Título real: "Ocean census reveals more than 1,100 new species". Publisher: Scientific American. Fecha: 2026-05-24.

**Other flags:**
- El fact_check «El 728…» contiene además un error gramatical; debe ser «728 de las especies…».
- Corregir cualquier summary que ubique los gusanos cinta tóxicos cerca de Marsella: la fuente los ubica en East Timor.
- **Verificado independientemente por Claude (2026-08-24):** el cuerpo publicado ya distingue correctamente Marsella (camarones) de East Timor (gusanos cinta con toxinas) — el error está confinado al `fact_check` del borrador de metadata, el texto publicado es correcto.

**Recommendation:** **ACCEPT WITH EDITS**

---

## Resumen de patrones

De los 30 posts, **0** pasan `ACCEPT AS-IS`, **21** pueden conservarse con ediciones, **3** requieren reescritura y **6** deben degradarse a v1 porque la fuente suministrada no permite una auditoría válida. Los problemas sistemáticos más repetidos son: títulos traducidos o inventados en `sources[].title` en vez del titular real; fechas vacías o erróneas; capitalización/identidad de publishers inferida desde el dominio; claims `confirmed` que en realidad contradicen o exceden la fuente; claims `uncertain` que sí aparecen explícitamente; extrapolaciones regionales en `why_it_matters`; y `confidence` que a veces afirma que no hay publicación revisada por pares aunque la propia fuente enlace o identifique el paper. Por tanto, el lote no es apto para inserción automática: la revisión humana/editorial que motivó esta auditoría es necesaria.

---

## Addendum — verificación de errores a nivel de cuerpo (Claude, 2026-08-24)

Los bloques marcados arriba con "Verificado independientemente por Claude" documentan un hallazgo adicional a esta auditoría: para varios posts, el error que el `fact_check` del borrador señala como `CONTRADICTED`/`UNSUPPORTED` **ya está presente en el cuerpo publicado del artículo**, no solo en los seis campos de metadata v2 pendientes. Esto se verificó leyendo directamente el archivo `.md` publicado en `noticiencias/src/content/posts/` para cada post con un hallazgo `CONTRADICTED`/`UNSUPPORTED`, no asumido a partir de esta auditoría. Ver `../../review/step2-review-outcomes.md` para la decisión tomada al respecto y la lista completa de posts reclasificados a `DOWNGRADE TO v1` por esta razón.
