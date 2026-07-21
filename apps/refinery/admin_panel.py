import hmac
import importlib.util
import json
import logging
import os
import sqlite3
import sys
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import streamlit as st

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

# from src.database import DatabaseManager as RefineryDatabaseManager # Removed legacy
from apps.refinery.published_content import (
    find_local_target_checkout,
    find_published_article_by_refinery_id,
    get_repo_head_sha,
    resolve_published_content_snapshot,
    truncate_refinery_id,
)
from news_collector.config import settings as config_settings
from news_collector.infrastructure.llm.factory import get_provider
from news_collector.logic.workflows.image_briefs import ImageBriefStore
from news_collector.logic.workflows.manual_ingest import ManualUrlIngestService
from news_collector.storage.database import DatabaseManager
from news_collector.utils.logger import get_logger
from noticiencias.config_manager import (
    Config,
    default_config_path,
    default_env_path,
    load_config,
    load_env_overrides,
    save_config,
    save_env_overrides,
)

# Alias for compatibility if legacy code relies on this name
RefineryDatabaseManager = DatabaseManager

# Configure logging with timestamps for console output
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
    force=True,
)

logger = get_logger().create_module_logger("RefineryAdminPanel")

# Page Config
st.set_page_config(
    page_title="Panel de Control Noticiencias", page_icon="🎛️", layout="wide"
)


# Premium Custom CSS Injection
def inject_custom_css():
    st.html(
        """<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
/* Reset and core fonts */
html, body, [class*="css"], .stApp, .stMarkdown, .stText, p, span, div, button, select, input, textarea {
    font-family: 'Outfit', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}
/* Restore Material Symbols font overridden by the blanket span rule above */
[data-testid="stIconMaterial"] {
    font-family: 'Material Symbols Outlined', 'Material Symbols Rounded', 'Material Icons' !important;
    font-feature-settings: 'liga' !important;
}
code, pre, [class*="mono"] {
    font-family: 'JetBrains Mono', monospace !important;
}

/* Page Background and Layout adjustments */
.stApp {
    background-color: #0d111d !important;
    color: #e2e8f0 !important;
}

/* Sidebar styling */
[data-testid="stSidebar"] {
    background-color: #090d16 !important;
    border-right: 1px solid rgba(255, 255, 255, 0.05) !important;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.3) !important;
}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    font-size: 0.95rem !important;
    color: #94a3b8 !important;
}

/* Headings styling */
h1 {
    background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800 !important;
    letter-spacing: -0.03em !important;
    padding-bottom: 0.4em !important;
}

h2, h3 {
    color: #f8fafc !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    border-bottom: none !important;
    margin-top: 1.5rem !important;
}

h4, h5, h6 {
    color: #cbd5e1 !important;
    font-weight: 600 !important;
}

/* Metric Container overrides */
[data-testid="metric-container"] {
    background: rgba(30, 41, 59, 0.45) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 16px !important;
    padding: 16px 20px !important;
    backdrop-filter: blur(10px) !important;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15) !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
[data-testid="metric-container"]:hover {
    transform: translateY(-2px) !important;
    border-color: rgba(56, 189, 248, 0.25) !important;
    box-shadow: 0 8px 30px rgba(56, 189, 248, 0.08) !important;
}

[data-testid="stMetricValue"] {
    font-size: 1.8rem !important;
    font-weight: 800 !important;
    background: linear-gradient(135deg, #38bdf8 0%, #60a5fa 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    font-weight: 600 !important;
    color: #94a3b8 !important;
}

/* Custom premium-card class for visual groupings */
.premium-card {
    background: rgba(30, 41, 59, 0.35) !important;
    border: 1px solid rgba(255, 255, 255, 0.07) !important;
    border-radius: 16px !important;
    padding: 24px !important;
    margin-bottom: 24px !important;
    backdrop-filter: blur(12px) !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2) !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.premium-card:hover {
    border-color: rgba(56, 189, 248, 0.2) !important;
    box-shadow: 0 15px 40px rgba(56, 189, 248, 0.05) !important;
}

/* Beautiful custom status info badges */
.custom-badge {
    display: inline-block;
    padding: 6px 12px;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-right: 8px;
    margin-bottom: 8px;
}
.badge-blue {
    background: rgba(56, 189, 248, 0.15);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.3);
}
.badge-red {
    background: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.3);
}
.badge-green {
    background: rgba(34, 197, 94, 0.15);
    color: #4ade80;
    border: 1px solid rgba(34, 197, 94, 0.3);
}
.badge-purple {
    background: rgba(168, 85, 247, 0.15);
    color: #c084fc;
    border: 1px solid rgba(168, 85, 247, 0.3);
}

/* Buttons styling */
.stButton button {
    background: linear-gradient(135deg, #0284c7 0%, #4f46e5 100%) !important;
    color: #ffffff !important;
    border: none !important;
    padding: 10px 24px !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 15px rgba(79, 70, 229, 0.25) !important;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    width: auto !important;
}
.stButton button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(79, 70, 229, 0.45) !important;
    background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%) !important;
}
.stButton button:active {
    transform: translateY(0px) !important;
}

/* Secondary actions reset button styling */
.stButton button[class*="secondary"] {
    background: rgba(255, 255, 255, 0.05) !important;
    color: #e2e8f0 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    box-shadow: none !important;
}
.stButton button[class*="secondary"]:hover {
    background: rgba(255, 255, 255, 0.1) !important;
    border-color: rgba(255, 255, 255, 0.2) !important;
}

/* Tab container modifications */
.stTabs [data-baseweb="tab-list"] {
    background-color: rgba(15, 23, 42, 0.3) !important;
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
    border-radius: 12px 12px 0 0 !important;
    padding: 6px 12px 0 12px !important;
    gap: 4px !important;
}

.stTabs [data-baseweb="tab"] {
    color: #94a3b8 !important;
    font-weight: 500 !important;
    font-size: 0.95rem !important;
    padding: 10px 18px !important;
    border-radius: 8px 8px 0 0 !important;
    transition: all 0.2s ease !important;
    border-bottom: none !important;
}

.stTabs [data-baseweb="tab"]:hover {
    color: #f1f5f9 !important;
    background-color: rgba(255, 255, 255, 0.04) !important;
}

.stTabs [aria-selected="true"] {
    color: #38bdf8 !important;
    background-color: rgba(30, 41, 59, 0.4) !important;
    border-bottom: 2px solid #38bdf8 !important;
    font-weight: 600 !important;
}

/* Table / Dataframe wrapper styling */
div[data-testid="stDataFrame"] {
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}

/* Custom visual progress bar */
.progress-bar-container {
    width: 100%;
    background-color: rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    margin-bottom: 12px;
    border: 1px solid rgba(255, 255, 255, 0.05);
    overflow: hidden;
}
.progress-bar-fill {
    height: 8px;
    border-radius: 8px;
    background: linear-gradient(90deg, #38bdf8 0%, #818cf8 100%);
    transition: width 0.5s ease-in-out;
}

/* Tooltip and caption styling */
.stCaption {
    color: #64748b !important;
    font-size: 0.8rem !important;
}
</style>"""
    )


inject_custom_css()

st.title("🎛️ Panel de Control Unificado Noticiencias")

# The editorial mode badge has been relocated to the persistent sidebar.


# Paths
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = default_config_path()
ENV_FILE = default_env_path()
LEGACY_REFINERY_ENV_FILE = BASE_DIR / ".env"

REFINERY_UI_TOKEN_KEY = "REFINERY_UI_TOKEN"  # noqa: S105  # noqa: S105 # nosec
REFINERY_UI_BYPASS_KEY = "REFINERY_UI_UNSAFE_ALLOW"

# Paths continued below after NEWS_COLLECTOR_PATH logic...


# --- Helper Functions ---
def load_secrets():
    return load_env_overrides(ENV_FILE)


def save_secrets(secrets_dict):
    normalized = {
        key: (None if value in ("", None) else str(value))
        for key, value in secrets_dict.items()
    }
    save_env_overrides(normalized, ENV_FILE)


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
            "Configúralo en el .env raíz del backend para habilitar acciones de publicación."
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
            if hmac.compare_digest(str(entered), str(token)):
                st.session_state["refinery_ui_authenticated"] = True
                st.success("Autenticación exitosa.")
                return True
            logger.warning("refinery.auth.failed")
            st.error("Token inválido.")
    return False


