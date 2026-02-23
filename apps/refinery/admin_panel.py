import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import dotenv
import streamlit as st
import toml

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
import logging

# from src.database import DatabaseManager as RefineryDatabaseManager # Removed legacy
from news_collector.config.settings import DATABASE_CONFIG
from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.storage.database import DatabaseManager

# Alias for compatibility if legacy code relies on this name
RefineryDatabaseManager = DatabaseManager

# Configure logging with timestamps for console output
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
    force=True,
)

# Page Config
st.set_page_config(
    page_title="Panel de Control Noticiencias", page_icon="🎛️", layout="wide"
)

st.title("🎛️ Panel de Control Unificado Noticiencias")

# --- Editorial Mode Badge ---
from news_collector.editorial.policy import EditorialPolicy

# Load Config (We need to reload it to get fresh values or just load it here)
# refinery_main has config object usually?
# Let's load mode from config.toml directly or via config_manager
try:
    from noticiencias.config_manager import load_config

    sys_config = load_config()
    editorial_mode = getattr(sys_config.app, "editorial_mode", "standard")
    policy = EditorialPolicy.from_mode(editorial_mode)

    # Display Badge
    mode_color = "blue"
    if policy.mode == "strict":
        mode_color = "red"
    elif policy.mode == "velocity":
        mode_color = "green"

    st.markdown(
        f"""
        <div style="padding: 10px; border-radius: 5px; background-color: rgba(28, 131, 225, 0.1); border: 1px solid {mode_color}; margin-bottom: 20px;">
            <h4 style="margin:0; color: {mode_color};">🛡️ Editorial Mode: {policy.mode.upper()}</h4>
            <small>Critic Threshold: <b>{policy.critic_threshold}</b> | Auditor Threshold: <b>{policy.auditor_threshold}</b> | Caveats Required: <b>{policy.require_caveats}</b></small>
        </div>
        """,
        unsafe_allow_html=True,
    )
except Exception as e:
    st.error(f"Failed to load editorial policy: {e}")


# Paths
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
# Load environment variables into os.environ for main.py to see them
dotenv.load_dotenv(ENV_FILE, override=False)

REFINERY_UI_TOKEN_KEY = "REFINERY_UI_TOKEN"  # noqa: S105  # noqa: S105 # nosec
REFINERY_UI_BYPASS_KEY = "REFINERY_UI_UNSAFE_ALLOW"

# Paths continued below after NEWS_COLLECTOR_PATH logic...


# --- Helper Functions ---
def load_secrets():
    if not ENV_FILE.exists():
        return {}
    # Only load secrets
    all_env = dotenv.dotenv_values(ENV_FILE)
    # Filter for known secrets or return all (simplest is return all for now, but UI will separate)
    return all_env


def save_secrets(secrets_dict):
    # Load existing to preserve other keys if needed, or just write what we have
    # Better: Update existing file with new values
    current = dotenv.dotenv_values(ENV_FILE)
    current.update(secrets_dict)

    with open(ENV_FILE, "w") as f:
        for key, value in current.items():
            # Only write known secrets or everything? Let's write everything that is in the dict
            # keys that are NOT secrets should generally be removed from here if we migrate them
            # But for safety, we just allow writing the passed dict + updates.

            # Simple approach: Write atomic
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
            key=key,
        )
        if entered:
            if entered == token:
                st.session_state["refinery_ui_authenticated"] = True
                st.success("Autenticación exitosa.")
                return True
            st.error("Token inválido.")
    return False


# Load Secrets for Auth
secrets = load_secrets()
# Default relative path
# In monorepo structure, admin_panel is in apps/refinery, so root is up two levels
DEFAULT_COLLECTOR_PATH = BASE_DIR.parent.parent
# Get from config (preferred) or env or default
# We need to load TOML early to find PATH?
# Chicken and egg. NEWS_COLLECTOR_PATH is expected in .env usually for bootstrapping.
# We will keep NEWS_COLLECTOR_PATH in .env/secrets for now as it defines WHERE config.toml is.
collector_path_str = os.getenv("NEWS_COLLECTOR_PATH") or secrets.get(
    "NEWS_COLLECTOR_PATH", str(DEFAULT_COLLECTOR_PATH)
)  # env overrides
NEWS_COLLECTOR_PATH = Path(collector_path_str).resolve()

COLLECTOR_CONFIG_PATH = NEWS_COLLECTOR_PATH / "config.toml"
# Use configured DB path to ensure we wipe the correct DB
configured_db_path = DATABASE_CONFIG.get("path", "refinery.db")
REFINERY_DB_PATH = NEWS_COLLECTOR_PATH / configured_db_path


def load_toml_config():
    if not COLLECTOR_CONFIG_PATH.exists():
        st.error(
            f"❌ Archivo de configuración no encontrado en: `{COLLECTOR_CONFIG_PATH}`"
        )
        st.caption(
            f"Ruta revisada: `{NEWS_COLLECTOR_PATH}`. Configura `NEWS_COLLECTOR_PATH` en la pestaña de ajustes."
        )
        st.info(f"Directorio de Trabajo Actual: `{os.getcwd()}`")
        return None
    with open(COLLECTOR_CONFIG_PATH, "r") as f:
        return toml.load(f)


def save_toml_config(config_data):
    with open(COLLECTOR_CONFIG_PATH, "w") as f:
        toml.dump(config_data, f)


def load_source_health():
    """Load latest health stats from collector export."""
    try:
        # NEWS_COLLECTOR_PATH is defined globally above
        health_path = NEWS_COLLECTOR_PATH / "data" / "exports" / "source_health.json"
        if not health_path.exists():
            return None
        import json

        with open(health_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# --- Tabs ---
tab1, tab_prompts, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "🧠 IA & Refinería",
        "📝 Prompts",
        "📊 Scraper & Scoring",
        "💼 Gestión",
        "📈 Analítica",
        "🚀 Publicados",
        "📡 Fuentes",
    ]
)

