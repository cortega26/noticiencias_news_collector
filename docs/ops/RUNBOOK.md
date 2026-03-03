# 📘 RUNBOOK MAESTRO - NOTICIENCIAS NEWS COLLECTOR

> **Versión:** 2.0 (Cognitive Edition)
> **Última Actualización:** 31 de Diciembre, 2025
> **Objetivo:** Guía operativa, técnica y de mantenimiento del ecosistema Noticiencias.

---

## 📑 Índice de Contenidos

1.  [Visión General del Sistema](#1-visión-general-del-sistema)
2.  [Arquitectura Técnica](#2-arquitectura-técnica)
3.  [Instalación y Despliegue](#3-instalación-y-despliegue)
    - [Requisitos Previos](#31-requisitos-previos)
    - [Ejecución Local (Desarrollo)](#32-ejecución-local-desarrollo)
    - [Ejecución con Docker (Producción)](#33-ejecución-con-docker-producción)
4.  [Manual de Operaciones: Recolección](#4-manual-de-operaciones-recolección)
    - [Uso del CLI (run_collector.py)](#41-uso-del-cli-run_collectorpy)
    - [Flags y Comandos Útiles](#42-flags-y-comandos-útiles)
5.  [Manual de Operaciones: Refinery (UI)](#5-manual-de-operaciones-refinery-ui)
    - [El Flujo Editorial](#51-el-flujo-editorial)
    - [Configuración de la IA ("Prompt Maestro")](#52-configuración-de-la-ia-prompt-maestro)
6.  [Configuración del Sistema](#6-configuración-del-sistema)
    - [Variables de Entorno (.env)](#61-variables-de-entorno-env)
    - [Archivo Maestro (config.toml)](#62-archivo-maestro-configtoml)
    - [Scoring Cognitivo: Ajuste de Pesos](#63-scoring-cognitivo-ajuste-de-pesos)
7.  [Mantenimiento y Solución de Problemas](#7-mantenimiento-y-solución-de-problemas)
    - [Logs y Auditoría](#71-logs-y-auditoría)
    - [Comandos de Mantenimiento (Makefile)](#72-comandos-de-mantenimiento-makefile)
    - [Errores Comunes](#73-errores-comunes)

---

## 1. Visión General del Sistema

**Noticiencias News Collector** es una plataforma automatizada de **Inteligencia de Fuentes Abiertas (OSINT)** aplicada al periodismo científico. A diferencia de un scraper tradicional que maximiza el volumen de datos, este sistema maximiza la **Relevancia Cognitiva**.

### Cadena de Valor

1.  **Ingesta**: Monitorea fuentes RSS y APIs científicas de alta credibilidad (Nature, Science, NASA, etc.).
2.  **Evaluación (Scoring)**: Un algoritmo híbrido (Matemático + IA) puntúa cada noticia según su impacto potencial.
3.  **Refinamiento**: Un agente de IA (basado en Ollama) transforma textos técnicos en narrativas divulgativas listas para publicar.
4.  **Distribución**: Genera automáticamente Pull Requests en el repositorio del sitio web.

---

## 2. Arquitectura Técnica

El sistema sigue una arquitectura modular desacoplada:

- **News Collector (Backend)**:
  - Escrito en Python 3.13+.
  - Usa `SQLAlchemy` para persistencia (SQLite en local, PostgreSQL en prod).
  - Motor de Scoring en `news_collector/scoring/`.
- **Refinery (Frontend/Ops)**:
  - Aplicación Streamlit (`apps/refinery/`).
  - Sirve como Panel de Control para humanos.
  - Maneja la lógica GitOps (clonar repos, crear ramas, commits y PRs).
- **Servicios Externos**:
  - **Ollama**: Proveedor de LLM local para inferencia privada y gratuita.
  - **GitHub**: Plataforma de destino para el contenido generado.

---

## 3. Instalación y Despliegue

### 3.1 Requisitos Previos

- **OS**: Windows, Linux o macOS.
- **Software Base**:
  - Git
  - Python 3.13+
  - Docker & Docker Compose (Opcional, para producción)
  - [Ollama](https://ollama.com/) instalado y corriendo (`ollama serve`).

### 3.2 Ejecución Local (Desarrollo)

Ideal para editar código o correr recolecciones manuales.

1.  **Clonar y Preparar Entorno**:

    ```bash
    git clone <repo-url>
    cd noticiencias_news_collector
    make bootstrap  # Crea entorno virtual e instala dependencias
    ```

2.  **Configurar Secretos**:
    - Copia `.env.example` a `.env`.
    - Edita `.env` y añade tu `GITHUB_TOKEN` (necesario para publicar) y asegúrate que `OLLAMA_API_URL` apunta a tu instancia local.

3.  **Iniciar o Verificar DB**:
    - Por defecto, el sistema usará SQLite en `data/news.db`. No requiere configuración extra.
    - Por defecto, el sistema usará SQLite en `data/news.db`. No requiere configuración extra.

4.  **Iniciar Panel de Control (Refinery)**:
    ```bash
    make refinery
    # O manualmente:
    # streamlit run apps/refinery/admin_panel.py
    ```
    Accede a `http://localhost:8501`.

### 3.3 Ejecución con Docker (Producción)

Ideal para servidores o ejecución 24/7.

1.  **Construir y Levantar**:

    ```bash
    docker-compose up --build -d
    ```

    Esto levantará tres contenedores:
    - `noticiencias-db`: Base de datos PostgreSQL.
    - `noticiencias-refinery`: Panel web accesible en `http://localhost:8501`.
    - `noticiencias-collector`: Contenedor inactivo listo para ejecutar tareas programadas.

2.  **Verificar Logs**:
    ```bash
    docker-compose logs -f refinery
    ```

---

## 4. Manual de Operaciones: Recolección

El script `run_collector.py` es el punto de entrada para todas las tareas de ingesta de datos.

### 4.1 Uso del CLI (run_collector.py)

**Ejecución Estándar:**
Busca noticias nuevas en todas las fuentes, las puntúa y guarda las mejores en la base de datos.

```bash
python run_collector.py
```

**Modo Simulación (Dry Run):**
Ve qué noticias encontraría sin guardar nada en la DB. Útil para probar nuevas fuentes.

```bash
python run_collector.py --dry-run
```

**Ver Fuentes Disponibles:**
Muestra una lista de todos los orígenes configurados y su credibilidad base.

```bash
python run_collector.py --list-sources
```

### 4.2 Flags y Comandos Útiles

| Flag                | Descripción                                       | Ejemplo                                            |
| :------------------ | :------------------------------------------------ | :------------------------------------------------- |
| `--sources`         | Recolecta solo de fuentes específicas (IDs).      | `python run_collector.py --sources nature science` |
| `--show-articles N` | Muestra los top N artículos al finalizar.         | `python run_collector.py --show-articles 10`       |
| `--export-json`     | Guarda los resultados en un JSON portable.        | `python run_collector.py --export-json`            |
| `--quiet`           | Reduce el ruido en la terminal (ideal para CRON). | `python run_collector.py --quiet`                  |

---

## 5. Manual de Operaciones: Refinery (UI)

Refinery es el estudio editorial. Accede vía navegador (`http://localhost:8501`).

**Lanzamiento Local:**

```bash
make refinery
```

### 5.1 El Flujo Editorial

1.  **Sincronizar**: Ve a la pestaña **"🚀 Operations"** y pulsa **"🔄 Sync Latest Data"**. Esto ejecuta el colector en segundo plano.
2.  **Seleccionar**: En la sección "Available Articles", elige una noticia de alto puntaje.
3.  **Revisar**: Lee el resumen automático y verifica la imagen extraída.
4.  **Publicar**: Pulsa **"✨ Refine & Publish"**.
    - _Acción_: El sistema reescribe la noticia, genera posts para redes sociales y crea el PR en GitHub. Revisa la terminal o los logs para ver los borradores de Tweets/LinkedIn.

### 5.1.1 Semántica de Estado de Publicación (Refinery)

- **PR_CREATED**: estado persistido cuando el backend crea el Pull Request en el repositorio Astro.
- **PUBLISHED**: no se marca desde backend al crear el PR; corresponde a publicación final del sitio tras merge/deploy del frontend.
- **Auditor LLM**: verificación opcional post-PR por defecto (`editorial_auditor.blocking = false`).
- Si el auditor falla (timeout/disponibilidad), el pipeline de publicación no se revierte:
  - se conserva el estado **PR_CREATED**
  - se registra `audit_failed` con razón y metadatos de timeout/reintentos.

### 5.2 Configuración de la IA ("Prompt Maestro")

Puedes ajustar cómo "piensa" y "escribe" la IA sin tocar código.

1.  Ve a la pestaña **"🧠 AI & Refinery"**.
2.  Localiza el área de texto "System Prompt".
3.  Aquí puedes modificar:
    - El **Tono** (divulgativo, técnico, humorístico).
    - La **Estructura** (cambiar los 6 puntos narrativos).
    - Las **Prohibiciones**.
4.  Pulsa **"💾 Save AI Settings"** para persistir los cambios.

---

## 6. Configuración del Sistema

El comportamiento del sistema se controla mediante dos archivos principales.

### 6.1 Variables de Entorno (.env)

Contiene secretos y configuración de infraestructura.

- `GITHUB_TOKEN`: **Requerido**. Token personal (PAT) con permisos de `repo`.
- `OLLAMA_API_URL`: URL del servidor Ollama (default: `http://localhost:11434/api/generate`).
- `OLLAMA_MODEL`: Modelo a usar (ej: `llama3`, `mistral`).
- `SOURCE_REPO_URL`: Repo de origen (opcional si usas el colector local).
- `TARGET_REPO_URL`: Repo donde se publicará el sitio web.

### 6.2 Archivo Maestro (config.toml)

Contiene la lógica de negocio y pesos del algoritmo.

- **[collection]**: Intervalos de tiempo y límites de artículos por fuente.
- **[scoring.weights]**: Define qué importa más.
  - _Nota_: La suma de los pesos debe ser 1.0.

### 6.3 Scoring Cognitivo: Ajuste de Pesos

Gracias al **Cognitive Scorer**, ahora puedes ajustar la sensibilidad de la IA desde la UI.

1.  Ve a la pestaña **"📊 Scraper & Scoring"**.
2.  Ajusta los sliders:
    - **Source Credibility**: Peso de la reputación (ej. Nature vale más).
    - **Recency**: Peso de la frescura (noticias de hoy valen más).
    - **Content Quality**: Peso del texto (longitud, vocabulario).
    - **Engagement Potential (Cognitive Engagement)**: Peso de la evaluación profunda por IA (impacto, sorpresa).
3.  Pulsa **"💾 Save Scraper Config"**. Los cambios se aplican inmediatamente a la siguiente recolección.

---

## 7. Mantenimiento y Solución de Problemas

### 7.0 Verificación de Salud

Antes de operar, puedes verificar la configuración y servicios críticos:

**Verificar Configuración Resolved:**

```bash
python -c "from core.config_manager import CONFIG; print(f'API: {CONFIG.ollama.api_url}, Model: {CONFIG.ollama.model}')"
```

**Chequeo de Salud (Bootstrap/Ollama):**

```bash
python -c "from news_collector.system.bootstrap import bootstrap_system; print(bootstrap_system())"
```

### 7.1 Logs y Auditoría

- **Refinery Logs**: Se muestran en la parte inferior de la pestaña "Operations" en la UI.
- **Collector Logs**: Se guardan en `logs/collector.log` (rotación automática).
- **Errores de Despliegue**: Si usas Docker, usa `docker-compose logs`.

### 7.2 Comandos de Mantenimiento (Makefile)

El proyecto incluye un `Makefile` para tareas de calidad de código:

- `make format`: Formatea todo el código (Black/Isort).
- `make clean`: Limpia archivos temporales y caché.
- `make security`: Ejecuta auditoría de seguridad (Bandit, Pip-audit).
- `make test`: Ejecuta la suite de pruebas unitarias.

### 7.3 Errores Comunes

| Error                             | Causa Probable                             | Solución                                                              |
| :-------------------------------- | :----------------------------------------- | :-------------------------------------------------------------------- |
| `ConnectionRefusedError` (Ollama) | Ollama no está corriendo.                  | Ejecuta `ollama serve` en una terminal aparte.                        |
| `GitCommandError: 403`            | Token de GitHub inválido o expirado.       | Renueva el `GITHUB_TOKEN` en el archivo `.env`.                       |
| "Config file not found"           | Ruta incorrecta en `.env`.                 | Verifica `NEWS_COLLECTOR_PATH` en el `.env` o Admin Panel.            |
| "No articles found"               | Base de datos vacía o intervalo muy corto. | Ejecuta `run_collector.py` sin flags o aumenta `collection_interval`. |

### 7.4 Legacy Schema Governance

Legacy Schema Governance (derived from `docs/AGENTS.md` LAW-1A):

- `schema_version: 1` -> adapter fallback allowed (warning).
- `schema_version: 2+` -> strict contract enforcement.
- Any extension of legacy support requires `docs/AGENTS.md` update.

Deprecation checkpoint:

- `TODO[owner=@backend-governance; checkpoint=2026-06-30; issue=#legacy-schema-cutoff]: Decide v1 cutoff date or explicitly ratify indefinite compatibility in AGENTS amendment.`

---

## 8. Referencia de Herramientas y Scripts

Este proyecto incluye una suite de herramientas de línea de comandos en `scripts/` para facilitar la operación y mantenimiento. Todas deben ejecutarse desde la raíz del proyecto, preferiblemente usando `make` o el entorno virtual.

### 8.1 Gestión de Base de Datos (`scripts/migrate.py`)

Gestiona las migraciones de esquema de la base de datos (Alembic).

- **Comandos:**
  - `python scripts/migrate.py up`: Aplica todas las migraciones pendientes.
  - `python scripts/migrate.py down`: Revierte la última migración.
  - `python scripts/migrate.py history`: Muestra el historial de versiones.
  - `python scripts/migrate.py make "mensaje"`: Crea una nueva migración automática.

### 8.2 Verificación de Salud (`scripts/healthcheck.py`)

Diagnóstico rápido del estado del sistema. Verifica conectividad a DB, colas y frescura de datos.

- **Uso:** `python scripts/healthcheck.py`
- **Opciones:**
  - `--max-pending N`: Alerta si hay más de N items en cola.
  - `--max-ingest-minutes N`: Alerta si no hubo ingesta en N minutos.

### 8.3 Control de Calidad y Seguridad

#### Quality Gate (`scripts/quality_gate.py`)

Verifica que el pipeline de IA mantenga la calidad esperada usando "snapshots" dorados. Previene regresiones en la generación de texto.

- **Uso:** `make quality-gate`

#### Escaneo de Secretos (`scripts/run_secret_scan.py`)

Busca credenciales hardcodeadas o tokens en el código y el historial reciente.

- **Uso:** `python scripts/run_secret_scan.py --output report.json .`

#### Validación de Exportación (`scripts/validate_export.py`)

Asegura que `data/exports/latest_articles.json` cumple con el contrato esperado por el Frontend.

- **Uso:** `python scripts/validate_export.py data/exports/latest_articles.json`

### 8.4 Gestión de Versiones (`scripts/bump_version.py`)

Utilidad para incrementar la versión semántica del proyecto (`VERSION`).

- **Uso:**
  - `python scripts/bump_version.py --part patch` (1.0.0 -> 1.0.1)
  - `python scripts/bump_version.py --part minor` (1.0.0 -> 1.1.0)
  - `python scripts/bump_version.py --set 2.0.0`

### 8.5 Referencia Completa del Makefile

| Comando           | Descripción                                             |
| :---------------- | :------------------------------------------------------ |
| `make bootstrap`  | Instala dependencias y configura el entorno `.venv`.    |
| `make refinery`   | Inicia la interfaz gráfica de administración.           |
| `make run-local`  | Ejecuta el recolector de noticias una vez.              |
| `make lint`       | Verifica estilo de código (Ruff, Black).                |
| `make format`     | Corrige estilo de código automáticamente.               |
| `make test`       | Ejecuta pruebas unitarias (Pytest).                     |
| `make type`       | Verificación estática de tipos (Mypy).                  |
| `make security`   | Auditoría de seguridad (Bandit, Pip-audit, TruffleHog). |
| `make quality-ci` | Ejecuta todos los chequeos estrictos (CI pipeline).     |
| `make clean`      | Limpia caché y archivos temporales.                     |

---

**Noticiencias News Collector** - _Ingeniería aplicada al periodismo científico._
