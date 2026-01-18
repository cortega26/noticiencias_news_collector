import streamlit as st
import toml
import os
import dotenv
from pathlib import Path
import sys
import sqlite3
import importlib.util

# Import refinery main explicitly to avoid ambiguous module resolution.
# Import refinery main explicitly to avoid ambiguous module resolution.
sys.path.append(str(Path(__file__).parent))
# Add project root to sys.path to find 'news_collector'
sys.path.append(str(Path(__file__).resolve().parents[2]))

# DEBUG: DIAGNOSE IMPORTS - REMOVED

# Force reload of critical modules to pick up schema changes without restart
try:
    if "news_collector.components.editorial.ai_editor" in sys.modules:
        importlib.reload(sys.modules["news_collector.components.editorial.ai_editor"])
    # MUST reload the package too because main.py imports from here
    if "news_collector.components.editorial" in sys.modules:
        importlib.reload(sys.modules["news_collector.components.editorial"])
    if "news_collector.system" in sys.modules:
        importlib.reload(sys.modules["news_collector.system"])
    # Force reload config definitions to pick up schema changes
    if "noticiencias.config_schema" in sys.modules:
        importlib.reload(sys.modules["noticiencias.config_schema"])
    if "noticiencias.config_manager" in sys.modules:
        importlib.reload(sys.modules["noticiencias.config_manager"])
except Exception as e:
    print(f"Warning: Failed to reload modules: {e}")

RUN_REFINERY_PATH = Path(__file__).parent / "main.py"
spec = importlib.util.spec_from_file_location("refinery_main", RUN_REFINERY_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load refinery main from {RUN_REFINERY_PATH}")
refinery_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refinery_main)
run_refinery = refinery_main.main
from news_collector.storage.database import DatabaseManager
from src.database import DatabaseManager as RefineryDatabaseManager
from news_collector.config.settings import DATABASE_CONFIG

import logging
# Configure logging with timestamps for console output
logging.basicConfig(
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    level=logging.INFO,
    datefmt='%H:%M:%S',
    force=True
)

# Page Config
st.set_page_config(page_title="Panel de Control Noticiencias", page_icon="🎛️", layout="wide")

st.title("🎛️ Panel de Control Unificado Noticiencias")

# Paths
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
# Load environment variables into os.environ for main.py to see them
dotenv.load_dotenv(ENV_FILE, override=True)

REFINERY_UI_TOKEN_KEY = "REFINERY_UI_TOKEN"
REFINERY_UI_BYPASS_KEY = "REFINERY_UI_UNSAFE_ALLOW"

# Paths continued below after NEWS_COLLECTOR_PATH logic...

# --- Helper Functions ---
def load_env_file():
    if not ENV_FILE.exists():
        # st.warning(f"⚠️ .env no encontrado en: {ENV_FILE}") # Too noisy on first run
        return {}
    # Use dotenv to load values without polluting os.environ if we just want to edit
    return dotenv.dotenv_values(ENV_FILE)

def save_env_file(env_vars):
    with open(ENV_FILE, "w") as f:
        for key, value in env_vars.items():
            # Basic handling for quotes
            if " " in str(value) and not str(value).startswith('"'):
                f.write(f'{key}="{value}"\n')
            else:
                f.write(f"{key}={value}\n")

def require_refinery_auth(env_vars: dict[str, str], key: str = "auth_token") -> bool:
    """Require a UI access token unless an explicit unsafe bypass is enabled."""
    bypass = (
        str(env_vars.get(REFINERY_UI_BYPASS_KEY, "")).strip() == "1"
        or os.getenv(REFINERY_UI_BYPASS_KEY) == "1"
    )
    if bypass:
        st.warning("⚠️ Autenticación desactivada vía REFINERY_UI_UNSAFE_ALLOW=1.")
        return True

    token = env_vars.get(REFINERY_UI_TOKEN_KEY) or os.getenv(REFINERY_UI_TOKEN_KEY)
    if not token:
        st.error(
            "❌ Falta REFINERY_UI_TOKEN. "
            "Configúralo en apps/refinery/.env para habilitar acciones de publicación."
        )
        return False

    if st.session_state.get("refinery_ui_authenticated"):
        return True

    with st.expander("🔐 Acceso restringido", expanded=True):
        entered = st.text_input(
            "Token de acceso",
            type="password",
            help="Ingresa REFINERY_UI_TOKEN para habilitar acciones de escritura.",
            key=key
        )
        if entered:
            if entered == token:
                st.session_state["refinery_ui_authenticated"] = True
                st.success("Autenticación exitosa.")
                return True
            st.error("Token inválido.")
    return False

