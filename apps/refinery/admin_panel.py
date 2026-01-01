import streamlit as st
import toml
import os
import dotenv
from pathlib import Path
import sys
import importlib.util

# Import refinery main explicitly to avoid ambiguous module resolution.
sys.path.append(str(Path(__file__).parent))
REFINERY_MAIN_PATH = Path(__file__).parent / "main.py"
spec = importlib.util.spec_from_file_location("refinery_main", REFINERY_MAIN_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load refinery main from {REFINERY_MAIN_PATH}")
refinery_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refinery_main)
run_refinery = refinery_main.main
from news_collector.storage.database import DatabaseManager
from news_collector.config.settings import DATABASE_CONFIG

# Page Config
st.set_page_config(page_title="Panel de Control Noticiencias", page_icon="🎛️", layout="wide")

st.title("🎛️ Panel de Control Unificado Noticiencias")

# Paths
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

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

# Load Env to get Path
env_config = load_env_file()
# Default relative path
# In monorepo structure, admin_panel is in apps/refinery, so root is up two levels
DEFAULT_COLLECTOR_PATH = BASE_DIR.parent.parent
# Get from env or default
collector_path_str = env_config.get("NEWS_COLLECTOR_PATH", str(DEFAULT_COLLECTOR_PATH))
NEWS_COLLECTOR_PATH = Path(collector_path_str).resolve()

COLLECTOR_CONFIG_PATH = NEWS_COLLECTOR_PATH / "config.toml"

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
tab1, tab2, tab3, tab4 = st.tabs(["🧠 IA & Refinería", "📊 Scraper & Scoring", "🚀 Operaciones", "📈 Analítica"])

# --- Tab 1: AI Settings ---
with tab1:
    st.header("Configuración de Refinería")
    env_vars = load_env_file()
    
    # Convert to mutable dict if it's not
    env_vars = dict(env_vars)
    
    if env_vars or not ENV_FILE.exists(): # Allow editing even if empty
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
            
        st.subheader("📝 Prompt del Sistema (Personalidad)")
        default_prompt = (
            "You are a science communicator for 'Noticiencias'. "
            "Translate the following technical text to Spanish. "
            "Then, rewrite it to be punchy, engaging, and easy to understand for a general audience. "
            "Maintain accuracy but improve flow. "
            "Output ONLY the final Markdown content with a YAML Frontmatter block containing "
            "title, author (AI), and date (use today's date in YYYY-MM-DD format). "
            "Ensure the frontmatter starts and ends with '---'. "
            "Do not include any preamble, just the markdown."
        )
        current_prompt = env_vars.get("OLLAMA_PROMPT", default_prompt)
        # Use height=200 for a nice big editor
        env_vars["OLLAMA_PROMPT"] = st.text_area("Editar instrucciones de la IA:", value=current_prompt, height=200)

        if st.button("💾 Guardar Configuración IA"):
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

# --- Tab 3: Operations ---
with tab3:
    st.header("Operaciones del Pipeline")
    
    st.info("ℹ️ Selecciona un artículo para refinar y publicar.")
    
    # Section 1: Sync
    col_sync, col_status = st.columns([1, 2])
    with col_sync:
        if st.button("🔄 Sincronizar Datos", help="Traer últimos artículos del Colector Cloud"):
            with st.spinner("Sincronizando datos..."):
                try:
                    # Direct call to main module instead of subprocess
                    result = run_refinery(fetch_only=True)
                    if result.get("status") == "success":
                        st.success("¡Sincronización Completa!")
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
    if CLONED_PATH.exists():
        JSON_PATH = CLONED_PATH
    elif SIBLING_PATH.exists():
        JSON_PATH = SIBLING_PATH
    if JSON_PATH and JSON_PATH.exists():
        import json
        import pandas as pd
        
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                articles = json.load(f)
            
            # --- RE-SCORING LOGIC ---
            # Apply current weights from config_data to loaded articles
            if articles and "scoring" in config_data and "weights" in config_data["scoring"]:
                current_weights = config_data["scoring"]["weights"]
                recalc_count = 0
                for art in articles:
                    # We need the 'components' data to re-calculate without calling LLM
                    # If 'components' is missing, we can't re-score accurately without full re-process
                    if "components" in art:
                        comps = art["components"]
                        
                        # Extract component scores (default to 0 if missing)
                        s_score = comps.get("source_credibility", 0.0)
                        r_score = comps.get("recency", 0.0)
                        q_score = comps.get("content_quality", 0.0)
                        c_score = comps.get("cognitive_engagement_norm", 0.0)
                        
                        # Calculate new final score
                        new_final = (
                            s_score * current_weights.get("source_credibility", 0.25) +
                            r_score * current_weights.get("recency", 0.20) +
                            q_score * current_weights.get("content_quality", 0.25) +
                            c_score * current_weights.get("engagement_potential", 0.30)
                        )
                        
                        # Update article data in memory
                        art["score"] = round(new_final, 4)
                        recalc_count += 1
                
                if recalc_count > 0:
                    st.toast(f"✅ Se recalcularon {recalc_count} puntajes con los pesos actuales.", icon="🧮")
                else:
                    st.warning("⚠️ No se pudieron recalcular puntajes. Los datos cargados son 'Legacy' (sin desglose de componentes). Por favor, ejecuta una nueva recolección con el modo 'cognitive' activado.")
            # ------------------------
            
            if articles:
                st.subheader(f"Artículos Disponibles ({len(articles)})")
                
                # Convert to DataFrame for easier display
                df = pd.DataFrame(articles)
                # Keep relevant columns
                display_cols = ["id", "title", "score", "published_date"]
                # Filter strictly for existing columns
                display_cols = [c for c in display_cols if c in df.columns]
                
                # Display interactive table
                # We use a selection box for simplicity as st.dataframe selection is newer
                
                # Create a formatted list for the selectbox
                options = {f"{row['id']} - {row['title']} (Score: {row.get('score', 0):.2f})": row['id'] for i, row in df.iterrows()}
                
                selected_label = st.selectbox("Seleccionar Artículo a Procesar:", options=list(options.keys()))
                
                if selected_label:
                    selected_id = options[selected_label]
                    
                    # Show details of selected
                    selected_art = next((a for a in articles if str(a["id"]) == str(selected_id)), None)
                    if selected_art:
                        with st.expander("📄 Revisar Resumen del Artículo", expanded=False):
                            st.write(f"**Título:** {selected_art.get('title')}")
                            st.write(f"**Resumen:** {selected_art.get('summary')}")
                    if selected_art.get("image_url"):
                                st.image(selected_art.get("image_url"), caption="Imagen Extraída", width=300)
                    
                    # Visual Settings
                    with st.expander("🎨 Configuración Visual", expanded=True):
                        visual_analysis_enabled = st.checkbox("Activar Análisis Visual", value=True, help="Generar categorías y prompts para imágenes.")

                    # Process Button
                    if st.button(f"✨ Refinar y Publicar (ID: {selected_id})", type="primary"):
                        with st.spinner(f"Procesando ID {selected_id}... Esto toma ~15 mins en CPU."):
                             # Direct call to main module
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
        db = DatabaseManager(DATABASE_CONFIG)
        
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
