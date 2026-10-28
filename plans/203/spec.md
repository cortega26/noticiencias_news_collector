# Plan 203: un artículo al día en los temas foco

## Contexto

- Search Console (2026-10-27): 0 impresiones en Discover, 1.268 en la búsqueda
  web. 50 de 53 artículos están indexados y se cumplen los requisitos técnicos.
  El cuello de botella es el volumen y la autoridad temática: 54 artículos en
  unos 9 meses (~1,4 por semana).
- Decisión del propietario: un artículo al día durante 4 semanas, en dos
  temas foco (salud y biología; tecnología e IA). Es la etapa de ritmo
  moderado del issue #233 del frontend.
- Hoy nada lanza la publicación sola. La recolección de GitHub Actions corre
  en una máquina temporal y no alimenta la base local. El admin solo vive
  mientras `make admin` está abierto.

## Cambios

1. `scripts/ops/daily_publish.py`: vía la API del admin, omite el día si ya
   se publicó (marcador `data/daily-publish/AAAA-MM-DD.json`) o si hay una
   publicación activa. Luego recolecta, espera y elige el candidato listo con
   mejor puntaje en `[daily_publish].categories` (con un mínimo de
   `min_score`), y lanza su publicación. Si no hay candidato, no publica.
2. `[daily_publish]` en `config.toml`: `medicine`, `biology`, `technology` y
   `artificial_intelligence`.
3. Unidades de usuario de systemd en `config/systemd/`:
   - `noticiencias-admin.service`: el admin como servicio, en los puertos
     fijos 8000/4321, con reinicio si falla. Mantiene vivos el reconciliador y
     el generador de imágenes (plan 202).
   - `noticiencias-daily-publish.timer`: todos los días a las 07:30 locales.
4. Cada artículo sigue llegando como PR al frontend para que el propietario
   lo revise.

## Medición

A las 4 semanas: `npm run analytics:dataset` en el frontend (impresiones
web/Discover a 1/7/28 días por artículo, artículos indexados).

## Verificación

- Tests de `daily_publish` con una API falsa (filtro de temas y puntaje,
  marcador diario, publicación activa, recolección fallida o agotada,
  autenticación opcional, API caída).
- Unidades instaladas y comprobadas con `systemctl --user`.