# Load Env to get Path
env_config = load_env_file()
# Default relative path
# In monorepo structure, admin_panel is in apps/refinery, so root is up two levels
DEFAULT_COLLECTOR_PATH = BASE_DIR.parent.parent
# Get from env or default
collector_path_str = env_config.get("NEWS_COLLECTOR_PATH", str(DEFAULT_COLLECTOR_PATH))
NEWS_COLLECTOR_PATH = Path(collector_path_str).resolve()

COLLECTOR_CONFIG_PATH = NEWS_COLLECTOR_PATH / "config.toml"
# Use configured DB path to ensure we wipe the correct DB
configured_db_path = DATABASE_CONFIG.get("path", "refinery.db")
REFINERY_DB_PATH = NEWS_COLLECTOR_PATH / configured_db_path

def load_toml_config():
    if not COLLECTOR_CONFIG_PATH.exists():
        st.error(f"❌ Archivo de configuración no encontrado en: `{COLLECTOR_CONFIG_PATH}`")
        st.caption(f"Ruta revisada: `{NEWS_COLLECTOR_PATH}`. Configura `NEWS_COLLECTOR_PATH` en la pestaña de ajustes.")
        st.info(f"Directorio de Trabajo Actual: `{os.getcwd()}`")
        return None
    with open(COLLECTOR_CONFIG_PATH, "r") as f:
        return toml.load(f)

def save_toml_config(config_data):
    with open(COLLECTOR_CONFIG_PATH, "w") as f:
        toml.dump(config_data, f)

# --- Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🧠 IA & Refinería", "📊 Scraper & Scoring", "💼 Gestión", "📈 Analítica", "🚀 Publicados"])

# --- Tab 1: AI Settings ---
with tab1:
    st.header("Configuración de Refinería")
    env_vars = load_env_file()
    
    # Convert to mutable dict if it's not
    env_vars = dict(env_vars)
    
    if env_vars or not ENV_FILE.exists(): # Allow editing even if empty
        if not ENV_FILE.exists():
            st.info(
                f"Archivo de entorno de refinería: `{ENV_FILE}`. "
                "Crea este archivo para guardar GITHUB_TOKEN y OLLAMA_*."
            )
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🤖 Modelo de IA")
            current_model = env_vars.get("OLLAMA_MODEL", "llama3.2")
            new_model = st.selectbox(
                "Seleccionar Modelo Ollama", 
                ["llama3.2", "llama3.3", "llama3.1:70b", "mistral"],
                index=0 if "3.2" in current_model else 1
            )
            env_vars["OLLAMA_MODEL"] = new_model
            
            st.subheader("🔗 URL de API")
            env_vars["OLLAMA_API_URL"] = st.text_input("Endpoint de Ollama", env_vars.get("OLLAMA_API_URL", "http://localhost:11434/api/generate"))

        with col2:
            st.subheader("📂 Repositorios")
            env_vars["SOURCE_REPO_URL"] = st.text_input("Repo Origen", env_vars.get("SOURCE_REPO_URL", ""))
            env_vars["TARGET_REPO_URL"] = st.text_input("Repo Destino", env_vars.get("TARGET_REPO_URL", ""))
            
            # --- NEW: Configurable Path ---
            env_vars["NEWS_COLLECTOR_PATH"] = st.text_input(
                "Ruta News Collector (Local)", 
                env_vars.get("NEWS_COLLECTOR_PATH", str(DEFAULT_COLLECTOR_PATH))
            )
            # ------------------------------
            
            env_vars["GITHUB_TOKEN"] = st.text_input("Token de GitHub", env_vars.get("GITHUB_TOKEN", ""), type="password")
            env_vars[REFINERY_UI_TOKEN_KEY] = st.text_input(
                "Token UI Refinery",
                env_vars.get(REFINERY_UI_TOKEN_KEY, ""),
                type="password",
                help="Requerido para ejecutar sincronizacion y publicar.",
            )
            env_vars[REFINERY_UI_BYPASS_KEY] = (
                "1"
                if st.checkbox(
                    "Permitir acciones sin token (solo local)",
                    value=str(env_vars.get(REFINERY_UI_BYPASS_KEY, "")).strip() == "1",
                )
                else "0"
            )
            
        st.subheader("📝 Prompts del Sistema (Definidos en prompts.yaml)")
        
        # Path to prompts.yaml
        PROMPTS_YAML_PATH = NEWS_COLLECTOR_PATH / "config" / "prompts.yaml"
        
        import yaml
        
        current_prompts = {}
        if PROMPTS_YAML_PATH.exists():
            try:
                with open(PROMPTS_YAML_PATH, "r", encoding="utf-8") as f:
                    current_prompts = yaml.safe_load(f) or {}
            except Exception as e:
                st.error(f"Error leyendo prompts.yaml: {e}")
        else:
            st.warning("⚠️ No se encontró config/prompts.yaml. Se crearán valores por defecto al guardar.")
            
        # Translator Prompt
        st.markdown("##### 1. Traductor (Fase 1)")
        trans_sys = current_prompts.get("translator", {}).get("system", "")
        new_trans_sys = st.text_area("Prompt Traductor", value=trans_sys, height=150, key="prompt_trans")
        
        # Editor Prompt
        st.markdown("##### 2. Editor (Fase 2)")
        edit_sys = current_prompts.get("editor", {}).get("system", "")
        new_edit_sys = st.text_area("Prompt Editor", value=edit_sys, height=200, key="prompt_edit")

        # Headline Prompt
        st.markdown("##### 3. Titulares (Fase 3)")
        head_sys = current_prompts.get("headline", {}).get("system", "")
        new_head_sys = st.text_area("Prompt Titulares", value=head_sys, height=100, key="prompt_head")

        if st.button("💾 Guardar Prompts (YAML)"):
            updated_prompts = current_prompts.copy()
            if "translator" not in updated_prompts: updated_prompts["translator"] = {}
            if "editor" not in updated_prompts: updated_prompts["editor"] = {}
            if "headline" not in updated_prompts: updated_prompts["headline"] = {}
            
            updated_prompts["translator"]["system"] = new_trans_sys
            updated_prompts["editor"]["system"] = new_edit_sys
            updated_prompts["headline"]["system"] = new_head_sys
            
            try:
                with open(PROMPTS_YAML_PATH, "w", encoding="utf-8") as f:
                    yaml.dump(updated_prompts, f, allow_unicode=True, default_flow_style=False)
                st.success("¡Prompts actualizados en config/prompts.yaml!")
            except Exception as e:
                st.error(f"Error guardando prompts: {e}")
            
            # Also save env vars if any other changes were made
            save_env_file(env_vars)
            st.success("¡Variables de entorno actualizadas!")
    else:
        st.warning("No se encontró archivo .env y no se pudo crear.")