# --- Global Authentication Gate ---
# Every tab and all downstream secrets/widget/DB initialization is behind this
# boundary.  Unauthenticated sessions see only the auth prompt.
secrets = load_secrets()
if not require_refinery_auth(secrets):
    st.stop()


NEWS_COLLECTOR_PATH = PROJECT_ROOT
# Use configured DB path to ensure we wipe the correct DB
runtime_config = config_settings.refresh_runtime_config()
configured_db_path = config_settings.DATABASE_CONFIG.get("path", "refinery.db")
REFINERY_DB_PATH = NEWS_COLLECTOR_PATH / configured_db_path

if LEGACY_REFINERY_ENV_FILE.exists():
    legacy_keys = sorted(load_env_overrides(LEGACY_REFINERY_ENV_FILE).keys())
    legacy_key_text = (
        ", ".join(legacy_keys[:8]) if legacy_keys else "sin claves activas"
    )
    st.warning(
        "⚠️ Se detectó `apps/refinery/.env`, pero ya no se usa como fuente de configuración. "
        f"Migra cualquier override necesario al `.env` raíz ({ENV_FILE}). "
        f"Claves detectadas: {legacy_key_text}"
    )

for config_warning in getattr(
    getattr(runtime_config, "_metadata", None), "warnings", []
):
    st.warning(config_warning.message)


def load_toml_config():
    if not CONFIG_FILE.exists():
        st.error(f"❌ Archivo de configuración no encontrado en: `{CONFIG_FILE}`")
        st.caption(
            f"Ruta revisada: `{NEWS_COLLECTOR_PATH}`. La UI ahora usa el repo raíz como fuente única de configuración."
        )
        st.info(f"Directorio de Trabajo Actual: `{os.getcwd()}`")
        return None
    return load_config(CONFIG_FILE).model_dump(mode="python")


def save_toml_config(config_data):
    validated = Config.model_validate(config_data)
    current = load_config(CONFIG_FILE)
    validated._metadata = current._metadata
    save_config(validated, CONFIG_FILE)
    config_settings.refresh_runtime_config(validated)


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


def get_refinery_data_dir() -> Path:
    try:
        from noticiencias.config_manager import load_config

        config = load_config()
        paths = getattr(config, "paths", None)
        if isinstance(paths, dict):
            return Path(paths.get("data_dir", NEWS_COLLECTOR_PATH / "data"))
        data_dir = getattr(paths, "data_dir", NEWS_COLLECTOR_PATH / "data")
        return Path(data_dir)
    except Exception:
        return NEWS_COLLECTOR_PATH / "data"


def estimate_time(art_len: int, model: str) -> str:
    """Rough CPU estimate for the three editorial phases."""
    total_words = art_len or 1000
    model_name = (model or "").lower()
    if (
        "llama3.3" in model_name
        or "70b" in model_name
        or "32b" in model_name
        or "qwen2.5:14b" in model_name
    ):
        speed_factor = 0.05
    elif "8b" in model_name:
        speed_factor = 2.0
    else:
        speed_factor = 5.0

    est_min = int((total_words * 3) / (speed_factor * 60))
    est_min = max(est_min, 1)
    return f"~{est_min} mins ({model})"


def render_fetch_attempts(fetch_attempts: list[dict[str, Any]] | None) -> None:
    if not fetch_attempts:
        return
    with st.expander("🧪 Resumen de Métodos de Extracción", expanded=False):
        for attempt in fetch_attempts:
            method = attempt.get("method", "unknown")
            success = "✅" if attempt.get("success") else "⚠️"
            reason = attempt.get("reason", "n/a")
            content_length = attempt.get("content_length", 0)
            st.write(
                f"{success} `{method}` · motivo: `{reason}` · longitud: `{content_length}`"
            )


