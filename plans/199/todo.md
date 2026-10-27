# Plan 199 — estado

- [x] Diagnóstico (PR #345 del frontend + `fa7adb72` + logs del crítico)
- [x] Spec
- [x] Prompt `headline`: incertidumbre con gancho, ángulo original, anti-patrones de titular plano
- [x] Prompt `headline_critic`: rigor en `direct`, reparaciones que conservan el gancho
- [x] Gates: test, lint, docs
- [x] Prueba en vivo con 2–3 artículos (sin publicar)
- [x] PR backend y CI (#405, #406)
- [x] PR frontend con 8 titulares (#356, aprobada e integrada)

## Prueba en vivo (2026-10-26, sin publicar)

Primera iteración: titulares con gancho, pero copiaba los ejemplos del prompt
y abusaba de "pero" y de la negación inicial. Segunda: casi todo en forma de
pregunta. Versión final (6 artículos que no figuran en los ejemplos):

| Publicado | Generado |
| --- | --- |
| El calor agudo alteró la coordinación ciliar de un coral en laboratorio | A 39 °C el movimiento de los cilios del coral se detiene |
| Microesferas de alginato protegen células productoras de insulina durante el cultivo en biorreactor | Microesferas de alginato suben recuperación de islotes de células madre al 91 % |
| GlucoFM: qué predice el modelo de glucosa y qué falta para usarlo clínicamente | Google entrena una IA para predecir glucosa: lo que logra y lo que no es |
| DES: qué diferencia el catálogo de 669 millones de objetos del análisis cosmológico | Solo una fracción de los 669 millones de objetos del DES alimenta los análisis cosmológicos |
| ¿El plomo en la tinta lee los rollos del Vesubio sin abrirlos? | El plomo en la tinta podría ayudar a leer rollos carbonizados del Vesubio |
| DES y el agrupamiento de materia: por qué una tensión no refuta por sí sola el modelo | El mismo dato da dos tensiones: 2,6σ o 1,8σ según cómo se compare |