# --- Tab 1: AI Settings ---
with tab1:
    st.header("Configuración de Refinería")

    # Load both sources
    secrets = dict(load_secrets())
    config_data = load_toml_config() or {}

    # Defensive defaults: config.toml may be missing/partial during first run or after OS migration.
    config_data.setdefault("ollama", {})
    config_data.setdefault("github", {})

    if not config_data:
        st.error("No se pudo cargar config.toml. Verifica la ruta.")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🤖 Configuración de Modelos (Per-Phase)")

        # Read from TOML [ollama] section
        ollama_cfg = config_data.get("ollama", {})

        # API URL First
        current_api = ollama_cfg.get("api_url", "http://localhost:11434/api/generate")
        new_api_url = st.text_input("Endpoint de Ollama", current_api)
        config_data.setdefault("ollama", {})
        config_data["ollama"]["api_url"] = new_api_url

        # Fetch Available Models
        available_models = []
        try:
            temp_provider = OllamaProvider(api_url=new_api_url, timeout=5)
            available_models = temp_provider.list_models()
        except Exception as e:
            st.warning(f"No se pudieron cargar modelos: {e}")

        # Fallback list
        model_options = (
            available_models
            if available_models
            else ["llama3.3:latest", "llama3.2:latest", "qwen2.5:14b", "mistral"]
        )

        # Helper index
        def get_idx(options, value, default=0):
            try:
                return options.index(value)
            except ValueError:
                return default

        # Helper: Detect "Slow" Models
        def is_heavy_model(m_name):
            if not m_name:
                return False
            m_lower = m_name.lower()
            return (
                "14b" in m_lower
                or "27b" in m_lower
                or "70b" in m_lower
                or "mixtral" in m_lower
            )

        # --- Base Model (Fallback) ---
        current_base = ollama_cfg.get("model", "llama3.3:latest")
        if is_heavy_model(current_base):
            st.warning(
                f"⚠️ El modelo base '{current_base}' es muy pesado para CPU. Considera usar llama3.2."
            )

        base_model_sel = st.selectbox(
            "Modelo Base (Fallback)",
            options=model_options,
            index=get_idx(model_options, current_base),
            help="Modelo usado si se selecciona 'Default' en una fase.",
        )
        config_data["ollama"]["model"] = base_model_sel

        # --- Resolved Summary (Truth) ---
        st.markdown("##### 🔍 Resumen de Configuración (Resuelto)")
        r_trans = ollama_cfg.get("translator_model") or base_model_sel
        r_edit = ollama_cfg.get("editor_model") or base_model_sel
        r_head = ollama_cfg.get("headlines_model") or base_model_sel

        c_r1, c_r2, c_r3 = st.columns(3)
        c_r1.metric(
            "1. Traductor",
            r_trans,
            delta="Lento" if is_heavy_model(r_trans) else "Rápido",
            delta_color="inverse",
        )
        c_r2.metric(
            "2. Editor",
            r_edit,
            delta="Lento" if is_heavy_model(r_edit) else "Rápido",
            delta_color="inverse",
        )
        c_r3.metric(
            "3. Titulares",
            r_head,
            delta="Lento" if is_heavy_model(r_head) else "Rápido",
            delta_color="inverse",
        )

        st.markdown("---")

        # --- PRESETS (Shortcuts) ---
        st.markdown("#### ⚡ Presets (Atajos)")
        st.caption(
            "Aplica una configuración recomendada. Esto rellenará los selectores de abajo."
        )

        col_p1, col_p2, col_p3 = st.columns(3)

        # Preset: Production (Llama 3.2 Pure)
        if col_p1.button(
            "🚀 Producción (CPU / Rápido)",
            help="Llama 3.2 en todo. Ideal para servidores sin GPU.",
        ):
            config_data["ollama"]["model"] = "llama3.2:latest"
            config_data["ollama"]["translator_model"] = "llama3.2:latest"
            config_data["ollama"]["editor_model"] = "llama3.2:latest"
            config_data["ollama"]["headlines_model"] = "llama3.2:latest"
            save_toml_config(config_data)
            st.rerun()

        # Preset: Balanced (Qwen 14B)
        if col_p2.button(
            "⚖️ Calidad (GPU Requerida)",
            help="Qwen 14B. NO USAR EN CPU (Tiempos > 45min).",
        ):
            config_data["ollama"]["model"] = "qwen2.5:14b"
            config_data["ollama"]["translator_model"] = "qwen2.5:14b"
            config_data["ollama"]["editor_model"] = "qwen2.5:14b"
            config_data["ollama"]["headlines_model"] = "llama3.2:latest"
            save_toml_config(config_data)
            st.rerun()

        # Preset: Reset
        if col_p3.button(
            "↺ Reset a Base", help="Borra overrides y usa Modelo Base para todo."
        ):
            keys_to_remove = ["translator_model", "editor_model", "headlines_model"]
            for k in keys_to_remove:
                if k in config_data["ollama"]:
                    del config_data["ollama"][k]
            save_toml_config(config_data)
            st.rerun()

        st.markdown("---")

        # --- Phase Overrides (Explicit) ---
        st.markdown("#### 🛠️ Configuración Manual por Fase")

        phases = [
            ("translator_model", "1. Traductor Científico"),
            ("editor_model", "2. Editor Periodístico"),
            ("headlines_model", "3. Generador de Titulares"),
        ]

        # Options: Default + Models
        # Display "Default (Base)" to be clear
        default_label = f"(Default: {base_model_sel})"
        phase_options = [default_label] + model_options

        for cfg_key, label in phases:
            curr_val = ollama_cfg.get(cfg_key)  # None or str

            # Determine Index
            sel_idx = 0
            if curr_val and curr_val in model_options:
                sel_idx = (
                    model_options.index(curr_val) + 1
                )  # +1 because of Default item

            sel = st.selectbox(
                label, options=phase_options, index=sel_idx, key=f"sel_{cfg_key}"
            )

            # Save Logic
            if sel == default_label:
                # Remove explicit key to inherit base
                if cfg_key in config_data["ollama"]:
                    del config_data["ollama"][cfg_key]
            else:
                config_data["ollama"][cfg_key] = sel

    with col2:
        st.subheader("📂 Repositorios")
        config_data.setdefault(
            "github", {}
        )  # avoid KeyError when config.toml is missing or lacks [github]
        github_cfg = config_data["github"]

        github_cfg["source_repo_url"] = st.text_input(
            "Repo Origen", github_cfg.get("source_repo_url", "")
        )
        github_cfg["target_repo_url"] = st.text_input(
            "Repo Destino", github_cfg.get("target_repo_url", "")
        )

        st.markdown("---")
        st.subheader("🛡️ Fase 2.5: Crítico (Guardrail)")

        # Load Env Var for Critic
        # Note: We read from os.environ because it's a runtime toggle, but we also check secrets
        # to see if it was just set.
        env_guard = str(os.getenv("ENABLE_TRANSLATION_GUARD", "true")).lower() == "true"
        # Also check secrets dict in case it's defined there but not yet in env (rare)
        secret_guard = (
            str(secrets.get("ENABLE_TRANSLATION_GUARD", "true")).lower() == "true"
        )

        # Effective State
        is_critic_enabled = env_guard

        if not is_critic_enabled:
            st.error(
                "⚠️ **CRITIC DISABLED**: El guardrail de calidad está APAGADO. El contenido inestable pasará al editor."
            )
        else:
            st.success("✅ **CRITIC ENABLED**: Guardrail activo.")

        # Critic Configuration (Read-Only from Settings/Hardcoded defaults as per contracts)
        # We assume standard defaults if not in config
        critic_threshold = 70  # Default contract
        if "text_processing" in config_data:
            critic_threshold = config_data["text_processing"].get(
                "critic_score_threshold", 70
            )

        c_col1, c_col2 = st.columns(2)
        # fmt: off
        c_col1.metric("Umbral de Aprobación", f"{critic_threshold}/100", help="Puntuación mínima para pasar.")
        # fmt: on
        c_col2.metric("Reintentos Máximos", "2", help="Hardcoded en pipeline.")

        st.caption(f"🤖 **Modelo**: Usa el mismo modelo que el **Editor** ({r_edit}).")

        # Toggle (saves to secrets/.env)
        new_guard_state = st.toggle("Habilitar Crítico", value=is_critic_enabled)
        if new_guard_state != is_critic_enabled:
            secrets["ENABLE_TRANSLATION_GUARD"] = "true" if new_guard_state else "false"
            st.warning("Cambio pendiente. Guarda la configuración para aplicar.")

        # --- PATH remains in Secrets/Env ---
        secrets["NEWS_COLLECTOR_PATH"] = st.text_input(
            "Ruta News Collector (Local)",
            secrets.get("NEWS_COLLECTOR_PATH", str(DEFAULT_COLLECTOR_PATH)),
        )
        # ------------------------------

        st.markdown("##### 🔐 Secretos (.env)")
        secrets["GITHUB_TOKEN"] = st.text_input(
            "Token de GitHub", secrets.get("GITHUB_TOKEN", ""), type="password"
        )
        secrets[REFINERY_UI_TOKEN_KEY] = st.text_input(
            "Token UI Refinery",
            secrets.get(REFINERY_UI_TOKEN_KEY, ""),
            type="password",
            help="Requerido para ejecutar sincronizacion y publicar.",
        )
        secrets[REFINERY_UI_BYPASS_KEY] = (
            "1"
            if st.checkbox(
                "Permitir acciones sin token (solo local)",
                value=str(secrets.get(REFINERY_UI_BYPASS_KEY, "")).strip() == "1",
            )
            else "0"
        )

    # Save Button (Handles Both)
    if st.button("💾 Guardar Configuración (Global)"):
        # 1. Save TOML
        save_toml_config(config_data)
        # 2. Save Secrets
        save_secrets(secrets)
        st.success("¡Configuración y Secretos actualizados!")

    # End of Tab 1