# --- Tab 2: Scraper Settings ---
with tab2:
    st.header("Configuración del Colector")
    config_data = load_toml_config()
    
    if config_data:
        # Collection Settings
        st.subheader("⏱️ Recolección")
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            if "collection" in config_data:
                config_data["collection"]["collection_interval_hours"] = st.number_input(
                    "Intervalo de Recolección (Horas)", 
                    min_value=1, max_value=48, 
                    value=config_data["collection"].get("collection_interval_hours", 6)
                )
                config_data["collection"]["max_articles_per_source"] = st.number_input(
                    "Máx. Artículos por Fuente", 
                    min_value=5, max_value=500, 
                    value=config_data["collection"].get("max_articles_per_source", 50)
                )

        # New Column for Scoring Model
        with col_c2:
            st.subheader("🧠 IA de Scoring")
            # Load from env specifically for scoring to allow override
            env_vars_scoring = load_env_file()
            current_scoring_model = env_vars_scoring.get("NOTICIENCIAS__SCORING__LLM_MODEL", "llama3.2")
            
            new_scoring_model = st.selectbox(
                "Modelo para Clasificación (Rápido)",
                ["llama3.2", "mistral", "llama3.1:8b"],
                index=0 if "3.2" in current_scoring_model else 0,
                help="Usar un modelo más pequeño/rápido para la fase de recolección."
            )
            
            # We save this to .env immediately when changed, or purely rely on config.toml if supported?
            # Config schema says it's part of ScoringConfig. 
            # If we write to .env it overrides everything.
            if new_scoring_model != current_scoring_model:
                env_vars_scoring["NOTICIENCIAS__SCORING__LLM_MODEL"] = new_scoring_model
                save_env_file(env_vars_scoring)
                st.toast(f"Modelo de scoring actualizado a: {new_scoring_model}")

        # Scoring Weights
        st.subheader("⚖️ Pesos de Scoring (Total debe ser ~1.0)")
        if "scoring" in config_data and "weights" in config_data["scoring"]:
            weights = config_data["scoring"]["weights"]
            
            w_col1, w_col2 = st.columns(2)
            with w_col1:
                weights["source_credibility"] = st.slider("Credibilidad Fuente", 0.0, 1.0, weights.get("source_credibility", 0.25))
                weights["recency"] = st.slider("Recencia / Frescura", 0.0, 1.0, weights.get("recency", 0.2))
            with w_col2:
                weights["content_quality"] = st.slider("Calidad Contenido", 0.0, 1.0, weights.get("content_quality", 0.25))
                weights["engagement_potential"] = st.slider("Potencial Engagement (Cognitivo)", 0.0, 1.0, weights.get("engagement_potential", 0.3))

        # Keywords
        st.subheader("🔑 Palabras Clave")
        if "text_processing" in config_data:
            tp = config_data["text_processing"]
            
            boost_txt = st.text_area("Keywords para Potenciar (separadas por coma)", ", ".join(tp.get("boost_keywords", [])))
            tp["boost_keywords"] = [x.strip() for x in boost_txt.split(",") if x.strip()]
            
            penalty_txt = st.text_area("Keywords Penalizadas/Clickbait (separadas por coma)", ", ".join(tp.get("penalty_keywords", [])))
            tp["penalty_keywords"] = [x.strip() for x in penalty_txt.split(",") if x.strip()]

        if st.button("💾 Guardar Config Colector"):
            save_toml_config(config_data)
            st.success("¡config.toml actualizado con éxito!")

        st.markdown("---")
        st.subheader("🧹 Mantenimiento del Sistema")
        with st.expander("🚨 Reinicio de Fábrica (Reset Total)", expanded=True):
            st.warning("⚠️ Esta acción borrará TODOS los datos: artículos en base de datos, caché y archivos exportados. Úsalo para empezar de cero.")
            
            # Confirmation Checkbox to prevent accidental clicks
            confirm_delete = st.checkbox("Confirmo que deseo vaciar TODO el sistema (Backend + Frontend).")
            
            if st.button("🧨 EJECUTAR RESET TOTAL", type="primary", disabled=not confirm_delete):
                 with st.spinner("Eliminando datos y reseteando caché..."):
                     try:
                         # Use the DatabaseManager for the persistent storage
                         db_man = DatabaseManager({"type": "sqlite", "path": REFINERY_DB_PATH})
                         count = db_man.clear_all_articles()
                         
                         # Clean up export files to reflect empty state immediately
                         paths_to_clean = [
                             BASE_DIR / "temp" / "source" / "data" / "exports" / "latest_articles.json",
                             NEWS_COLLECTOR_PATH / "data" / "exports" / "latest_articles.json"
                         ]
                         
                         for p in paths_to_clean:
                             if p.exists():
                                 try:
                                     p.unlink()
                                 except Exception:
                                     pass
                         
                         # 2. Clear Refinery Workflow State (refinery.db)
                         # This DB tracks which files have been turned into PRs.
                         # We must wipe it so the UI allows re-processing the same content if desired.
                         refinery_db_path = NEWS_COLLECTOR_PATH / "refinery.db"
                         if refinery_db_path.exists():
                             try:
                                 refinery_db_path.unlink()
                                 st.success(f"✅ Estado del flujo de trabajo reiniciado ({refinery_db_path.name} eliminado).")
                             except Exception as e:
                                 st.warning(f"No se pudo eliminar {refinery_db_path.name}: {e}")

                         # 3. Clean Job History & Source Metadata to force re-fetch
                         # If we don't clear this, the collector will think it just ran 
                         # and skip everything (304 Not Modified or "Duplicate Job")
                         with sqlite3.connect(REFINERY_DB_PATH) as conn:
                             cursor = conn.cursor()
                             
                             # Wipe all article data
                             tables_to_wipe = ["articles", "article_metrics", "score_logs"]
                             for table in tables_to_wipe:
                                 try:
                                     cursor.execute(f"DELETE FROM {table}")
                                     st.write(f"  - Tabla `{table}` limpiada.")
                                 except Exception:
                                     pass # Table might not exist yet
                             
                             # Reset Source Metadata (Force Re-fetch)
                             try:
                                 cursor.execute("""
                                     UPDATE sources 
                                     SET last_checked = NULL, 
                                         last_successful_check = NULL, 
                                         feed_etag = NULL, 
                                         feed_last_modified = NULL
                                 """)
                                 st.write("  - Metadatos de fuentes reiniciados (forzando re-colección).")
                             except Exception as e:
                                 st.warning(f"No se pudieron reiniciar fuentes: {e}")
                                 
                             conn.commit()

                         # Clear Streamlit Cache
                         st.cache_data.clear()
                         
                         st.success(f"✅ SISTEMA LIMPIO. {count} artículos eliminados. Caché purgada.")
                         import time
                         time.sleep(2) # Give user time to see success message
                         st.rerun()
                     except Exception as e:
                         st.error(f"Error durante limpieza: {e}")