def render_article_processing_panel(  # noqa: C901
    selected_art: dict[str, Any] | None,
    *,
    export_path: str | None,
    auth_ok: bool,
    env_vars: dict[str, Any],
    panel_key: str,
    header: str | None = None,
    source_note: str | None = None,
    fetch_attempts: list[dict[str, Any]] | None = None,
) -> None:
    if not selected_art:
        return

    selected_id = str(selected_art.get("id", selected_art.get("title", "")))
    if not selected_id:
        return

    if header:
        st.markdown(f"### {header}")
    if source_note:
        st.caption(source_note)
    render_fetch_attempts(fetch_attempts)

    # Render candidate scoring components with custom progress bars
    def _as_float(value, default=0.0):
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    components = selected_art.get("components") or {}
    source_cred = _as_float(components.get("source_credibility"))
    recency = _as_float(components.get("recency"))
    quality = _as_float(components.get("content_quality"))
    engagement = _as_float(
        components.get(
            "engagement_potential", components.get("cognitive_engagement_norm")
        )
    )
    overall_score = _as_float(selected_art.get("score"))

    st.markdown(
        f"""
    <div class="premium-card">
        <h4 style="margin-top:0; color:#38bdf8;">🎯 Puntuación de Relevancia: {overall_score:.2f}</h4>
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #cbd5e1; margin-bottom: 4px;">
                <span>Credibilidad de Fuente</span>
                <span>{source_cred * 100:.1f}%</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: {source_cred * 100:.1f}%; background: linear-gradient(90deg, #38bdf8 0%, #60a5fa 100%);"></div>
            </div>
        </div>
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #cbd5e1; margin-bottom: 4px;">
                <span>Recencia / Frescura</span>
                <span>{recency * 100:.1f}%</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: {recency * 100:.1f}%; background: linear-gradient(90deg, #818cf8 0%, #6366f1 100%);"></div>
            </div>
        </div>
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #cbd5e1; margin-bottom: 4px;">
                <span>Calidad de Contenido</span>
                <span>{quality * 100:.1f}%</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: {quality * 100:.1f}%; background: linear-gradient(90deg, #c084fc 0%, #a855f7 100%);"></div>
            </div>
        </div>
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #cbd5e1; margin-bottom: 4px;">
                <span>Potencial de Engagement</span>
                <span>{engagement * 100:.1f}%</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: {engagement * 100:.1f}%; background: linear-gradient(90deg, #34d399 0%, #10b981 100%);"></div>
            </div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    with st.expander("📄 Revisar Resumen del Artículo", expanded=False):
        st.write(f"**Título:** {selected_art.get('title')}")
        st.write(f"**Resumen:** {selected_art.get('summary')}")
        if selected_art.get("url"):
            st.write(f"**URL:** {selected_art.get('url')}")

    if selected_art.get("image_url"):
        st.image(selected_art.get("image_url"), caption="Imagen Extraída", width=300)

    with st.expander("🎨 Configuración Visual / Caché", expanded=True):
        visual_analysis_enabled = st.checkbox(
            "Activar Análisis Visual",
            value=True,
            help="Generar categorías y prompts para imágenes.",
            key=f"visual_analysis_{panel_key}_{selected_id}",
        )

        st.markdown("---")
        if st.button(
            "🧹 Limpiar Caché IA",
            key=f"clear_cache_{panel_key}_{selected_id}",
            help="Elimina el texto generado previamente para este artículo (traducciones/ediciones parciales) forzando que la IA genere el contenido desde cero.",
        ):
            try:
                import re

                safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", selected_id)
                count = 0
                cache_dirs = [
                    NEWS_COLLECTOR_PATH / "data" / "cache" / "editor",
                    NEWS_COLLECTOR_PATH
                    / "temp"
                    / "source"
                    / "data"
                    / "cache"
                    / "editor",
                ]

                for cache_dir in cache_dirs:
                    if cache_dir.exists():
                        for file_path in cache_dir.glob(f"{safe_id}_*.txt"):
                            file_path.unlink()
                            count += 1

                if count > 0:
                    st.success(f"✅ Caché eliminada ({count} archivos).")
                else:
                    st.info(
                        "ℹ️ No se encontraron archivos de caché para este artículo."
                    )
            except Exception as exc:
                st.error(f"Error al limpiar caché: {exc}")

    refinery_db = DatabaseManager()
    is_pub = False
    with suppress(ValueError):
        is_pub = refinery_db.is_article_published(int(selected_id))

    if is_pub:
        st.error(
            "⛔ Artículo ya publicado. Usa 'Forzar Reprocesamiento' si necesitas sobrescribir."
        )

        col_pub1, col_pub2 = st.columns(2)
        with col_pub1:
            if st.button(
                "🔄 Forzar Reprocesamiento (Sobrescribir)",
                key=f"reproc_{panel_key}_{selected_id}",
                disabled=st.session_state.get("op_in_progress", False),
            ):
                st.session_state["op_in_progress"] = True
                try:
                    with st.spinner(f"Reprocesando ID {selected_id}..."):
                        if not auth_ok:
                            st.warning("Autenticación requerida para publicar.")
                        else:
                            skip_flag = not visual_analysis_enabled
                            result = run_refinery(
                                process_id=str(selected_id),
                                skip_visuals=skip_flag,
                                export_path=str(export_path) if export_path else None,
                            )
                            status = result.get("status")
                            if (
                                status == "success"
                                and result.get("processed_count", 0) > 0
                            ):
                                st.success("¡Reprocesamiento Completo!")
                            elif status == "error":
                                st.error("Reprocesamiento Fallido.")
                                st.expander("Detalles del Error").write(
                                    result.get("message")
                                )
                            else:
                                st.warning(
                                    f"Sin resultados: {result.get('message', 'Nada procesado.')}"
                                )
                finally:
                    st.session_state["op_in_progress"] = False

        with col_pub2:
            if st.button(
                "🗑️ Despublicar (Eliminar)",
                type="primary",
                key=f"del_{panel_key}_{selected_id}",
                disabled=st.session_state.get("op_in_progress", False),
            ):
                with st.spinner(f"Solicitando eliminación de {selected_id}..."):
                    try:
                        if hasattr(refinery_main, "delete_article"):
                            del_result = refinery_main.delete_article(str(selected_id))
                            if del_result.get("status") == "success":
                                st.success("✅ Solicitud de eliminación creada.")
                                st.markdown(
                                    f"[Ver Pull Request de Eliminación]({del_result.get('pr_url')})"
                                )
                                st.info(
                                    "Nota: La base de datos local seguirá marcándolo como procesado hasta recibir confirmación de limpieza."
                                )
                            else:
                                st.error(f"Error: {del_result.get('message')}")
                        else:
                            st.error(
                                "Función delete_article no encontrada. Reinicia la aplicación."
                            )
                    except Exception as exc:
                        st.error(f"Error invocando despublicación: {exc}")
        return

    content_len = (
        len(str(selected_art.get("content", "")).split()) if selected_art else 1000
    )
    active_model = env_vars.get("OLLAMA_MODEL", "unknown")
    time_est = estimate_time(content_len, active_model)

    if st.button(
        f"✨ Refinar y Publicar (ID: {selected_id})",
        type="primary",
        help=f"Estimación de tiempo: {time_est}",
        key=f"process_{panel_key}_{selected_id}",
        disabled=st.session_state.get("op_in_progress", False),
    ):
        st.session_state["op_in_progress"] = True
        try:
            with st.spinner(
                f"Procesando ID {selected_id}... Esto toma {time_est} en CPU."
            ):
                if not auth_ok:
                    st.warning("Autenticación requerida para publicar.")
                else:
                    try:
                        skip_flag = not visual_analysis_enabled
                        result = run_refinery(
                            process_id=str(selected_id),
                            skip_visuals=skip_flag,
                            export_path=str(export_path) if export_path else None,
                        )

                        status = result.get("status")
                        processed_count = result.get("processed_count", 0)
                        if status == "success" and processed_count > 0:
                            st.success(
                                "¡Procesamiento Completo! Revisa el repo de tu web."
                            )
                            st.balloons()
                        elif status == "error":
                            st.error("Procesamiento Fallido.")
                            detail = result.get("message")
                            if result.get("error_code"):
                                detail = f"[{result.get('error_code')}] {detail}"
                            st.expander("Detalles del Error").write(detail)
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
                    except Exception as exc:
                        st.error(f"Error crítico de ejecución: {exc}")
        finally:
            st.session_state["op_in_progress"] = False


# --- Sidebar, Global status and Tabs ---


@st.cache_data(ttl=600)
def cached_fetch_pages_deploy_health(
    target_repo_url: str, current_repo_sha: str | None, github_token: str
) -> Any:
    try:
        from apps.refinery.published_content import fetch_pages_deploy_health

        return fetch_pages_deploy_health(
            target_repo_url=target_repo_url,
            current_repo_sha=current_repo_sha,
            github_token=github_token,
        )
    except Exception:
        return None


# Load global configuration and secrets
global_config_data = load_toml_config() or {}
global_secrets = dict(load_secrets())
global_ollama_cfg = global_config_data.get("ollama", {})
global_current_api = global_ollama_cfg.get(
    "api_url", "http://localhost:11434/api/generate"
)

# Resolve active provider for status display
global_active_provider = None
with suppress(Exception):
    global_active_provider = get_provider(
        config=config_settings.refresh_runtime_config(),
        api_url=global_current_api,
        timeout=5,
    )

global_provider_type = (
    type(global_active_provider).__name__ if global_active_provider else "NoneType"
)
if (
    global_provider_type == "FallbackProvider"
    and hasattr(global_active_provider, "providers")
    and global_active_provider.providers
):
    global_active_provider = global_active_provider.providers[0]
    global_provider_type = (
        type(global_active_provider).__name__ if global_active_provider else "NoneType"
    )

global_provider_name = "Ollama (Local)"
global_provider_model = global_ollama_cfg.get("model", "qwen2.5:32b")
global_status_dot = "🟢"
if global_active_provider:
    if global_provider_type == "NvidiaProvider":
        global_provider_name = "NVIDIA NIM"
        global_provider_model = getattr(global_active_provider, "model", "N/A")
    elif global_provider_type == "GeminiProvider":
        global_provider_name = "Gemini"
        global_provider_model = getattr(global_active_provider, "model", "N/A")
else:
    global_status_dot = "🔴"

# Database check
db_size_mb = 0.0
db_exists = False
try:
    if REFINERY_DB_PATH.exists():
        db_size_mb = REFINERY_DB_PATH.stat().st_size / (1024 * 1024)
        db_exists = True
except Exception as e:
    logging.debug("Could not determine DB stats: %s", e)
db_status = "🟢 Activa" if db_exists else "🔴 Inexistente"
db_path_str = REFINERY_DB_PATH.name if db_exists else "N/A"

# Repo Branch & Commit info
collector_branch = "unknown"
collector_sha = "unknown"
try:
    import git

    repo = git.Repo(PROJECT_ROOT)
    collector_branch = repo.active_branch.name
    collector_sha = repo.head.commit.hexsha[:7]
except Exception as e:
    logging.debug("Could not determine collector Git stats: %s", e)

target_url = global_secrets.get("TARGET_REPO_URL", "")
target_branch = "unknown"
target_sha = "unknown"
target_dir = BASE_DIR / "temp" / "target"
try:
    local_checkout = find_local_target_checkout(
        target_url,
        collector_repo_root=PROJECT_ROOT,
    )
    if local_checkout and local_checkout.exists():
        target_repo = git.Repo(local_checkout)
        target_branch = target_repo.active_branch.name
        target_sha = target_repo.head.commit.hexsha[:7]
    elif target_dir.exists():
        target_repo = git.Repo(target_dir)
        target_branch = target_repo.active_branch.name
        target_sha = target_repo.head.commit.hexsha[:7]
except Exception as e:
    logging.debug("Could not determine target Git stats: %s", e)

# Pages deploy health
global_deploy_health = None
if target_sha and target_sha != "unknown":
    global_deploy_health = cached_fetch_pages_deploy_health(
        target_repo_url=target_url,
        current_repo_sha=target_sha,
        github_token=global_secrets.get("GITHUB_TOKEN", ""),
    )

deploy_status_html = ""
if global_deploy_health:
    conclusion = global_deploy_health.latest_run_conclusion
    if conclusion == "success":
        deploy_status_html = (
            '<br/>Deploy Pages: <b style="color: #4ade80;">🟢 Exitoso</b>'
        )
    elif conclusion == "failure":
        deploy_status_html = (
            '<br/>Deploy Pages: <b style="color: #f87171;">🔴 Fallido</b>'
        )
    elif conclusion:
        deploy_status_html = f'<br/>Deploy Pages: <b style="color: #fbbf24;">🟡 {conclusion.capitalize()}</b>'
    else:
        deploy_status_html = (
            '<br/>Deploy Pages: <b style="color: #94a3b8;">⚪ En progreso</b>'
        )

# Draw persistent sidebar
with st.sidebar:
    st.markdown("## 🎛️ Refinería Noticiencias")

    # 1. Editorial Mode Card
    try:
        from news_collector.editorial.policy import EditorialPolicy

        sys_config = config_settings.refresh_runtime_config()
        editorial_mode = getattr(sys_config.app, "editorial_mode", "standard")
        policy = EditorialPolicy.from_mode(editorial_mode)

        mode_color = "#38bdf8"  # blue/standard
        if policy.mode == "strict":
            mode_color = "#f87171"  # red
        elif policy.mode == "velocity":
            mode_color = "#4ade80"  # green

        st.markdown(
            f"""
            <div style="padding: 14px; border-radius: 12px; background-color: rgba(30, 41, 59, 0.45); border: 1px solid {mode_color}; margin-bottom: 16px;">
                <h4 style="margin:0; color: {mode_color};">🛡️ Modo Editorial: {policy.mode.upper()}</h4>
                <div style="font-size: 0.8rem; margin-top: 8px; color: #94a3b8;">
                    Umbral Crítico: <b>{policy.critic_threshold}</b><br/>
                    Umbral Auditor: <b>{policy.auditor_threshold}</b><br/>
                    Advertencias: <b>{"Sí" if policy.require_caveats else "No"}</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    except Exception as e:
        st.error(f"Error cargando política editorial: {e}")

    # 2. Active AI Engine Card
    st.markdown(
        f"""
        <div style="padding: 14px; border-radius: 12px; background-color: rgba(30, 41, 59, 0.45); border: 1px solid rgba(255, 255, 255, 0.08); margin-bottom: 16px;">
            <h4 style="margin:0; color: #f8fafc;">🤖 Motor de IA {global_status_dot}</h4>
            <div style="font-size: 0.8rem; margin-top: 8px; color: #94a3b8;">
                Proveedor: <b>{global_provider_name}</b><br/>
                Modelo: <code>{global_provider_model}</code>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 3. Database status
    st.markdown(
        f"""
        <div style="padding: 14px; border-radius: 12px; background-color: rgba(30, 41, 59, 0.45); border: 1px solid rgba(255, 255, 255, 0.08); margin-bottom: 16px;">
            <h4 style="margin:0; color: #f8fafc;">💾 Base de Datos</h4>
            <div style="font-size: 0.8rem; margin-top: 8px; color: #94a3b8;">
                Estado: <b>{db_status}</b><br/>
                Archivo: <code>{db_path_str}</code><br/>
                Tamaño: <b>{db_size_mb:.2f} MB</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 4. Repo Status Card
    st.markdown(
        f"""
        <div style="padding: 14px; border-radius: 12px; background-color: rgba(30, 41, 59, 0.45); border: 1px solid rgba(255, 255, 255, 0.08); margin-bottom: 16px;">
            <h4 style="margin:0; color: #f8fafc;">📦 Repositorios</h4>
            <div style="font-size: 0.8rem; margin-top: 8px; color: #94a3b8;">
                <b>Colector (Backend):</b><br/>
                Rama: <code>{collector_branch}</code><br/>
                SHA: <code>{collector_sha}</code>
                <hr style="margin: 8px 0; border: none; border-top: 1px solid rgba(255,255,255,0.08);"/>
                <b>Sitio Web (Frontend):</b><br/>
                Rama: <code>{target_branch}</code><br/>
                SHA: <code>{target_sha}</code>{deploy_status_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# --- Consolidated Tabs ---
tab_escritorio, tab_imagenes, tab_publicado, tab_fuentes, tab_prompts, tab_config = (
    st.tabs(
        [
            "🏠 Escritorio (Curation Desk)",
            "🖼️ Cola de Imágenes (Image Queue)",
            "🚀 Contenido Publicado (Live CMS & Analytics)",
            "📡 Gestión de Fuentes (Source Manager)",
            "🧠 Prompts (Prompt Lab)",
            "⚙️ Configuración (Settings & Logs)",
        ]
    )
)

tab3 = tab_escritorio
tab_images = tab_imagenes
tab5 = tab_publicado
tab4 = tab_publicado
tab6 = tab_fuentes
tab_prompts = tab_prompts
tab1 = tab_config
tab2 = tab_config

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

    # Pre-resolve stage models from config so col2 widgets can reference them
    # regardless of which provider branch is selected in col1.
    _pre_ollama_cfg = config_data.get("ollama", {})
    _pre_base = _pre_ollama_cfg.get("model", "qwen2.5:32b")
    r_trans = _pre_ollama_cfg.get("translator_model") or _pre_base
    r_edit = _pre_ollama_cfg.get("editor_model") or _pre_base
    r_head = _pre_ollama_cfg.get("headlines_model") or _pre_base

    with col1:
        st.subheader("🤖 Configuración de Modelos")

        # ── Helpers ──────────────────────────────────────────────────────────

        def get_idx(options, value, default=0):
            try:
                return options.index(value)
            except ValueError:
                return default

        def is_heavy_model(m_name):
            if not m_name:
                return False
            m_lower = m_name.lower()
            return any(
                tok in m_lower for tok in ("14b", "32b", "27b", "70b", "mixtral")
            )

        # ── Detect currently active provider (without side-effects) ──────────
        ollama_cfg = config_data.get("ollama", {})
        current_api = ollama_cfg.get("api_url", "http://localhost:11434/api/generate")

        _active_provider = None
        with suppress(Exception):
            _active_provider = get_provider(
                config=config_settings.refresh_runtime_config(),
                api_url=current_api,
                timeout=5,
            )

        _active_provider_type = (
            type(_active_provider).__name__ if _active_provider else "NoneType"
        )
        if (
            _active_provider_type == "FallbackProvider"
            and hasattr(_active_provider, "providers")
            and _active_provider.providers
        ):
            _active_provider = _active_provider.providers[0]
            _active_provider_type = (
                type(_active_provider).__name__ if _active_provider else "NoneType"
            )

        _active_is_nvidia = _active_provider_type == "NvidiaProvider"
        _active_is_gemini = _active_provider_type == "GeminiProvider"
        _active_is_cloud = _active_is_nvidia or _active_is_gemini

        # ── Top-level provider type selector ─────────────────────────────────
        # Initialise session default from the actual active provider so the
        # page opens in the correct section on first load.
        if "provider_mode" not in st.session_state:
            st.session_state["provider_mode"] = (
                "☁️ Cloud (NVIDIA / Gemini)"
                if _active_is_cloud
                else "🖥️ Local (Ollama)"
            )

        provider_mode = st.radio(
            "Tipo de proveedor",
            options=["☁️ Cloud (NVIDIA / Gemini)", "🖥️ Local (Ollama)"],
            index=(
                0
                if st.session_state["provider_mode"] == "☁️ Cloud (NVIDIA / Gemini)"
                else 1
            ),
            horizontal=True,
            key="provider_mode",
            help="Elige el tipo de proveedor LLM. El proveedor activo depende de las API keys configuradas.",
        )

        st.markdown("---")

        # ════════════════════════════════════════════════════════════════════
        # CLOUD BRANCH
        # ════════════════════════════════════════════════════════════════════
        if provider_mode == "☁️ Cloud (NVIDIA / Gemini)":

            # Active provider notice
            if _active_is_nvidia:
                st.success(
                    f"🚀 **Proveedor Activo: NVIDIA NIM** — `{_active_provider.model}`"
                )
            elif _active_is_gemini:
                st.info(
                    f"✨ **Proveedor Activo: Gemini** — `{getattr(_active_provider, 'model', 'N/A')}`"
                )
            else:
                st.warning(
                    "⚠️ Ningún proveedor cloud está activo actualmente. "
                    "Configura `NOTICIENCIAS__NVIDIA__API_KEY` o `NOTICIENCIAS__GEMINI__API_KEY` en el `.env`."
                )

            # Sub-selector: NVIDIA vs Gemini
            cloud_choice = st.radio(
                "Proveedor cloud",
                options=["🚀 NVIDIA NIM", "✨ Gemini"],
                horizontal=True,
                key="cloud_provider_choice",
            )

            st.markdown("---")

            if cloud_choice == "🚀 NVIDIA NIM":
                # ── NVIDIA settings ───────────────────────────────────────
                st.markdown("#### NVIDIA NIM")
                config_data.setdefault("nvidia", {})
                nvidia_cfg = config_data["nvidia"]

                _nvidia_model_options = [
                    "qwen/qwen3-next-80b-a3b-instruct",
                    "meta/llama-3.1-70b-instruct",
                    "meta/llama-3.3-70b-instruct",
                    "mistralai/mistral-large-2-instruct",
                    "mistralai/mixtral-8x22b-instruct-v0.1",
                    "google/gemma-3-27b-it",
                    "microsoft/phi-4",
                    "deepseek-ai/deepseek-r1",
                ]
                _current_nvidia_model = nvidia_cfg.get(
                    "model", "qwen/qwen3-next-80b-a3b-instruct"
                )
                _nvidia_model_sel = st.selectbox(
                    "Modelo NVIDIA NIM",
                    options=_nvidia_model_options,
                    index=get_idx(_nvidia_model_options, _current_nvidia_model),
                    help="ID del modelo en https://build.nvidia.com/models",
                    key="nvidia_model_sel",
                )
                config_data["nvidia"]["model"] = _nvidia_model_sel

                _nvidia_maxtok = st.number_input(
                    "Max tokens",
                    min_value=256,
                    max_value=32768,
                    value=int(nvidia_cfg.get("max_tokens", 4096)),
                    step=256,
                    key="nvidia_max_tokens",
                )
                config_data["nvidia"]["max_tokens"] = _nvidia_maxtok

                if st.button("💾 Guardar configuración NVIDIA", key="save_nvidia"):
                    save_toml_config(config_data)
                    st.success("Configuración NVIDIA guardada.")
                    st.rerun()

                st.markdown("---")
                st.markdown("##### 🔍 Resumen de Etapas")
                c_r1, c_r2, c_r3 = st.columns(3)
                c_r1.metric("1. Traductor", _nvidia_model_sel, delta="Cloud")
                c_r2.metric("2. Editor", _nvidia_model_sel, delta="Cloud")
                c_r3.metric("3. Titulares", _nvidia_model_sel, delta="Cloud")

            else:
                # ── Gemini settings ───────────────────────────────────────
                st.markdown("#### Gemini")
                config_data.setdefault("gemini", {})
                gemini_cfg = config_data["gemini"]

                _gemini_model_options = [
                    "gemini-2.5-flash",
                    "gemini-2.5-pro",
                    "gemini-2.0-flash",
                    "gemini-1.5-pro",
                    "gemini-1.5-flash",
                    "gemma-4-31b-it",
                ]
                _current_gemini_model = gemini_cfg.get("model", "gemini-2.5-flash")
                _gemini_model_sel = st.selectbox(
                    "Modelo Gemini",
                    options=_gemini_model_options,
                    index=get_idx(_gemini_model_options, _current_gemini_model),
                    key="gemini_model_sel",
                )
                config_data["gemini"]["model"] = _gemini_model_sel

                if st.button("💾 Guardar configuración Gemini", key="save_gemini"):
                    save_toml_config(config_data)
                    st.success("Configuración Gemini guardada.")
                    st.rerun()

                st.markdown("---")
                st.markdown("##### 🔍 Resumen de Etapas")
                c_r1, c_r2, c_r3 = st.columns(3)
                c_r1.metric("1. Traductor", _gemini_model_sel, delta="Cloud")
                c_r2.metric("2. Editor", _gemini_model_sel, delta="Cloud")
                c_r3.metric("3. Titulares", _gemini_model_sel, delta="Cloud")

        # ════════════════════════════════════════════════════════════════════
        # LOCAL (OLLAMA) BRANCH
        # ════════════════════════════════════════════════════════════════════
        else:
            if _active_is_cloud:
                st.warning(
                    "⚠️ Un proveedor cloud está activo ahora mismo. "
                    "Estos ajustes se usarán cuando no haya API key cloud configurada."
                )
            else:
                st.success(
                    f"🖥️ **Proveedor Activo: Ollama (Local)** — "
                    f"`{getattr(_active_provider, 'model', 'N/A') if _active_provider else 'N/A'}`"
                )

            # Endpoint
            new_api_url = st.text_input(
                "Endpoint de Ollama",
                current_api,
                key="ollama_api_url",
            )
            config_data.setdefault("ollama", {})
            config_data["ollama"]["api_url"] = new_api_url

            # Fetch Ollama local model list (only when Ollama is actually active)
            available_models: list[str] = []
            if (
                not _active_is_cloud
                and _active_provider
                and hasattr(_active_provider, "list_models")
            ):
                with suppress(Exception):
                    available_models = _active_provider.list_models()

            _ollama_base_options = [
                "qwen2.5:32b",
                "qwen2.5:14b",
                "llama3.2:latest",
                "mistral:latest",
                "phi4:latest",
            ]
            model_options = (
                available_models if available_models else _ollama_base_options
            )

            # Base model
            current_base = ollama_cfg.get("model", "qwen2.5:32b")
            if is_heavy_model(current_base):
                st.warning(
                    f"⚠️ El modelo base `{current_base}` requiere mucha RAM. "
                    "Considera `llama3.2:latest` en máquinas sin GPU."
                )

            base_model_sel = st.selectbox(
                "Modelo Base (Fallback)",
                options=model_options,
                index=get_idx(model_options, current_base),
                help="Modelo usado cuando una fase no tiene override explícito.",
                key="ollama_base_model",
            )
            config_data["ollama"]["model"] = base_model_sel

            # Configuration Summary
            st.markdown("##### 🔍 Resumen de Etapas")
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

            # ── Presets ───────────────────────────────────────────────────
            st.markdown("#### ⚡ Presets (Atajos)")
            st.caption("Aplica una configuración recomendada para todas las fases.")
            col_p1, col_p2, col_p3 = st.columns(3)

            if col_p1.button(
                "🚀 Producción (CPU)",
                help="Llama 3.2 en todo — sin GPU requerida.",
            ):
                for k in (
                    "model",
                    "translator_model",
                    "editor_model",
                    "headlines_model",
                ):
                    config_data["ollama"][k] = "llama3.2:latest"
                save_toml_config(config_data)
                st.rerun()

            if col_p2.button(
                "⚖️ Calidad (GPU)",
                help="Qwen 2.5 14B — requiere GPU.",
            ):
                config_data["ollama"]["model"] = "qwen2.5:14b"
                config_data["ollama"]["translator_model"] = "qwen2.5:14b"
                config_data["ollama"]["editor_model"] = "qwen2.5:14b"
                config_data["ollama"]["headlines_model"] = "llama3.2:latest"
                save_toml_config(config_data)
                st.rerun()

            if col_p3.button(
                "↺ Reset a Base",
                help="Elimina overrides por fase — usa Modelo Base para todo.",
            ):
                for k in ("translator_model", "editor_model", "headlines_model"):
                    config_data["ollama"].pop(k, None)
                save_toml_config(config_data)
                st.rerun()

            st.markdown("---")

            # ── Manual per-phase overrides ────────────────────────────────
            st.markdown("#### 🛠️ Override por Fase")

            default_label = f"(Default: {base_model_sel})"
            phase_options = [default_label] + model_options

            for cfg_key, label in [
                ("translator_model", "1. Traductor Científico"),
                ("editor_model", "2. Editor Periodístico"),
                ("headlines_model", "3. Generador de Titulares"),
            ]:
                curr_val = ollama_cfg.get(cfg_key)
                sel_idx = 0
                if curr_val and curr_val in model_options:
                    sel_idx = model_options.index(curr_val) + 1

                sel = st.selectbox(
                    label,
                    options=phase_options,
                    index=sel_idx,
                    key=f"sel_{cfg_key}",
                )
                if sel == default_label:
                    config_data["ollama"].pop(cfg_key, None)
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

        st.caption(
            f"Ruta backend activa: `{NEWS_COLLECTOR_PATH}`. La UI ya no guarda `NEWS_COLLECTOR_PATH` en un `.env` separado."
        )

        st.markdown("##### 🔐 Secretos (.env)")

        _gh_val = st.text_input(
            "Token de GitHub",
            value="",
            type="password",
            help="Dejar en blanco para conservar el valor existente.",
        )
        if _gh_val:
            secrets["GITHUB_TOKEN"] = _gh_val
        elif st.checkbox("🗑️ Eliminar Token de GitHub", key="clear_gh_token"):
            secrets["GITHUB_TOKEN"] = ""

        _ui_val = st.text_input(
            "Token UI Refinery",
            value="",
            type="password",
            help="Dejar en blanco para conservar el valor existente. Requerido para ejecutar sincronizacion y publicar.",
        )
        if _ui_val:
            secrets[REFINERY_UI_TOKEN_KEY] = _ui_val
        elif st.checkbox("🗑️ Eliminar Token UI", key="clear_ui_token"):
            secrets[REFINERY_UI_TOKEN_KEY] = ""
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
    st.header("📝 Prompts Editoriales del Sistema")
    st.info(
        "Personaliza las instrucciones fundamentales que rigen el comportamiento de la IA en cada fase del pipeline editorial."
    )

    # Path to prompts.yaml
    PROMPTS_YAML_PATH = NEWS_COLLECTOR_PATH / "config" / "prompts.yaml"

    import yaml

    current_prompts: Dict[str, Any] = {}
    if PROMPTS_YAML_PATH.exists():
        try:
            with open(PROMPTS_YAML_PATH, "r", encoding="utf-8") as f_yaml:
                current_prompts = yaml.safe_load(f_yaml) or {}
        except Exception as e:
            st.error(f"Error leyendo prompts.yaml: {e}")
    else:
        st.warning(
            "⚠️ No se encontró config/prompts.yaml. Se crearán valores por defecto al guardar."
        )

    st.markdown("### ✨ Configuración Activa (v2.0)")

    col_trans, col_edit = st.columns(2)

    with col_trans:
        st.markdown("##### 1. Traductor Científico (Fase 1)")
        trans_sys = current_prompts.get("translator", {}).get("system", "")
        new_trans_sys = st.text_area(
            "Instrucciones de Traducción",
            value=trans_sys,
            height=450,
            key="prompt_trans",
        )

    with col_edit:
        st.markdown("##### 2. Editor Periodístico (Fase 2)")
        edit_sys = current_prompts.get("editor", {}).get("system", "")
        new_edit_sys = st.text_area(
            "Instrucciones de Edición y Adaptación",
            value=edit_sys,
            height=450,
            key="prompt_edit",
        )

    st.markdown("##### 3. Generador de Titulares (Fase 3)")
    head_sys = current_prompts.get("headline", {}).get("system", "")
    new_head_sys = st.text_area(
        "Instrucciones de Titulares", value=head_sys, height=150, key="prompt_head"
    )

    col_btn, empty_col = st.columns([1, 3])
    with col_btn:
        if st.button("💾 Guardar Prompts (YAML)", type="primary"):
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
                        updated_prompts,
                        f,
                        allow_unicode=True,
                        default_flow_style=False,
                        sort_keys=False,
                    )
                st.success("¡Prompts actualizados correctamente!")

                # Refresh variables to update UI immediately
                trans_sys = new_trans_sys
                edit_sys = new_edit_sys
                head_sys = new_head_sys

            except Exception as e:
                st.error(f"Error guardando prompts: {e}")

    st.markdown("---")
    with st.expander(
        "🕰️ Ver Prompts de Respaldo (Versión 1.0 - Pre-Auditoría)", expanded=False
    ):
        st.caption(
            "Estos son los prompts originales por si necesitas consultar cómo operaba el sistema anteriormente."
        )
        col_v1_trans, col_v1_edit = st.columns(2)
        with col_v1_trans:
            st.markdown("##### Traductor v1")

            trans_v1_content = current_prompts.get("translator_v1", {}).get("system")
            if not trans_v1_content:
                # Intento de lectura pura de línea si yaml_safe_load falló parcial
                trans_v1_content = "No disponible. Revisa config/prompts.yaml"

            st.code(trans_v1_content, language="markdown")
        with col_v1_edit:
            st.markdown("##### Editor v1")
            edit_v1_content = current_prompts.get("editor_v1", {}).get("system")
            if not edit_v1_content:
                edit_v1_content = "No disponible. Revisa config/prompts.yaml"
            st.code(edit_v1_content, language="markdown")

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
                        # B-06 / F-0029: All DELETEs + UPDATE wrapped in a single
                        # transaction so partial failure leaves DB unchanged.
                        with sqlite3.connect(REFINERY_DB_PATH) as conn:
                            cursor = conn.cursor()
                            try:
                                # Pre-check which tables exist to avoid expected errors
                                cursor.execute(
                                    "SELECT name FROM sqlite_master WHERE type='table'"
                                )
                                existing_tables = {row[0] for row in cursor.fetchall()}

                                # Wipe all article data
                                tables_to_wipe = [
                                    "articles",
                                    "article_metrics",
                                    "score_logs",
                                ]
                                for table in tables_to_wipe:
                                    if table in existing_tables:
                                        # fmt: off
                                        cursor.execute(f"DELETE FROM {table}")  # noqa: S608  # nosemgrep # nosec
                                        # fmt: on
                                        st.write(f"  - Tabla `{table}` limpiada.")

                                # Reset Source Metadata (Force Re-fetch)
                                if "sources" in existing_tables:
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

                                conn.commit()
                            except Exception:
                                conn.rollback()
                                raise

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

    st.markdown("---")
    st.markdown("### 📊 Registro de Actividad Reciente")
    # Integrated Activity Monitor
    from news_collector.system.activity_monitor import ActivityMonitor

    # Initialize monitor
    # Note: We rely on default path resolution in ActivityMonitor, but we can pass explicit if needed.
    monitor = ActivityMonitor()
    events = monitor.get_recent_activity(limit=15)  # Show last 15 aggregated events

    from news_collector.utils.refinery_helper import has_no_activity

    if has_no_activity(events):
        st.info("ℹ️ No hay actividad reciente registrada.")
    else:
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
                    c_msg.markdown(f"**[{event.category}]** {event.message}")

            st.divider()

# --- Tab Images: Editorial Image Briefs ---
with tab_images:
    st.header("🖼️ Cola Editorial de Imágenes")
    st.caption(
        "Cuando una nota no tiene una imagen utilizable, Refinery crea un brief estructurado aquí en lugar de publicar con un placeholder."
    )

    image_brief_store = ImageBriefStore(get_refinery_data_dir())
    briefs = image_brief_store.list_briefs()

    if not briefs:
        st.info(
            "No hay briefs pendientes. Los próximos artículos sin imagen válida aparecerán aquí."
        )
    else:
        status_filter = st.selectbox(
            "Filtrar por estado",
            options=[
                "Todos",
                "needs_editorial_image",
                "editorial_image_ready",
                "resolved",
            ],
            index=0,
        )
        filtered_briefs = [
            brief
            for brief in briefs
            if status_filter == "Todos" or brief.status == status_filter
        ]

        if not filtered_briefs:
            st.info("No hay briefs en ese estado.")
        else:
            selected_label = st.selectbox(
                "Seleccionar brief",
                options=[
                    f"{brief.slug} · {brief.status} · {brief.topic}"
                    for brief in filtered_briefs
                ],
            )
            selected_slug = selected_label.split(" · ", 1)[0]
            selected_brief = next(
                brief for brief in filtered_briefs if brief.slug == selected_slug
            )

            col_meta1, col_meta2, col_meta3 = st.columns(3)
            col_meta1.metric("Estado", selected_brief.status)
            col_meta2.metric("Motivo", selected_brief.reason)
            col_meta3.metric("Prompt", selected_brief.prompt_version)

            if selected_brief.source_url:
                st.caption(f"Fuente: {selected_brief.source_url}")

            st.text_area(
                "Prompt listo para copiar",
                value=selected_brief.generated_prompt,
                height=320,
                key=f"brief_prompt_{selected_brief.slug}",
            )

            if selected_brief.uploaded_asset_path:
                uploaded_path = Path(selected_brief.uploaded_asset_path)
                st.caption(f"Asset staged: `{uploaded_path}`")
                if uploaded_path.exists():
                    st.image(str(uploaded_path), caption="Asset staged", width=320)

            with st.form(f"image_brief_form_{selected_brief.slug}"):
                topic = st.text_input("Tema", value=selected_brief.topic)
                news_angle = st.text_area(
                    "Ángulo periodístico",
                    value=selected_brief.news_angle,
                    height=100,
                )
                scientific_domain = st.text_input(
                    "Dominio científico", value=selected_brief.scientific_domain
                )
                subject_scene = st.text_area(
                    "Escena / sujeto a representar",
                    value=selected_brief.subject_scene,
                    height=100,
                )
                draft_alt_text = st.text_input(
                    "Texto alternativo preliminar",
                    value=selected_brief.draft_alt_text,
                )
                upload = st.file_uploader(
                    "Subir imagen curada",
                    type=["png", "jpg", "jpeg", "webp", "avif"],
                    key=f"image_upload_{selected_brief.slug}",
                )
                submit_brief = st.form_submit_button(
                    "Guardar cambios del brief",
                )

            if submit_brief:
                try:
                    if upload is not None:
                        updated_brief = image_brief_store.stage_upload(
                            brief=selected_brief,
                            filename=upload.name,
                            content=upload.getvalue(),
                            draft_alt_text=draft_alt_text,
                            topic=topic,
                            news_angle=news_angle,
                            scientific_domain=scientific_domain,
                            subject_scene=subject_scene,
                        )
                        st.success(
                            f"Imagen staged para {updated_brief.slug}. Refinery la usará en la próxima publicación."
                        )
                    else:
                        updated_brief = selected_brief.model_copy(
                            update={
                                "topic": topic.strip(),
                                "news_angle": news_angle.strip(),
                                "scientific_domain": scientific_domain.strip(),
                                "subject_scene": subject_scene.strip(),
                                "draft_alt_text": draft_alt_text.strip(),
                                "generated_prompt": image_brief_store.prompt_template.format(
                                    topic=topic.strip(),
                                    news_angle=news_angle.strip(),
                                    subject_scene=subject_scene.strip(),
                                    scientific_domain=scientific_domain.strip(),
                                    tone=selected_brief.tone,
                                ),
                                "updated_at": datetime.now(timezone.utc),
                            }
                        )
                        image_brief_store.save_brief(updated_brief)
                        st.success("Brief actualizado.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo actualizar el brief: {exc}")

# --- Tab 3: Operations ---
with tab3:
    st.header("Operaciones del Pipeline")

    st.info("ℹ️ Selecciona un artículo para refinar y publicar.")
    env_vars = dict(load_secrets())
    auth_ok = True  # Global auth gate already enforced

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
            disabled=st.session_state.get("op_in_progress", False),
        ):
            st.session_state["op_in_progress"] = True
            try:
                with st.spinner("Ejecutando recolección y análisis cognitivo..."):
                    if not auth_ok:
                        st.warning("Autenticación requerida para sincronizar.")
                    else:
                        try:
                            # Direct call to main module instead of subprocess
                            result = run_refinery(
                                fetch_only=False,
                                fast_mode=False,
                                dry_run=dry_run_enabled,
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
            finally:
                st.session_state["op_in_progress"] = False

    st.markdown("---")
    st.subheader("Pegar URL Específica")
    manual_url = st.text_input(
        "URL del artículo",
        key="manual_article_url",
        placeholder="https://ejemplo.com/articulo",
        help="Carga una URL concreta, la guarda en la base de datos y la deja lista para revisión.",
    )
    col_url_load, col_url_clear = st.columns([2, 1])
    with col_url_load:
        if st.button(
            "🔗 Cargar Artículo desde URL",
            disabled=st.session_state.get("op_in_progress", False),
        ):
            st.session_state["op_in_progress"] = True
            try:
                with st.spinner("Extrayendo artículo desde URL específica..."):
                    if not auth_ok:
                        st.warning(
                            "Autenticación requerida para cargar artículos por URL."
                        )
                    else:
                        try:
                            ingest_service = ManualUrlIngestService(
                                DatabaseManager(),
                                export_dir=BASE_DIR / "temp" / "manual_ingest",
                            )
                            ingest_result = ingest_service.ingest(manual_url)
                            if ingest_result.get("status") == "success":
                                st.session_state["manual_loaded_article"] = (
                                    ingest_result.get("article")
                                )
                                st.session_state["manual_loaded_export_path"] = (
                                    ingest_result.get("export_path")
                                )
                                st.session_state["manual_loaded_fetch_attempts"] = (
                                    ingest_result.get("fetch_attempts", [])
                                )
                                st.session_state["manual_loaded_source_id"] = (
                                    ingest_result.get("source_id")
                                )
                                st.session_state["manual_loaded_source_created"] = (
                                    ingest_result.get("source_created", False)
                                )
                                st.session_state["manual_loaded_article_exists"] = (
                                    ingest_result.get("article_exists", False)
                                )
                                st.success(
                                    "Artículo cargado desde URL. Revísalo y publícalo usando el flujo normal."
                                )
                            else:
                                detail = ingest_result.get(
                                    "message", "No se pudo cargar la URL."
                                )
                                if ingest_result.get("error_code"):
                                    detail = (
                                        f"[{ingest_result.get('error_code')}] {detail}"
                                    )
                                st.error(detail)
                        except Exception as exc:
                            st.error(f"Error cargando URL: {exc}")
            finally:
                st.session_state["op_in_progress"] = False

    with col_url_clear:
        if st.button("🧽 Limpiar URL Cargada"):
            for key in [
                "manual_loaded_article",
                "manual_loaded_export_path",
                "manual_loaded_fetch_attempts",
                "manual_loaded_source_id",
                "manual_loaded_source_created",
                "manual_loaded_article_exists",
            ]:
                st.session_state.pop(key, None)
            st.rerun()

    manual_loaded_article = st.session_state.get("manual_loaded_article")
    if manual_loaded_article:
        source_id = st.session_state.get("manual_loaded_source_id", "unknown")
        source_state = (
            "fuente manual creada"
            if st.session_state.get("manual_loaded_source_created")
            else "fuente reutilizada"
        )
        article_state = (
            "artículo existente reutilizado"
            if st.session_state.get("manual_loaded_article_exists")
            else "artículo nuevo guardado"
        )
        render_article_processing_panel(
            manual_loaded_article,
            export_path=st.session_state.get("manual_loaded_export_path"),
            auth_ok=auth_ok,
            env_vars=env_vars,
            panel_key="manual_url",
            header="Artículo Cargado desde URL",
            source_note=f"Fuente resuelta: `{source_id}` · {source_state} · {article_state}",
            fetch_attempts=st.session_state.get("manual_loaded_fetch_attempts", []),
        )

    st.markdown("---")

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
                    # B-07 / F-0017: Warn if exported data is stale (> 30 min)
                    _ts = data.get("exported_at") or data.get("generated_at")
                    if _ts:
                        try:
                            from datetime import datetime as _dt
                            from datetime import timezone as _tz

                            _exported = _dt.fromisoformat(_ts)
                            if _exported.tzinfo is None:
                                _exported = _exported.replace(tzinfo=_tz.utc)
                            _age_min = (
                                _dt.now(_tz.utc) - _exported
                            ).total_seconds() / 60
                            if _age_min > 30:
                                st.warning(
                                    f"⚠️ Los datos del JSON tienen **{_age_min:.0f} minutos** "
                                    "de antigüedad. Considera ejecutar Sync para obtener datos frescos."
                                )
                        except (ValueError, TypeError):
                            pass  # Malformed timestamp — skip warning
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

                with open(CLONED_PATH, "w", encoding="utf-8") as f_mock:
                    json.dump({"articles": candidates}, f_mock, indent=2)

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

                # Resolve "already published" for the whole candidate set in a
                # single query (avoids one DB round-trip per article on every
                # Streamlit rerun).
                published_id_set: set[int] = set()
                if not show_processed:
                    candidate_ids = []
                    for art in articles:
                        with suppress(ValueError, TypeError):
                            candidate_ids.append(
                                int(str(art.get("id", art.get("title"))))
                            )
                    published_id_set = refinery_db.published_ids_in(candidate_ids)

                filtered_count = 0
                for art in articles:
                    art_id = str(art.get("id", art.get("title")))

                    if not show_processed:
                        try:
                            numeric_id = int(art_id)
                            if numeric_id in published_id_set:
                                filtered_count += 1
                                continue
                        except ValueError:
                            pass  # If ID is not int, we can't check efficiently in main DB yet, or assume not processed

                        # Check .md existence is handled by published_ids_in?
                        # No, published_ids_in checks DB status.
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
                        selected_art = next(
                            (
                                a
                                for a in available_articles
                                if str(a["id"]) == str(selected_id)
                            ),
                            None,
                        )
                        render_article_processing_panel(
                            selected_art,
                            export_path=str(JSON_PATH) if JSON_PATH else None,
                            auth_ok=auth_ok,
                            env_vars=env_vars,
                            panel_key="ranked_list",
                            header="Artículo Seleccionado del Ranking",
                        )

            else:
                st.info("No se encontraron artículos en el archivo exportado.")
        except Exception as e:
            st.error(f"Error leyendo archivo de datos: {e}")
    else:
        st.warning("No hay datos. Clic en 'Sincronizar Datos' para buscar artículos.")


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
    # reuse GitHubPublisher logic from main or init new one
    import git
    from news_collector.components.publishing import GitHubPublisher

    TARGET_DIR = BASE_DIR / "temp" / "target"
    collector_repo_root = BASE_DIR.parents[1]

    refresh_requested = st.button("🔄 Refrescar Lista de Artículos Publicados")
    initial_refresh_key = "published_live_initial_refresh_done"
    refresh_clone = refresh_requested or not st.session_state.get(
        initial_refresh_key, False
    )
    st.session_state[initial_refresh_key] = True

    target_url = env_vars.get("TARGET_REPO_URL", "")

    try:
        snapshot = resolve_published_content_snapshot(
            target_repo_url=target_url,
            collector_repo_root=collector_repo_root,
            temp_target_dir=TARGET_DIR,
            github_token=env_vars.get("GITHUB_TOKEN", ""),
            refresh_clone=refresh_clone,
            prefer_remote_checkout=True,
        )
    except Exception as exc:
        st.error(f"Fallo cargando contenido publicado: {exc}")
        snapshot = None

    if snapshot is not None:
        articles = snapshot.articles
        action_repo_sha = get_repo_head_sha(snapshot.repo_root)
        local_checkout = find_local_target_checkout(
            target_url,
            collector_repo_root=collector_repo_root,
        )
        if local_checkout and local_checkout.resolve() != snapshot.repo_root.resolve():
            st.info(
                "Checkout local detectado solo como referencia: "
                f"`{local_checkout}`. Las acciones usan `{snapshot.repo_root}`."
            )

        if (
            refresh_requested
            and snapshot.source_label != "Checkout local verificado del frontend"
        ):
            st.success("Repositorio destino actualizado y sincronizado.")

        if not articles:
            st.info("No hay artículos en src/content/posts.")
        else:
            st.write(f"Encontrados **{len(articles)}** artículos.")
            st.caption(f"Fuente: {snapshot.source_label} · {snapshot.freshness_label}")
            st.caption(f"Ruta resuelta: `{snapshot.repo_root}`")

            h1, h2, h3, h4 = st.columns([3, 2, 1.5, 1.5])
            h1.markdown("**Título**")
            h2.markdown("**Archivo**")
            h3.markdown("**Acción 1**")
            h4.markdown("**Acción 2**")
            st.markdown("---")

            for article in articles:
                file_path = article.file_path
                refinery_id = article.refinery_id

                c1, c2, c3, c4 = st.columns([3, 2, 1.5, 1.5])

                with c1:
                    st.write(article.title)
                with c2:
                    st.caption(article.file_name)
                    if refinery_id:
                        st.caption(f"ID: {truncate_refinery_id(refinery_id)}")
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
                    else:
                        st.caption("ID: n/a · se usará el nombre exacto del archivo")

                with c3:
                    if st.button(
                        "🗑️ Despublicar",
                        key=f"btn_despub_{article.file_name}",
                        width="stretch",
                    ):
                        delete_target = {"file_name": article.file_name}
                        if refinery_id:
                            delete_target["refinery_id"] = str(refinery_id)

                        with st.spinner("Solicitando eliminación..."):
                            try:
                                if hasattr(refinery_main, "delete_article"):
                                    res = refinery_main.delete_article(delete_target)
                                    if res.get("status") == "success":
                                        st.toast("✅ PR Creado", icon="🗑️")
                                        st.markdown(f"[Ver PR]({res.get('pr_url')})")
                                    else:
                                        st.error(res.get("message"))
                                else:
                                    st.error("Función no cargada")
                            except Exception as e:
                                st.error(str(e))

                with c4:
                    if st.button(
                        "♻️ Reset",
                        key=f"btn_rst_{article.file_name}",
                        width="stretch",
                    ):
                        try:
                            gh_handler = GitHubPublisher(
                                env_vars.get("GITHUB_TOKEN", "")
                            )
                            if not TARGET_DIR.exists():
                                gh_handler.clone_repo(target_url, TARGET_DIR)
                            else:
                                repo = git.Repo(TARGET_DIR)
                                try:
                                    repo.remotes.origin.pull()
                                except Exception:
                                    import shutil

                                    shutil.rmtree(TARGET_DIR, ignore_errors=True)
                                    gh_handler.clone_repo(target_url, TARGET_DIR)
                                    repo = git.Repo(TARGET_DIR)

                            target_posts_dir = TARGET_DIR / "src/content/posts"
                            target_article = None
                            if refinery_id:
                                target_article = find_published_article_by_refinery_id(
                                    target_posts_dir, refinery_id
                                )
                            if target_article is None:
                                candidate_path = target_posts_dir / article.file_name
                                if candidate_path.exists():
                                    target_article = article.__class__(
                                        file_path=candidate_path,
                                        file_name=candidate_path.name,
                                        title=article.title,
                                        refinery_id=refinery_id,
                                        frontmatter=article.frontmatter,
                                        modified_at=article.modified_at,
                                    )
                            if target_article is None:
                                st.error(
                                    "No se encontró el archivo correspondiente en el clon temporal."
                                )
                            else:
                                repo = git.Repo(TARGET_DIR)
                                repo.index.remove(
                                    [
                                        str(
                                            target_article.file_path.relative_to(
                                                TARGET_DIR
                                            )
                                        )
                                    ]
                                )
                                target_article.file_path.unlink()
                                repo.index.commit(
                                    f"Deleted (Reset) {target_article.file_name}"
                                )
                                repo.remotes.origin.push()

                                db_manager = RefineryDatabaseManager(
                                    {
                                        "type": "sqlite",
                                        "path": str(REFINERY_DB_PATH),
                                    }
                                )
                                if refinery_id:
                                    db_manager.delete_article(str(refinery_id))
                                    db_manager.delete_article(f"{refinery_id}.md")
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
                import pandas as pd

                failed_rows = [
                    {
                        "Fuente": source_id,
                        "Estado": data.get("status"),
                        "Error": data.get("last_error_details"),
                    }
                    for source_id, data in health_data_sources.items()
                    if isinstance(data, dict) and not data.get("feed_ok")
                ]
                st.dataframe(pd.DataFrame(failed_rows), width="stretch")

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
            styler = health_df[cols].style
            if "latency" in cols:
                styler = styler.highlight_max(
                    axis=0, subset=["latency"], color="#ffcdd2"
                )
            st.dataframe(styler, width="stretch")

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

    def _index_of(options, value, default=0):
        try:
            return options.index(value)
        except (ValueError, TypeError):
            return default

    cat_options = [
        "technology",
        "science",
        "medicine",
        "space",
        "biology",
        "multidisciplinary",
        "popular_science",
        "artificial_intelligence",
    ]
    freq_options = ["daily", "weekly", "hourly", "multiple_daily"]
    group_options = [
        "ELITE_JOURNALS",
        "SCIENCE_MEDIA",
        "INSTITUTIONAL_SOURCES",
        "AI_LABS",
        "CUSTOM",
    ]

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
                cat_options,
                index=_index_of(cat_options, default_data.get("category")),
            )
            update_freq = st.selectbox(
                "Frecuencia Actualización",
                freq_options,
                index=_index_of(freq_options, default_data.get("update_frequency")),
            )

        group_tag = st.selectbox(
            "Grupo (Organización Interna)",
            group_options,
            index=_index_of(group_options, default_data.get("_group"), default=1),
        )

        submit = st.form_submit_button("💾 Guardar Fuente")

        if submit:
            if not new_id:
                st.error("El ID es obligatorio.")
            else:
                # Update Dictionary — preserve existing keys (e.g. blacklisted,
                # blacklist_reason) instead of replacing the whole entry.
                new_entry = dict(default_data)
                new_entry.update(
                    {
                        "name": name,
                        "url": url,
                        "credibility_score": credibility,
                        "category": category,
                        "update_frequency": update_freq,
                        "_group": group_tag,
                    }
                )
                if is_new:
                    new_entry.setdefault("language", "en")
                    new_entry.setdefault("description", "Added via UI")
                    new_entry.setdefault("typical_delay", 0)

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
