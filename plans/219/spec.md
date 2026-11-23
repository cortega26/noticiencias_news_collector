# Plan 219 · Aislar datos locales de las imágenes Docker

**Base** `ffebfc9b3c8ff91cd001b3e2cc1c085ab6acbfc6` · 2026-11-22 · **Prioridad** P1 · **Riesgo** medio · **Esfuerzo** S–M · **Hallazgo** C07

## Resultado

El contexto y las capas del colector incluyen solo los archivos de aplicación necesarios. Los datos operativos, copias, archivos de configuración privada, dependencias locales y caches quedan fuera incluso en una compilación desde un checkout con esos archivos.

## Estado y alcance

- `Dockerfile:11–25` instala los locks base y security, configura Playwright y copia todo el contexto. `.dockerignore:1–12` excluye el `.env` raíz y pocos directorios, pero carece de exclusiones para bases de datos, respaldos y artefactos ignorados. `docker-compose.yml:8–18,35–43` usa el contexto raíz para los servicios de desarrollo y monta el directorio por separado.
- `Dockerfile.serving:21–24` usa copias explícitas y comparte el filtro de contexto por defecto. Verificar que sus insumos se conservan. La ejecución y publicación de imágenes históricas quedan fuera de esta intervención. [Semántica del contexto Docker](https://docs.docker.com/build/concepts/context/)
- Editar `Dockerfile`, el filtro de contexto que corresponda a ese Dockerfile, y actualizar la documentación activa del build en `docs/ci.md`. Incorporar un test acotado del contexto o extender el smoke de Docker en `.github/workflows/ci.yml` con fixtures ficticios si hace falta. Conservar el usuario, rutas de proceso, entrypoint y bind mounts. Si la variante de Refinery ya falla en un contenedor limpio, registrar su línea base por separado.

## Decisiones y verificación

1. Inventariar los insumos de ambos Dockerfiles desde un checkout limpio. Sustituir la copia general del Collector por copias explícitas de paquetes, scripts y archivos de configuración que usan los entrypoints. Definir el contexto permitido para evitar enviar al daemon información que luego no se copia. Si se comparte la política de exclusión, validar ambos Dockerfiles. Mantener la generación de datos en runtime o en los volúmenes ya definidos.
2. En un clon efímero, colocar fixtures identificables con nombres típicos de base de datos, respaldo, log, dependencia y configuración privada en diferentes niveles. Usar un build local y un test que pruebe exclusión tanto del contexto como de la imagen. La inspección de la imagen verifica rutas y contenido de fixtures exclusivamente. Conservar un archivo de aplicación como control positivo. Ejecutar el smoke de `scripts/run_collector.py --help` y el del contenedor serving con sus recursos de prueba. El análisis actual fue estático, basado en Dockerfiles, filtro de contexto y rutas locales.
3. Ejecutar `make docs-check` y los comandos de validación Docker de `.github/workflows/ci.yml` en modo local sin push. Usar exclusivamente datos de prueba para el build. Registrar el resultado de ambos entrypoints y del chequeo negativo de contexto.

Comprobar deriva con `git diff ffebfc9b..HEAD -- .dockerignore Dockerfile Dockerfile.serving docker-compose.yml .github/workflows/ci.yml docs/ci.md`. Si un archivo requerido por el runtime es local e irreproducible, documentar su provisión por entorno antes de alterar el contexto. Evitar cualquier prueba que empaquete el checkout de operación. Actualizar la fila 219.