# --- Tab 3: Operations ---
with tab3:
    st.header("Operaciones del Pipeline")
    
    st.info("ℹ️ Selecciona un artículo para refinar y publicar.")
    env_vars = dict(load_env_file())
    auth_ok = require_refinery_auth(env_vars, key="auth_ops")
    
    # Section 1: Sync
    col_sync, col_status = st.columns([1, 2])
    with col_sync:
        # User requested to eliminate Fast Mode to ensure quality discrimination
        st.info("🧠 Modo Cognitivo Activo (Análisis Profundo)")
        if st.button("🔄 Sincronizar y Recolectar", help="Ejecutar colector de noticias y traer nuevos artículos (puede tardar unos minutos)."):
            with st.spinner("Ejecutando recolección y análisis cognitivo..."):
                if not auth_ok:
                    st.warning("Autenticación requerida para sincronizar.")
                else:
                    try:
                        # Direct call to main module instead of subprocess
                        result = run_refinery(fetch_only=False, fast_mode=False)
                        if result.get("status") == "success":
                            st.success("¡Recolección Completa!")
                        else:
                            st.error("Fallo en Sincronización")
                            st.expander("Detalles del Error").write(result.get("message"))
                    except Exception as e:
                        st.error(f"Error: {e}")

    # Section 2: List Candidates
    # Look for the JSON file
    # We know main.py clones into temp/source
    CLONED_PATH = BASE_DIR / "temp" / "source" / "data" / "exports" / "latest_articles.json"
    SIBLING_PATH = NEWS_COLLECTOR_PATH / "data" / "exports" / "latest_articles.json"
    
    JSON_PATH = None
    if CLONED_PATH.exists() and SIBLING_PATH.exists():
        if CLONED_PATH.stat().st_mtime >= SIBLING_PATH.stat().st_mtime:
            JSON_PATH = CLONED_PATH
        else:
            JSON_PATH = SIBLING_PATH
    elif CLONED_PATH.exists():
        JSON_PATH = CLONED_PATH
    elif SIBLING_PATH.exists():
        JSON_PATH = SIBLING_PATH
    # If JSON is missing, try to generate it from local MD files (Mock/Test Data)
    if not (JSON_PATH and JSON_PATH.exists()):
        data_dir = CLONED_PATH.parent.parent # temp/source/data
        md_files = list(data_dir.glob("*.md"))
        if md_files:
            try:
                # Generate a temporary JSON for the UI to consume
                temp_articles = []
                for mf in md_files:
                    temp_articles.append({
                        "id": mf.name,
                        "title": mf.stem.replace("_", " ").title(),
                        "summary": "Local Markdown File (Mock/Test Data)",
                        "score": 0.99,
                        "published_date": "2025-01-01",
                        "file_path": str(mf),
                        "components": {
                            "source_credibility": 1.0,
                            "recency": 1.0,
                            "content_quality": 1.0,
                            "cognitive_engagement_norm": 1.0
                        }
                    })
                
                # Write to where the app expects it (or a temp location)
                # CLONED_PATH is .../exports/latest_articles.json
                # We will write it there so the next check passes
                CLONED_PATH.parent.mkdir(parents=True, exist_ok=True)
                import json
                with open(CLONED_PATH, "w", encoding="utf-8") as f:
                    json.dump({"articles": temp_articles}, f, indent=2)
                
                JSON_PATH = CLONED_PATH
                st.toast(f"ℹ️ Se generó un archivo JSON temporal desde {len(md_files)} archivos MD locales.", icon="🛠️")
            except Exception as e:
                st.error(f"Error generando datos mock: {e}")

    if JSON_PATH and JSON_PATH.exists():
        import json
        import pandas as pd
        
        try:
            refinery_db = RefineryDatabaseManager(REFINERY_DB_PATH) # Initialize early for safety
            
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                articles = payload.get("articles", [])
            else:
                articles = payload
            if not isinstance(articles, list):
                st.error("Formato de exportación inválido: no es una lista de artículos.")
                articles = []
            
            # --- RE-SCORING LOGIC DISABLED ---
            # We trust the score coming from the collector (especially for Cognitive Mode).
            # The Admin Panel should not overwrite with default static weights.
            # ------------------------
            # ------------------------
            
            # UX IMPROVEMENT: Allow showing processed items
            show_processed = st.sidebar.checkbox("Mostrar artículos procesados (Force Reprocess)", value=False)
            if show_processed:
                st.sidebar.info("Modo 'Force Reprocess' activo: Se muestran todos los artículos.")

            if articles:
                refinery_db = RefineryDatabaseManager(REFINERY_DB_PATH)
                available_articles = []
                
                filtered_count = 0
                for art in articles:
                    art_id = str(art.get("id", art.get("title")))
                    
                    # DEBUG SPECIFIC ID
                    if art_id == "169":
                        is_processed_raw = refinery_db.is_processed(art_id)
                        is_processed_md = refinery_db.is_processed(f"{art_id}.md")
                        # Only show debug if relevant or debug mode
                        if not show_processed and (is_processed_raw or is_processed_md):
                             # Keep this unobtrusive or remove it if user is tired of it
                             pass
                    
                    if not show_processed and (
                        refinery_db.is_processed(art_id)
                        or refinery_db.is_processed(f"{art_id}.md")
                    ):
                        filtered_count += 1
                        continue
                    available_articles.append(art)

                if filtered_count > 0:
                    st.caption(
                        f"Se ocultaron {filtered_count} artículos ya publicados."
                    )

                if not available_articles:
                    st.info("No hay artículos disponibles para procesar.")
                else:
                    st.subheader(
                        f"Artículos Disponibles ({len(available_articles)})"
                    )
                    
                    # Convert to DataFrame for easier display
                    df = pd.DataFrame(available_articles)
                    # Keep relevant columns
                    display_cols = ["id", "title", "score", "published_date"]
                    # Filter strictly for existing columns
                    display_cols = [c for c in display_cols if c in df.columns]
                    
                    # Sort by score descending
                    if "score" in df.columns:
                        df = df.sort_values(by="score", ascending=False)

                    # Display interactive table
                    # We use a selection box for simplicity as st.dataframe selection is newer
                    
                    # Create a formatted list for the selectbox
                    options = {
                        f"{row['id']} - {row['title']} "
                        f"(Score: {row.get('score', 0):.2f})": row['id']
                        for i, row in df.iterrows()
                    }
                    
                    selected_label = st.selectbox(
                        "Seleccionar Artículo a Procesar:",
                        options=list(options.keys()),
                    )
                    
                    if selected_label:
                        selected_id = options[selected_label]
                        
                        # Show details of selected
                        selected_art = next(
                            (
                                a
                                for a in available_articles
                                if str(a["id"]) == str(selected_id)
                            ),
                            None,
                        )
                        if selected_art:
                            with st.expander(
                                "📄 Revisar Resumen del Artículo", expanded=False
                            ):
                                st.write(f"**Título:** {selected_art.get('title')}")
                                st.write(
                                    f"**Resumen:** {selected_art.get('summary')}"
                                )
                        if selected_art.get("image_url"):
                            st.image(
                                selected_art.get("image_url"),
                                caption="Imagen Extraída",
                                width=300,
                            )
                        
                        # Visual Settings
                        with st.expander("🎨 Configuración Visual", expanded=True):
                            visual_analysis_enabled = st.checkbox(
                                "Activar Análisis Visual",
                                value=True,
                                help="Generar categorías y prompts para imágenes.",
                            )

                        # Process Button
                        if refinery_db.is_processed(selected_id) or refinery_db.is_processed(f"{selected_id}.md"):
                            st.warning("⚠️ Artículo ya publicado/procesado.")
                            
                            col_pub1, col_pub2 = st.columns(2)
                            with col_pub1:
                                if st.button("🔄 Forzar Reprocesamiento (Sobrescribir)", key=f"reproc_{selected_id}"):
                                    with st.spinner(f"Reprocesando ID {selected_id}..."):
                                        # ... existing logic ...
                                        # This needs refactoring to avoid duplication, but for now we copy the call logic
                                        # or we assume the main button below handles force if we allow it fall through?
                                        # No, let's keep one main action. 
                                        pass 
                            
                            with col_pub2:
                                if st.button(f"🗑️ Despublicar (Eliminar)", type="primary", key=f"del_{selected_id}"):
                                    with st.spinner(f"Solicitando eliminación de {selected_id}..."):
                                        try:
                                            # Call delete_article via import
                                            # We need to import it first or use module access
                                            import news_collector.apps.refinery.main as main_module # Dynamic? No.
                                            # We already have `run_refinery` available via importlib in admin_panel.
                                            # We need `delete_article` too.
                                            
                                            if hasattr(refinery_main, 'delete_article'):
                                                del_result = refinery_main.delete_article(str(selected_id))
                                                if del_result.get("status") == "success":
                                                    st.success("✅ Solicitud de eliminación creada.")
                                                    st.markdown(f"[Ver Pull Request de Eliminación]({del_result.get('pr_url')})")
                                                    # Update DB to un-processed?
                                                    # refinery_db.mark_processed(str(selected_id)) # No method to unmark
                                                    st.info("Nota: La base de datos local seguirá marcándolo como procesado hasta recibir confirmación de limpieza.")
                                                else:
                                                    st.error(f"Error: {del_result.get('message')}")
                                            else:
                                                st.error("Función delete_article no encontrada. Reinicia la aplicación.")
                                        except Exception as e:
                                            st.error(f"Error invocando despublicación: {e}")
                            
                        # Standard Process Button (Always visible for force reprocessing or new items)
                        if st.button(
                            f"✨ Refinar y Publicar (ID: {selected_id})",
                            type="primary",
                        ):
                            with st.spinner(
                                f"Procesando ID {selected_id}... Esto toma ~15 mins en CPU."
                            ):
                                # Direct call to main module
                                if not auth_ok:
                                    st.warning("Autenticación requerida para publicar.")
                                else:
                                    try:
                                        # Reverse logic: enable means skip=False
                                        skip_flag = not visual_analysis_enabled
                                        result = run_refinery(
                                            process_id=str(selected_id),
                                            skip_visuals=skip_flag,
                                            export_path=str(JSON_PATH),
                                        )
                                        
                                        status = result.get("status")
                                        processed_count = result.get("processed_count", 0)
                                        if status == "success" and processed_count > 0:
                                            st.success("¡Procesamiento Completo! Revisa el repo de tu web.")
                                            st.balloons()
                                        elif status == "error":
                                            st.error("Procesamiento Fallido.")
                                            st.expander("Detalles del Error").write(result.get("message"))
                                        elif status == "noop" or processed_count == 0:
                                            message = result.get(
                                                "message",
                                                "No se encontraron artículos para procesar.",
                                            )
                                            st.warning(f"Sin resultados: {message}")
                                        else:
                                            st.error("Procesamiento Fallido.")
                                            st.expander("Detalles del Error").write(result.get("message"))
                                    except Exception as e:
                                        st.error(f"Error crítico de ejecución: {e}")

            else:
                st.info("No se encontraron artículos en el archivo exportado.")
        except Exception as e:
            st.error(f"Error leyendo archivo de datos: {e}")
    else:
        st.warning("No hay datos. Clic en 'Sincronizar Datos' para buscar artículos.")

    st.markdown("---")
    st.markdown("### Registro de Actividad Reciente")
    log_file = BASE_DIR / "refinery.log"  # Assuming standard log file
    if log_file.exists():
        with open(log_file, "r") as f:
            logs = f.readlines()[-20:] # Last 20 lines
            st.code("".join(logs))
    else:
        st.text("Aún no hay registros.")


