# Plan 204: autorreparación del stack local del admin

## Contexto

El 2026-10-28, `make admin` se lanzó mientras el servicio systemd del plan 203
ya ocupaba 8000/4321. El script:

1. Arrancó una API duplicada en 8001.
2. Falló al levantar Astro (solo admite un `astro dev` por proyecto).
3. Anunció «GUI running in the background» aunque la GUI no existía.
4. Al salir habría ejecutado `astro dev stop`, que detiene a quien tenga el
   bloqueo: la GUI del servicio.

Además, tras Ctrl+C/TERM el trap no terminaba el script, que seguía hasta la
comprobación de la GUI.

## Objetivo

`scripts/dev/admin_stack.sh` debe autorrepararse (detectar y arreglar restos
rotos), autocorregirse (no anunciar un éxito falso) y dejar registro para
mejorar (eventos persistentes y aviso ante fallos recurrentes).

## Cambios

1. `ADMIN_STACK_MODE` = `reuse` (por defecto) | `restart` | `heal` | `status`.
   - Stack sano (la GUI responde y su `ADMIN_API_TARGET` responde `/healthz`):
     `reuse` muestra las URLs y sale con 0; `restart` lo detiene y arranca uno
     nuevo. Si la GUI pertenece al servicio systemd, se indica cómo reiniciarlo.
   - GUI viva con API caída: se detiene la GUI (salvo en `status`).
   - API huérfana (sin GUI) arrancada por este script: se detiene.
   - `heal` repara y sale; `status` solo diagnostica (sale 1 si hay algo roto).
2. Las API que arranca el script llevan `ADMIN_STACK_OWNER`. Solo esas se
   detienen; un `make serve` manual nunca se toca.
3. `cleanup` solo ejecuta `astro dev stop` si el bloqueo es de una GUI que
   arrancó este script y en su puerto.
4. Si la GUI no arranca, se registra `gui_failed`, se detiene la API y el
   script sale con error.
5. Los traps de INT/TERM terminan el script (130/143).
6. Eventos en `.cache/admin-stack/events.log`; con 3 o más reparaciones o
   fallos en 7 días se imprime un aviso para buscar la causa de fondo.
7. `noticiencias-admin.service` usa `ADMIN_STACK_MODE=restart`: el servicio
   manda en 8000/4321 y no debe quedar inactivo por reutilizar un stack manual.
8. Ayuda de `make admin` actualizada.

## Verificación

- `pytest tests/scripts/test_admin_stack.py` (astro simulado y procesos
  falsos con marca única; no tocan el stack real): reutilización, GUI sin API,
  API huérfana frente a API ajena, nada corriendo y modo inválido.
- Reproducción del trap: con el trap anterior el script seguía tras TERM; con
  el nuevo sale con 143.
- En vivo contra el servicio: `ADMIN_STACK_MODE=status` y `make admin`
  detectan el stack sano, avisan que es el servicio y salen con 0.

## Sin probar

- `restart` contra un stack real (no se quiso cortar el servicio en uso).
- Un arranque completo de API y GUI con el script nuevo.