# --- Tab Prompts ---
with tab_prompts:
    st.header("📝 Prompts del Sistema")
    st.info("Define las instrucciones para cada fase del proceso de refinamiento.")

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
        st.warning(
            "⚠️ No se encontró config/prompts.yaml. Se crearán valores por defecto al guardar."
        )

    # Translator Prompt
    st.markdown("##### 1. Traductor (Fase 1)")
    trans_sys = current_prompts.get("translator", {}).get("system", "")
    new_trans_sys = st.text_area(
        "Prompt Traductor", value=trans_sys, height=150, key="prompt_trans"
    )

    # Editor Prompt
    st.markdown("##### 2. Editor (Fase 2)")
    edit_sys = current_prompts.get("editor", {}).get("system", "")
    new_edit_sys = st.text_area(
        "Prompt Editor", value=edit_sys, height=200, key="prompt_edit"
    )

    # Headline Prompt
    st.markdown("##### 3. Titulares (Fase 3)")
    head_sys = current_prompts.get("headline", {}).get("system", "")
    new_head_sys = st.text_area(
        "Prompt Titulares", value=head_sys, height=100, key="prompt_head"
    )

    if st.button("💾 Guardar Prompts (YAML)"):
        updated_prompts = current_prompts.copy()
        if "translator" not in updated_prompts:
            updated_prompts["translator"] = {}
        if "editor" not in updated_prompts:
            updated_prompts["editor"] = {}
        if "headline" not in updated_prompts:
            updated_prompts["headline"] = {}

        updated_prompts["translator"]["system"] = new_trans_sys
        updated_prompts["editor"]["system"] = new_edit_sys
        updated_prompts["headline"]["system"] = new_head_sys

        try:
            with open(PROMPTS_YAML_PATH, "w", encoding="utf-8") as f:
                yaml.dump(
                    updated_prompts, f, allow_unicode=True, default_flow_style=False
                )
            st.success("¡Prompts actualizados en config/prompts.yaml!")
        except Exception as e:
            st.error(f"Error guardando prompts: {e}")

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
                config_data["collection"]["collection_interval_hours"] = (
                    st.number_input(
                        "Intervalo de Recolección (Horas)",
                        min_value=1,
                        max_value=48,
                        value=config_data["collection"].get(
                            "collection_interval_hours", 6
                        ),
                    )
                )
                config_data["collection"]["max_articles_per_source"] = st.number_input(
                    "Máx. Artículos por Fuente",
                    min_value=5,
                    max_value=500,
                    value=config_data["collection"].get("max_articles_per_source", 50),
                )

        # New Column for Scoring Model
        with col_c2:
            st.subheader("🧠 IA de Scoring")
            # Read from Config
            scoring_cfg = config_data.get("scoring", {})
            current_scoring_model = scoring_cfg.get("llm_model", "llama3.2")

            new_scoring_model = st.selectbox(
                "Modelo para Clasificación (Rápido)",
                ["llama3.2", "mistral", "llama3.1:8b"],
                index=0 if "3.2" in current_scoring_model else 0,
                help="Usar un modelo más pequeño/rápido para la fase de recolección.",
            )

            if new_scoring_model != current_scoring_model:
                if "scoring" not in config_data:
                    config_data["scoring"] = {}
                config_data["scoring"]["llm_model"] = new_scoring_model
                # We defer save to the main button below or add a specific one?
                # The code structure below has a "Guardar Config Colector" button.
                # Use st.warning to remind user to save
                st.info(
                    f"Modelo seleccionado: {new_scoring_model}. Recuerda guardar cambios."
                )

        # Scoring Weights
        st.subheader("⚖️ Pesos de Scoring (Total debe ser ~1.0)")
        if "scoring" in config_data and "weights" in config_data["scoring"]:
            weights = config_data["scoring"]["weights"]

            w_col1, w_col2 = st.columns(2)
            with w_col1:
                weights["source_credibility"] = st.slider(
                    "Credibilidad Fuente",
                    0.0,
                    1.0,
                    weights.get("source_credibility", 0.25),
                )
                weights["recency"] = st.slider(
                    "Recencia / Frescura", 0.0, 1.0, weights.get("recency", 0.2)
                )
            with w_col2:
                weights["content_quality"] = st.slider(
                    "Calidad Contenido", 0.0, 1.0, weights.get("content_quality", 0.25)
                )
                weights["engagement_potential"] = st.slider(
                    "Potencial Engagement (Cognitivo)",
                    0.0,
                    1.0,
                    weights.get("engagement_potential", 0.3),
                )

        # Keywords
        st.subheader("🔑 Palabras Clave")
        if "text_processing" in config_data:
            tp = config_data["text_processing"]

            boost_txt = st.text_area(
                "Keywords para Potenciar (separadas por coma)",
                ", ".join(tp.get("boost_keywords", [])),
            )
            tp["boost_keywords"] = [
                x.strip() for x in boost_txt.split(",") if x.strip()
            ]

            penalty_txt = st.text_area(
                "Keywords Penalizadas/Clickbait (separadas por coma)",
                ", ".join(tp.get("penalty_keywords", [])),
            )
            tp["penalty_keywords"] = [
                x.strip() for x in penalty_txt.split(",") if x.strip()
            ]

        if st.button("💾 Guardar Config Colector"):
            save_toml_config(config_data)
            st.success("¡config.toml actualizado con éxito!")

        st.markdown("---")
        st.subheader("🧹 Mantenimiento del Sistema")
        with st.expander("🚨 Reinicio de Fábrica (Reset Total)", expanded=True):
            st.warning(
                "⚠️ Esta acción borrará TODOS los datos: artículos en base de datos, caché y archivos exportados. Úsalo para empezar de cero."
            )

            # Confirmation Checkbox to prevent accidental clicks
            confirm_delete = st.checkbox(
                "Confirmo que deseo vaciar TODO el sistema (Backend + Frontend)."
            )

            if st.button(
                "🧨 EJECUTAR RESET TOTAL", type="primary", disabled=not confirm_delete
            ):
                with st.spinner("Eliminando datos y reseteando caché..."):
                    try:
                        # Use the DatabaseManager for the persistent storage
                        db_man = DatabaseManager(
                            {"type": "sqlite", "path": REFINERY_DB_PATH}
                        )
                        count = db_man.clear_all_articles()

                        # Clean up export files to reflect empty state immediately
                        paths_to_clean = [
                            BASE_DIR
                            / "temp"
                            / "source"
                            / "data"
                            / "exports"
                            / "latest_articles.json",
                            NEWS_COLLECTOR_PATH
                            / "data"
                            / "exports"
                            / "latest_articles.json",
                        ]

                        for p in paths_to_clean:
                            if p.exists():
                                try:  # noqa: SIM105
                                    p.unlink()
                                except Exception:  # noqa: S110
                                    pass

                        # 2. Clear Refinery Workflow State (refinery.db)
                        # This DB tracks which files have been turned into PRs.
                        # We must wipe it so the UI allows re-processing the same content if desired.
                        refinery_db_path = NEWS_COLLECTOR_PATH / "refinery.db"
                        if refinery_db_path.exists():
                            try:
                                refinery_db_path.unlink()
                                st.success(
                                    f"✅ Estado del flujo de trabajo reiniciado ({refinery_db_path.name} eliminado)."
                                )
                            except Exception as e:
                                st.warning(
                                    f"No se pudo eliminar {refinery_db_path.name}: {e}"
                                )

                        # 3. Clean Job History & Source Metadata to force re-fetch
                        # If we don't clear this, the collector will think it just ran
                        # and skip everything (304 Not Modified or "Duplicate Job")
                        with sqlite3.connect(REFINERY_DB_PATH) as conn:
                            cursor = conn.cursor()

                            # Wipe all article data
                            tables_to_wipe = [
                                "articles",
                                "article_metrics",
                                "score_logs",
                            ]
                            for table in tables_to_wipe:
                                try:
                                    # fmt: off
                                    cursor.execute(f"DELETE FROM {table}")  # noqa: S608  # nosemgrep # nosec
                                    # fmt: on
                                    st.write(f"  - Tabla `{table}` limpiada.")
                                except Exception:  # noqa: S110, SIM105
                                    pass  # Table might not exist yet

                            # Reset Source Metadata (Force Re-fetch)
                            try:
                                cursor.execute("""
                                     UPDATE sources
                                     SET last_checked = NULL,
                                         last_successful_check = NULL,
                                         feed_etag = NULL,
                                         feed_last_modified = NULL
                                 """)
                                st.write(
                                    "  - Metadatos de fuentes reiniciados (forzando re-colección)."
                                )
                            except Exception as e:
                                st.warning(f"No se pudieron reiniciar fuentes: {e}")

                            conn.commit()

                        # Clear Streamlit Cache
                        st.cache_data.clear()

                        st.success(
                            f"✅ SISTEMA LIMPIO. {count} artículos eliminados. Caché purgada."
                        )
                        import time

                        time.sleep(2)  # Give user time to see success message
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error durante limpieza: {e}")