# --- Tab 4: Analytics ---
with tab4:
    st.header("📈 Analítica del Sistema")
    
    try:
        # Use simple DB manager pointing to correct path with CONFIG DICT
        db_config = {"type": "sqlite", "path": Path(REFINERY_DB_PATH)}
        db = DatabaseManager(db_config)
        
        # 1. KPIs
        col_k1, col_k2, col_k3 = st.columns(3)
        
        # Stats
        stats = db.get_collection_stats(days=30)
        total_articles = sum(d["count"] for d in stats)
        
        with col_k1:
            st.metric("Total Artículos (30d)", total_articles)
            
        # Source Performance
        source_perf = db.get_source_performance()
        avg_score_overall = sum(s["avg_score"] * s["article_count"] for s in source_perf) / total_articles if total_articles else 0
        
        with col_k2:
            st.metric("Score Promedio", f"{avg_score_overall:.2f}")

        with col_k3:
            st.metric("Fuentes Activas", len(source_perf))

        st.markdown("---")

        # 2. Charts
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            st.subheader("📊 Tendencia Recolección (30 Días)")
            if stats:
                st.line_chart({d["date"]: d["count"] for d in stats})
            else:
                st.info("No hay datos de recolección.")

        with col_c2:
            st.subheader("🎯 Distribución de Scores")
            dist = db.get_score_distribution()
            if dist:
                st.bar_chart(dist)
            else:
                st.info("No hay scores disponibles.")

        st.markdown("---")
        
        col_c3, col_c4 = st.columns(2)
        
        with col_c3:
            st.subheader("🏆 Fuentes Top")
            if source_perf:
                # Top 5 by avg score
                top_sources = sorted(source_perf, key=lambda x: x["avg_score"], reverse=True)[:5]
                st.bar_chart({s["source_name"]: s["avg_score"] for s in top_sources})
            else:
                st.info("No hay datos de fuentes.")
        
        with col_c4:
            st.subheader("📚 Contenido por Categoría")
            cats = db.get_category_breakdown()
            if cats:
                st.bar_chart({c["category"]: c["count"] for c in cats})
            else:
                st.info("No hay datos de categorías.")

    except Exception as e:
        st.error(f"Error cargando analítica: {e}")
        st.info("Asegura que la BD esté inicializada y contenga datos.")

# --- Tab 5: Content Management ---
with tab5:
    st.header("Gestionar Contenido Publicado")
    
    st.info("⚠️ Aquí puedes eliminar artículos que ya han sido publicados en el repositorio destino.")
    
    env_vars = dict(load_env_file())
    if require_refinery_auth(env_vars, key="auth_cms"):
        # reuse GitHubPublisher logic from main or init new one
        from news_collector.components.publishing import GitHubPublisher
        import git
        
        TARGET_DIR = BASE_DIR / "temp" / "target"
        POSTS_DIR = TARGET_DIR / "src/content/posts"
        
        # 1. Ensure we have the latest state
        if st.button("🔄 Refrescar Lista de Artículos Publicados"):
            gh_handler = GitHubPublisher(env_vars.get("GITHUB_TOKEN"))
            target_url = env_vars.get("TARGET_REPO_URL")
            
            with st.spinner("Sincronizando repo destino..."):
                try:
                    if not TARGET_DIR.exists():
                        st.info("Clonando repositorio destino...")
                        gh_handler.clone_repo(target_url, TARGET_DIR)
                    else:
                        try:
                            repo = git.Repo(TARGET_DIR)
                            repo.remotes.origin.pull()
                        except Exception as e:
                            st.warning(f"Error sincronizando (intentando reclonar): {e}")
                            import shutil
                            shutil.rmtree(TARGET_DIR, ignore_errors=True)
                            gh_handler.clone_repo(target_url, TARGET_DIR)
                    st.success("Repositorio actualizado y sincronizado.")
                except Exception as e:
                    st.error(f"Fallo crítico actualizando repo: {e}")

        # 2. List Files
        if TARGET_DIR.exists() and POSTS_DIR.exists():
            files = sorted(list(POSTS_DIR.glob("*.md")), reverse=True)
            
            if not files:
                st.info("No hay artículos en src/content/posts.")
            else:
                st.write(f"Encontrados **{len(files)}** artículos.")
                
                # Table layout
                for f in files:
                    col_name, col_act = st.columns([3, 2])
                    with col_name:
                        st.text(f.name)
                    with col_act:
                        # Extract traceability ID
                        refinery_id = None
                        try:
                            content = f.read_text(encoding="utf-8", errors="ignore")
                            # Simple regex for frontmatter
                            import re
                            match = re.search(r'^refinery_id:\s*["\']?([^"\']+)["\']?', content, re.MULTILINE)
                            if match:
                                refinery_id = match.group(1)
                        except:
                            pass

                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("🗑️ Despublicar", key=f"del_arch_{f.name}", help="Elimina el artículo del sitio web (vía Pull Request)."):
                                if refinery_id:
                                    with st.spinner(f"Creando solicitud de eliminación para ID {refinery_id}..."):
                                        try:
                                            # Use shared delete capability
                                            # We already have `run_refinery` available via importlib in admin_panel.
                                            
                                            if hasattr(refinery_main, 'delete_article'):
                                                # Use the imported spec module
                                                del_result = refinery_main.delete_article(str(refinery_id))
                                                if del_result.get("status") == "success":
                                                    st.success("✅ PR de eliminación creado.")
                                                    st.markdown(f"[Fusionar PR en GitHub]({del_result.get('pr_url')})")
                                                else:
                                                    st.error(f"Error: {del_result.get('message')}")
                                            else:
                                                st.error("Función delete_article no cargada.")
                                        except Exception as e:
                                            st.error(f"Error: {e}")
                                else:
                                    st.error("No se encontró refinery_id en el archivo. Eliminación manual requerida.")
                        
                        with c2:
                            if st.button("♻️ Resetear", key=f"del_reset_{f.name}", help="Borra de la web Y permite volver a procesarlo (Inbox)."):
                                try:
                                    # 1. Git Delete
                                    repo = git.Repo(TARGET_DIR)
                                    repo.index.remove([str(f.relative_to(TARGET_DIR))])
                                    f.unlink()
                                    repo.index.commit(f"Deleted (Reset) {f.name}")
                                    repo.remotes.origin.push()
                                    
                                    # 2. DB Reset
                                    # We try to delete by ID if found, otherwise by filename (legacy)
                                    db_manager = RefineryDatabaseManager(str(REFINERY_DB_PATH))
                                    
                                    if refinery_id:
                                         # Try both ID and ID.md to be safe
                                        res1 = db_manager.delete_record(refinery_id)
                                        # Also try legacy filename format just in case
                                        res2 = db_manager.delete_record(f"{refinery_id}.md")
                                        
                                        if res1 or res2:
                                            st.success(f"Reset: {f.name} (ID: {refinery_id}) -> Inbox desbloqueado.")
                                        else:
                                            # If logic returns False/None on failure, we persist w warning
                                            st.warning(f"Archivo eliminado del repo, pero NO se encontró registro en BD (ID: {refinery_id}). Inbox puede no mostrarlo si ya estaba limpio.")
                                    else:
                                        st.warning("No se encontró ID en frontmatter. Solo se eliminó el archivo.")
                                    
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
        else:
             st.warning("No se encuentra el directorio de posts. Ejecuta una sincronización primero para clonar el repo.")