# --- Tab 3: Operations ---
with tab3:
    st.header("Operaciones del Pipeline")

    st.info("ℹ️ Selecciona un artículo para refinar y publicar.")
    env_vars = dict(load_secrets())
    auth_ok = require_refinery_auth(env_vars, key="auth_ops")

    # Section 1: Sync
    col_sync, col_status = st.columns([1, 2])
    with col_sync:
        # User requested to eliminate Fast Mode to ensure quality discrimination
        st.info("🧠 Modo Cognitivo Activo (Análisis Profundo)")

        dry_run_enabled = st.checkbox(
            "🧪 Test Connection (Dry Run)",
            help="Ejecutar análisis sin guardar artículos en Base de Datos.",
        )

        if st.button(
            "🔄 Sincronizar y Recolectar",
            help="Ejecutar colector de noticias y traer nuevos artículos (puede tardar unos minutos).",
        ):
            with st.spinner("Ejecutando recolección y análisis cognitivo..."):
                if not auth_ok:
                    st.warning("Autenticación requerida para sincronizar.")
                else:
                    try:
                        # Direct call to main module instead of subprocess
                        result = run_refinery(
                            fetch_only=False, fast_mode=False, dry_run=dry_run_enabled
                        )
                        if result.get("status") == "success":
                            st.success("¡Recolección Completa!")
                        else:
                            st.error("Fallo en Sincronización")
                            st.expander("Detalles del Error").write(
                                result.get("message")
                            )
                    except Exception as e:
                        st.error(f"Error: {e}")

    # Section 2: List Candidates
    # Look for the JSON file
    # We know main.py clones into temp/source
    CLONED_PATH = (
        BASE_DIR / "temp" / "source" / "data" / "exports" / "latest_articles.json"
    )
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
    # OBJECTIVE 3: Handoff Fallback (No SPOF)
    # We implement a robust loader that falls back to DB if JSON is missing or corrupt.

    candidates = []
    candidates_source = "Unknown"

    # 1. Try to load JSON
    if JSON_PATH and JSON_PATH.exists():
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "articles" in data:
                    candidates = data["articles"]
                    candidates_source = f"Export JSON ({JSON_PATH.name})"
                elif isinstance(data, list):
                    candidates = data
                    candidates_source = f"Export JSON ({JSON_PATH.name}) - Legacy List"
                else:
                    raise ValueError("Invalid JSON structure")
        except Exception as e:
            st.warning(
                f"⚠️ **Export Artifact Corrupt/Invalid**: {e}. Attempting DB Fallback..."
            )
            JSON_PATH = None  # Force fallback

    # 2. Fallback: DB Pending Items (Real Recovery)
    if not candidates:
        try:
            # Connect to DB to find pending items
            with sqlite3.connect(REFINERY_DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                # Check if articles table exists
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='articles'"
                )
                if cursor.fetchone():
                    # Fetch pending/new articles
                    # We might need to map DB columns to Article Schema
                    cursor.execute(
                        "SELECT id, title, url, source_id, published_date, collected_date FROM articles WHERE processing_status IN ('new', 'pending') ORDER BY collected_date DESC LIMIT 50"
                    )
                    rows = cursor.fetchall()
                    if rows:
                        st.info(
                            f"ℹ️ **Modo Recuperación**: Cargados {len(rows)} artículos pendientes directamente de Base de Datos."
                        )
                        candidates_source = "Direct DB Connection (Pending)"
                        for r in rows:
                            candidates.append(
                                {
                                    "id": r["id"],
                                    "title": r["title"],
                                    "url": r["url"],
                                    "source_id": r["source_id"],
                                    "published_date": r["published_date"],
                                    "summary": "Loaded from DB (Content might be fetched on demand)",
                                }
                            )
        except Exception as e:
            st.error(f"❌ Fallback DB failed: {e}")

    # 3. Last Resort: Mock Data (Dev/Test)
    if not candidates:
        data_dir = CLONED_PATH.parent.parent  # temp/source/data
        md_files = list(data_dir.glob("*.md"))
        if md_files:
            try:
                # Generate a temporary JSON for the UI to consume
                for mf in md_files:
                    candidates.append(
                        {
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
                                "cognitive_engagement_norm": 1.0,
                            },
                        }
                    )

                # Write to where the app expects it (or a temp location)
                # CLONED_PATH is .../exports/latest_articles.json
                # We will write it there so the next check passes
                CLONED_PATH.parent.mkdir(parents=True, exist_ok=True)
                import json

                with open(CLONED_PATH, "w", encoding="utf-8") as f:
                    json.dump({"articles": temp_articles}, f, indent=2)  # noqa: F821

                JSON_PATH = CLONED_PATH
                st.toast(
                    f"ℹ️ Se generó un archivo JSON temporal desde {len(md_files)} archivos MD locales.",
                    icon="🛠️",
                )
            except Exception as e:
                st.error(f"Error generando datos mock: {e}")

    # --- HANDOFF FALLBACK INTEGRATION ---
    # We use the 'candidates' list populated above (from JSON, DB, or Mock).
    if candidates:
        import json

        import pandas as pd

        try:
            refinery_db = DatabaseManager()  # Initialize using global config
            articles = candidates

            # Legacy compatibility (ensure list)
            if not isinstance(articles, list):
                articles = []

            # --- RE-SCORING LOGIC DISABLED ---
            # We trust the score coming from the collector (especially for Cognitive Mode).
            # The Admin Panel should not overwrite with default static weights.
            # ------------------------
            # ------------------------

            # UX IMPROVEMENT: Allow showing processed items
            # UX IMPROVEMENT: Allow showing processed items
            show_processed = st.checkbox(
                "Mostrar artículos procesados (Force Reprocess)", value=False
            )
            if show_processed:
                st.info(
                    "Modo 'Force Reprocess' activo: Se muestran todos los artículos."
                )

            if articles:
                refinery_db = DatabaseManager()
                available_articles = []

                filtered_count = 0
                for art in articles:
                    art_id = str(art.get("id", art.get("title")))

                    # DEBUG SPECIFIC ID
                    if art_id == "169":  # noqa: SIM102
                        # Only show debug if relevant or debug mode
                        if not show_processed:  # noqa: SIM102
                            # Keep this unobtrusive or remove it if user is tired of it
                            pass

                    if not show_processed:
                        try:
                            numeric_id = int(art_id)
                            # is_article_published is the new method in main DB
                            if refinery_db.is_article_published(numeric_id):
                                filtered_count += 1
                                continue
                        except ValueError:
                            pass  # If ID is not int, we can't check efficiently in main DB yet, or assume not processed

                        # Check .md existence is handled by is_article_published?
                        # No, is_article_published checks DB status.
                        # RefineryEngine previously checked file system.
                        # We trust DB status now.
                    available_articles.append(art)

                if filtered_count > 0:
                    st.caption(
                        f"Se ocultaron {filtered_count} artículos ya publicados."
                    )

                if not available_articles:
                    st.info("No hay artículos disponibles para procesar.")
                else:
                    st.subheader(f"Artículos Disponibles ({len(available_articles)})")

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
                        f"(Score: {row.get('score', 0):.2f})": row["id"]
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
                                st.write(f"**Resumen:** {selected_art.get('summary')}")
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
                        is_pub = False
                        try:  # noqa: SIM105
                            is_pub = refinery_db.is_article_published(int(selected_id))
                        except ValueError:
                            pass  # noqa: SIM105

                        if is_pub:
                            st.warning("⚠️ Artículo ya publicado/procesado.")

                            col_pub1, col_pub2 = st.columns(2)
                            with col_pub1:
                                if st.button(
                                    "🔄 Forzar Reprocesamiento (Sobrescribir)",
                                    key=f"reproc_{selected_id}",
                                ):
                                    with st.spinner(
                                        f"Reprocesando ID {selected_id}..."
                                    ):
                                        # ... existing logic ...
                                        # This needs refactoring to avoid duplication, but for now we copy the call logic
                                        # or we assume the main button below handles force if we allow it fall through?
                                        # No, let's keep one main action.
                                        pass

                            with col_pub2:
                                if st.button(
                                    "🗑️ Despublicar (Eliminar)",
                                    type="primary",
                                    key=f"del_{selected_id}",
                                ):
                                    with st.spinner(
                                        f"Solicitando eliminación de {selected_id}..."
                                    ):
                                        try:
                                            # Call delete_article via import
                                            # We need to import it first or use module access
                                            # We already have `run_refinery` available via importlib in admin_panel.
                                            # We need `delete_article` too.

                                            if hasattr(refinery_main, "delete_article"):
                                                del_result = (
                                                    refinery_main.delete_article(
                                                        str(selected_id)
                                                    )
                                                )
                                                if (
                                                    del_result.get("status")
                                                    == "success"
                                                ):
                                                    st.success(
                                                        "✅ Solicitud de eliminación creada."
                                                    )
                                                    st.markdown(
                                                        f"[Ver Pull Request de Eliminación]({del_result.get('pr_url')})"
                                                    )
                                                    # Update DB to un-processed?
                                                    # refinery_db.mark_processed(str(selected_id)) # No method to unmark
                                                    st.info(
                                                        "Nota: La base de datos local seguirá marcándolo como procesado hasta recibir confirmación de limpieza."
                                                    )
                                                else:
                                                    st.error(
                                                        f"Error: {del_result.get('message')}"
                                                    )
                                            else:
                                                st.error(
                                                    "Función delete_article no encontrada. Reinicia la aplicación."
                                                )
                                        except Exception as e:
                                            st.error(
                                                f"Error invocando despublicación: {e}"
                                            )

                        # Dynamic Time Estimation Helper
                        def estimate_time(art_len: int, model: str) -> str:
                            # Base speed heuristics (words per minute for 3 stages)
                            # Stage 1 (Trans), Stage 2 (Edit), Stage 3 (Meta)
                            total_words = art_len or 1000
                            # Very rough factors based on CPU inference
                            if "llama3.3" in model or "70b" in model:
                                speed_factor = 0.05  # Slow (big model)
                            elif "8b" in model:
                                speed_factor = 2.0  # Fast (medium model)
                            else:
                                speed_factor = 5.0  # Very Fast (small/tiny model)

                            est_min = int((total_words * 3) / (speed_factor * 60))
                            est_min = max(est_min, 1)  # At least 1 min

                            return f"~{est_min} mins ({model})"

                        # Standard Process Button (Always visible for force reprocessing or new items)

                        # Calculate estimate
                        content_len = len(selected_art.get("content", "").split())
                        active_model = env_vars.get("OLLAMA_MODEL", "unknown")
                        time_est = estimate_time(content_len, active_model)

                        if st.button(
                            f"✨ Refinar y Publicar (ID: {selected_id})",
                            type="primary",
                            help=f"Estimación de tiempo: {time_est}",
                        ):
                            with st.spinner(
                                f"Procesando ID {selected_id}... Esto toma {time_est} en CPU."
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
                                        processed_count = result.get(
                                            "processed_count", 0
                                        )
                                        if status == "success" and processed_count > 0:
                                            st.success(
                                                "¡Procesamiento Completo! Revisa el repo de tu web."
                                            )
                                            st.balloons()
                                        elif status == "error":
                                            st.error("Procesamiento Fallido.")
                                            st.expander("Detalles del Error").write(
                                                result.get("message")
                                            )
                                        elif status == "noop" or processed_count == 0:
                                            message = result.get(
                                                "message",
                                                "No se encontraron artículos para procesar.",
                                            )
                                            st.warning(f"Sin resultados: {message}")
                                        else:
                                            st.error("Procesamiento Fallido.")
                                            st.expander("Detalles del Error").write(
                                                result.get("message")
                                            )
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
    # Integrated Activity Monitor
    from news_collector.system.activity_monitor import ActivityMonitor

    st.markdown("### Registro de Actividad Reciente")

    # Initialize monitor
    # Note: We rely on default path resolution in ActivityMonitor, but we can pass explicit if needed.
    monitor = ActivityMonitor()
    events = monitor.get_recent_activity(limit=15)  # Show last 15 aggregated events

    from news_collector.utils.refinery_helper import has_no_activity

    if has_no_activity(events):
        st.info("ℹ️ No hay actividad reciente registrada.")
    else:
        # Custom CSS for timeline-like look (optional, keeping it simple first)
        for event in reversed(events):  # Show newest first

            # Icon & Color mapping
            icon = "🔹"
            if event.level == "ERROR":
                icon = "❌"
            elif event.level == "WARNING":
                icon = "⚠️"
            elif event.category == "Lifecycle":
                icon = "🔄"
            elif event.category == "Publishing":
                icon = "🚀"
            elif event.category == "Scoring":
                icon = "🧠"
            elif event.category == "Collection":
                icon = "📡"

            # Format relative time (approximate)
            time_label = event.timestamp_str
            if event.timestamp_dt:
                # Simple "X mins ago" logic could go here, or just show time
                time_label = event.timestamp_dt.strftime("%H:%M:%S")

            # Render
            with st.container():
                # Columns: Icon | Time | Message
                c_icon, c_time, c_msg = st.columns([0.5, 1.5, 8])
                c_icon.write(icon)
                c_time.caption(time_label)
                # Style message based on severity
                if event.level == "ERROR":
                    c_msg.error(f"[{event.category}] {event.message}")
                elif event.level == "WARNING":
                    c_msg.warning(f"[{event.category}] {event.message}")
                else:
                    # Normal info
                    c_msg.markdown(f"**[{event.category}]** {event.message}")

            st.divider()


# --- Tab 4: Analytics ---
with tab4:
    st.header("📈 Analítica del Sistema")

    try:
        # Use simple DB manager pointing to correct path with CONFIG DICT
        # Actually, global DatabaseManager() is better
        db = DatabaseManager()  # Using global config

        # 1. KPIs
        col_k1, col_k2, col_k3 = st.columns(3)

        # Stats
        stats = db.get_collection_stats(days=30)
        total_articles = sum(d["count"] for d in stats)

        with col_k1:
            st.metric("Total Artículos (30d)", total_articles)

        # Source Performance
        source_perf = db.get_source_performance()
        avg_score_overall = (
            sum(s["avg_score"] * s["article_count"] for s in source_perf)
            / total_articles
            if total_articles
            else 0
        )

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
                top_sources = sorted(
                    source_perf, key=lambda x: x["avg_score"], reverse=True
                )[:5]
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

    st.info(
        "⚠️ Aquí puedes eliminar artículos que ya han sido publicados en el repositorio destino."
    )

    env_vars = dict(load_secrets())
    if require_refinery_auth(env_vars, key="auth_cms"):
        # reuse GitHubPublisher logic from main or init new one
        import git
        from news_collector.components.publishing import GitHubPublisher

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
                            st.warning(
                                f"Error sincronizando (intentando reclonar): {e}"
                            )
                            import shutil

                            shutil.rmtree(TARGET_DIR, ignore_errors=True)
                            gh_handler.clone_repo(target_url, TARGET_DIR)
                    st.success("Repositorio actualizado y sincronizado.")
                except Exception as e:
                    st.error(f"Fallo crítico actualizando repo: {e}")

        # 2. List Files
        if TARGET_DIR.exists() and POSTS_DIR.exists():
            files = sorted(list(POSTS_DIR.glob("*.md")), reverse=True)  # noqa: C414

            if not files:
                st.info("No hay artículos en src/content/posts.")
            else:
                st.write(f"Encontrados **{len(files)}** artículos.")

                # Legacy Table Header
                h1, h2, h3, h4 = st.columns([3, 2, 1.5, 1.5])
                h1.markdown("**Título**")
                h2.markdown("**Archivo**")
                h3.markdown("**Acción 1**")
                h4.markdown("**Acción 2**")
                st.markdown("---")

                for f in files:
                    # Parse metadata (Same logic as before)
                    refinery_id = None
                    article_title = f.name
                    try:
                        content = f.read_text(encoding="utf-8", errors="ignore")
                        import re

                        match_id = re.search(
                            r'^refinery_id:\s*["\']?([^"\']+)["\']?',
                            content,
                            re.MULTILINE,
                        )
                        if match_id:
                            refinery_id = match_id.group(1)

                        match_title = re.search(
                            r"^title:\s*(.*)$", content, re.MULTILINE
                        )
                        if match_title:
                            raw = match_title.group(1).strip()
                            if (raw.startswith('"') and raw.endswith('"')) or (
                                raw.startswith("'") and raw.endswith("'")
                            ):
                                raw = raw[1:-1]
                            article_title = raw
                    except Exception:  # noqa: S110
                        pass

                    # Row Layout
                    c1, c2, c3, c4 = st.columns([3, 2, 1.5, 1.5])

                    with c1:
                        st.write(article_title)
                    with c2:
                        st.caption(f.name)
                        if refinery_id:
                            st.caption(f"ID: `{refinery_id}`")

                            # OBJECTIVE 4: Auditor Visibility

                            # OBJECTIVE 4: Auditor Visibility
                            # Check for auditor score
                            try:
                                score_path = (
                                    BASE_DIR
                                    / "data"
                                    / "article_metadata"
                                    / str(refinery_id).replace("/", "_")
                                    / "auditor_score.json"
                                )
                                if score_path.exists():
                                    with open(score_path, "r", encoding="utf-8") as af:
                                        score_data = json.load(af).get("audit", {})
                                        epistemic = float(
                                            score_data.get("epistemic_rigor_score", 0.0)
                                        )

                                        # Severity Badge
                                        color = "red"
                                        border = "🔴"
                                        if epistemic >= 8.0:
                                            color = "green"
                                            border = "🟢"
                                        elif epistemic >= 5.0:
                                            color = "orange"
                                            border = "🟡"

                                        st.markdown(
                                            f"**{border} Rigor: :{color}[{epistemic:.1f}]**"
                                        )
                                else:
                                    st.caption("⏳ No audit yet")
                            except Exception:  # noqa: S110
                                pass

                    with c3:
                        if st.button(
                            "🗑️ Despublicar",
                            width="stretch",
                        ):
                            if refinery_id:
                                # Copy-paste of delete logic
                                with st.spinner("Solicitando eliminación..."):
                                    try:
                                        if hasattr(refinery_main, "delete_article"):
                                            res = refinery_main.delete_article(
                                                str(refinery_id)
                                            )
                                            if res.get("status") == "success":
                                                st.toast("✅ PR Creado", icon="🗑️")
                                                st.markdown(
                                                    f"[Ver PR]({res.get('pr_url')})"
                                                )
                                            else:
                                                st.error(res.get("message"))
                                        else:
                                            st.error("Función no cargada")
                                    except Exception as e:
                                        st.error(str(e))
                            else:
                                st.error("Sin ID")

                    with c4:
                        if st.button(
                            "♻️ Reset",
                            key=f"btn_rst_{f.name}",
                            width="stretch",
                        ):
                            # Copy-paste of reset logic
                            try:
                                repo = git.Repo(TARGET_DIR)
                                repo.index.remove([str(f.relative_to(TARGET_DIR))])
                                f.unlink()
                                repo.index.commit(f"Deleted (Reset) {f.name}")
                                repo.remotes.origin.push()

                                db_manager = RefineryDatabaseManager(
                                    str(REFINERY_DB_PATH)
                                )
                                if refinery_id:
                                    db_manager.delete_record(refinery_id)
                                    db_manager.delete_record(f"{refinery_id}.md")
                                st.success("Reset OK")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

                    st.divider()


# --- Tab 6: Source Manager ---
with tab6:
    st.header("📡 Gestión de Fuentes RSS")

    # --- Source Health Dashboard ---
    health_data = load_source_health()
    if health_data:
        # Normalize data structure (handle 'sources' wrapper)
        if "sources" in health_data and isinstance(health_data["sources"], dict):
            health_data_sources = health_data["sources"]
            last_run_time = health_data.get("generated_at", "Unknown")
        else:
            health_data_sources = health_data
            last_run_time = "Unknown"

        st.subheader(f"🩺 Estado de Salud (Última Ejecución: {last_run_time})")

        # Metrics Calculation
        total_sources = len(health_data_sources)
        feed_ok_count = sum(
            1
            for s in health_data_sources.values()
            if isinstance(s, dict) and s.get("feed_ok")
        )
        content_ok_count = sum(
            1
            for s in health_data_sources.values()
            if isinstance(s, dict) and s.get("content_ok")
        )
        failed_count = total_sources - feed_ok_count

        success_rate = (feed_ok_count / total_sources * 100) if total_sources > 0 else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Fuentes Totales", total_sources)
        m2.metric("Success Rate (Feed)", f"{success_rate:.1f}%")
        m3.metric(
            "Feed OK",
            f"{feed_ok_count}/{total_sources}",
            delta=feed_ok_count - total_sources if failed_count > 0 else 0,
        )
        m4.metric("Content OK", f"{content_ok_count}/{total_sources}")

        if failed_count > 0:
            st.warning(f"⚠️ {failed_count} fuentes fallando")
            with st.expander("Ver Errores"):
                for source_id, data in health_data_sources.items():
                    if isinstance(data, dict) and not data.get("feed_ok"):
                        st.error(
                            f"**{source_id}** (Status: {data.get('status')}) - {data.get('last_error_details')}"
                        )

        # Detailed Health Dataframe
        with st.expander("📊 Ver Matriz de Salud Completa"):
            import pandas as pd

            health_df = pd.DataFrame.from_dict(health_data_sources, orient="index")
            # Reorder columns for readability
            cols = [
                "feed_ok",
                "content_ok",
                "content_mode",
                "articles_found",
                "articles_saved",
                "latency",
                "last_error_message",
            ]
            # Filter cols that exist
            cols = [c for c in cols if c in health_df.columns]
            st.dataframe(
                health_df[cols].style.highlight_max(
                    axis=0, subset=["latency"], color="#ffcdd2"
                ),
                # Deprecated arg replaced by width='stretch'
                width="stretch",
            )

        st.divider()
    else:
        st.info(
            "ℹ️ No hay datos de salud recientes (ejecuta el colector para generar `source_health.json`)."
        )
        st.divider()

    st.info("Modifica, agrega o deshabilita fuentes sin reiniciar el servidor.")

    # Import sources config
    import news_collector.config.sources as source_config_module

    # Reload to ensure fresh state
    source_config_module.load_sources()
    current_sources = source_config_module.ALL_SOURCES

    # 1. Main Table
    if not current_sources:
        st.warning("No se cargaron fuentes.")
    else:
        # Convert to list for dataframe
        source_list = []
        for sid, cfg in current_sources.items():
            source_list.append(
                {
                    "ID": sid,
                    "Nombre": cfg.get("name"),
                    "URL": cfg.get("url"),
                    "Credibilidad": cfg.get("credibility_score"),
                    "Categoria": cfg.get("category"),
                    "Grupo": cfg.get("_group", "Personalizado"),
                }
            )

        st.dataframe(source_list, width="stretch")

    st.divider()

    # 2. Edit / Add Form
    st.subheader("🛠️ Editar / Agregar Fuente")

    col_sel, col_act = st.columns([3, 1])
    with col_sel:
        # Select source to edit or New
        input_options = ["(Nueva Fuente)"] + list(current_sources.keys())
        selected_source_id = st.selectbox("Seleccionar Fuente", input_options)

    is_new = selected_source_id == "(Nueva Fuente)"

    # Load default data
    default_data = {}
    if not is_new:
        default_data = current_sources.get(selected_source_id, {}).copy()

    with st.form("source_editor"):
        c1, c2 = st.columns(2)
        with c1:
            new_id = st.text_input(
                "ID (Snake Case)",
                value=selected_source_id if not is_new else "",
                disabled=not is_new,
            )
            name = st.text_input("Nombre Legible", value=default_data.get("name", ""))
            url = st.text_input("URL del Feed RSS", value=default_data.get("url", ""))

        with c2:
            credibility = st.slider(
                "Score Credibilidad",
                0.0,
                1.0,
                float(default_data.get("credibility_score", 0.8)),
            )
            category = st.selectbox(
                "Categoría",
                [
                    "technology",
                    "science",
                    "medicine",
                    "space",
                    "biology",
                    "multidisciplinary",
                    "popular_science",
                    "artificial_intelligence",
                ],
                index=0,  # Should try to match existing, but selectbox needs index lookup. Simplified for now.
            )
            update_freq = st.selectbox(
                "Frecuencia Actualización",
                ["daily", "weekly", "hourly", "multiple_daily"],
                index=0,
            )

        group_tag = st.selectbox(
            "Grupo (Organización Interna)",
            [
                "ELITE_JOURNALS",
                "SCIENCE_MEDIA",
                "INSTITUTIONAL_SOURCES",
                "AI_LABS",
                "CUSTOM",
            ],
            index=1,
        )

        submit = st.form_submit_button("💾 Guardar Fuente")

        if submit:
            if not new_id:
                st.error("El ID es obligatorio.")
            else:
                # Update Dictionary
                new_entry = {
                    "name": name,
                    "url": url,
                    "credibility_score": credibility,
                    "category": category,
                    "update_frequency": update_freq,
                    "language": "en",  # Default
                    "description": "Added via UI",
                    "typical_delay": 0,
                    "_group": group_tag,
                }

                # Merge checks
                current_sources[new_id] = new_entry

                # Save to YAML
                try:
                    source_config_module.save_sources(current_sources)
                    st.success(f"Fuente '{new_id}' guardada correctamente.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error guardando: {e}")

    # Delete Action
    if not is_new:  # noqa: SIM102
        if st.button("🗑️ Eliminar Fuente Seleccionada", type="primary"):
            del current_sources[selected_source_id]
            source_config_module.save_sources(current_sources)
            st.success("Fuente eliminada.")
            st.rerun()
