import streamlit as st
import toml
import os
import dotenv
from pathlib import Path
import sys

# Import the refactored main function
# We need to add the current directory to path just in case, though usually not needed for sibling imports in scripts
sys.path.append(str(Path(__file__).parent))
from main import main as run_refinery

# Page Config
st.set_page_config(page_title="Noticiencias Control Panel", page_icon="🎛️", layout="wide")

st.title("🎛️ Noticiencias Unified Control Panel")

# Paths
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# --- Helper Functions ---
def load_env_file():
    if not ENV_FILE.exists():
        # st.warning(f"⚠️ .env not found at: {ENV_FILE}") # Too noisy on first run
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
        st.error(f"❌ Config file not found at: `{COLLECTOR_CONFIG_PATH}`")
        st.caption(f"Checked path: `{NEWS_COLLECTOR_PATH}`. Configure `NEWS_COLLECTOR_PATH` in the settings tab.")
        st.info(f"Current Working Directory: `{os.getcwd()}`")
        return None
    with open(COLLECTOR_CONFIG_PATH, "r") as f:
        return toml.load(f)

def save_toml_config(config_data):
    with open(COLLECTOR_CONFIG_PATH, "w") as f:
        toml.dump(config_data, f)

# --- Tabs ---
tab1, tab2, tab3 = st.tabs(["🧠 AI & Refinery", "📊 Scraper & Scoring", "🚀 Operations"])

# --- Tab 1: AI Settings ---
with tab1:
    st.header("Refinery Settings")
    env_vars = load_env_file()
    
    # Convert to mutable dict if it's not
    env_vars = dict(env_vars)
    
    if env_vars or not ENV_FILE.exists(): # Allow editing even if empty
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🤖 AI Model")
            current_model = env_vars.get("OLLAMA_MODEL", "llama3.2")
            new_model = st.selectbox(
                "Select Ollama Model", 
                ["llama3.2", "llama3.3", "llama3.1:70b", "mistral"],
                index=0 if "3.2" in current_model else 1
            )
            env_vars["OLLAMA_MODEL"] = new_model
            
            st.subheader("🔗 API URL")
            env_vars["OLLAMA_API_URL"] = st.text_input("Ollama Endpoint", env_vars.get("OLLAMA_API_URL", "http://localhost:11434/api/generate"))

        with col2:
            st.subheader("📂 Repositories")
            env_vars["SOURCE_REPO_URL"] = st.text_input("Source Repo", env_vars.get("SOURCE_REPO_URL", ""))
            env_vars["TARGET_REPO_URL"] = st.text_input("Target Repo", env_vars.get("TARGET_REPO_URL", ""))
            
            # --- NEW: Configurable Path ---
            env_vars["NEWS_COLLECTOR_PATH"] = st.text_input(
                "News Collector Path (Local)", 
                env_vars.get("NEWS_COLLECTOR_PATH", str(DEFAULT_COLLECTOR_PATH))
            )
            # ------------------------------
            
            env_vars["GITHUB_TOKEN"] = st.text_input("GitHub Token", env_vars.get("GITHUB_TOKEN", ""), type="password")
            
        st.subheader("📝 System Prompt (Personality)")
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
        env_vars["OLLAMA_PROMPT"] = st.text_area("Edit the AI's instructions:", value=current_prompt, height=200)

        if st.button("💾 Save AI Settings"):
            save_env_file(env_vars)
            st.success("Environment variables updated!")
    else:
        st.warning("No .env file found and unable to create one.")

# --- Tab 2: Scraper Settings ---
with tab2:
    st.header("Collector Configuration")
    config_data = load_toml_config()
    
    if config_data:
        # Collection Settings
        st.subheader("⏱️ Collection")
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            if "collection" in config_data:
                config_data["collection"]["collection_interval_hours"] = st.number_input(
                    "Collection Interval (Hours)", 
                    min_value=1, max_value=48, 
                    value=config_data["collection"].get("collection_interval_hours", 6)
                )
                config_data["collection"]["max_articles_per_source"] = st.number_input(
                    "Max Articles Per Source", 
                    min_value=5, max_value=500, 
                    value=config_data["collection"].get("max_articles_per_source", 50)
                )

        # Scoring Weights
        st.subheader("⚖️ Scoring Weights (Total should be ~1.0)")
        if "scoring" in config_data and "weights" in config_data["scoring"]:
            weights = config_data["scoring"]["weights"]
            
            w_col1, w_col2 = st.columns(2)
            with w_col1:
                weights["source_credibility"] = st.slider("Source Credibility", 0.0, 1.0, weights.get("source_credibility", 0.25))
                weights["recency"] = st.slider("Recency / Freshness", 0.0, 1.0, weights.get("recency", 0.2))
            with w_col2:
                weights["content_quality"] = st.slider("Content Quality", 0.0, 1.0, weights.get("content_quality", 0.25))
                weights["engagement_potential"] = st.slider("Engagement Potential", 0.0, 1.0, weights.get("engagement_potential", 0.3))

        # Keywords
        st.subheader("🔑 Topic Keywords")
        if "text_processing" in config_data:
            tp = config_data["text_processing"]
            
            boost_txt = st.text_area("Boost Keywords (comma separated)", ", ".join(tp.get("boost_keywords", [])))
            tp["boost_keywords"] = [x.strip() for x in boost_txt.split(",") if x.strip()]
            
            penalty_txt = st.text_area("Penalty/Clickbait Keywords (comma separated)", ", ".join(tp.get("penalty_keywords", [])))
            tp["penalty_keywords"] = [x.strip() for x in penalty_txt.split(",") if x.strip()]

        if st.button("💾 Save Scraper Config"):
            save_toml_config(config_data)
            st.success("config.toml updated successfully!")

# --- Tab 3: Operations ---
with tab3:
    st.header("Pipeline Operations")
    
    st.info("ℹ️ Select an article to refine and publish.")
    
    # Section 1: Sync
    col_sync, col_status = st.columns([1, 2])
    with col_sync:
        if st.button("🔄 Sync Latest Data", help="Pull latest articles from Cloud Collector"):
            with st.spinner("Syncing data..."):
                try:
                    # Direct call to main module instead of subprocess
                    result = run_refinery(fetch_only=True)
                    if result.get("status") == "success":
                        st.success("Sync Complete!")
                    else:
                        st.error("Sync Failed")
                        st.expander("Error Details").write(result.get("message"))
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
        st.info(f"Using local data from: {JSON_PATH}")
    
    if JSON_PATH and JSON_PATH.exists():
        import json
        import pandas as pd
        
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                articles = json.load(f)
            
            if articles:
                st.subheader(f"Available Articles ({len(articles)})")
                
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
                
                selected_label = st.selectbox("Select Article to Process:", options=list(options.keys()))
                
                if selected_label:
                    selected_id = options[selected_label]
                    
                    # Show details of selected
                    selected_art = next((a for a in articles if str(a["id"]) == str(selected_id)), None)
                    if selected_art:
                        with st.expander("📄 Review Article Summary", expanded=False):
                            st.write(f"**Title:** {selected_art.get('title')}")
                            st.write(f"**Summary:** {selected_art.get('summary')}")
                            if selected_art.get("image_url"):
                                st.image(selected_art.get("image_url"), caption="Extracted Image", width=300)
                    
                    # Process Button
                    if st.button(f"✨ Refine & Publish (ID: {selected_id})", type="primary"):
                        with st.spinner(f"Processing ID {selected_id}... This takes ~15 mins on CPU."):
                             # Direct call to main module
                            try:
                                result = run_refinery(process_id=str(selected_id))
                                
                                if result.get("status") == "success":
                                    st.success("Processing Complete! Check your website repo.")
                                    if result.get("processed_count", 0) > 0:
                                         st.balloons()
                                else:
                                    st.error("Processing Failed.")
                                    st.expander("Error Details").write(result.get("message"))
                            except Exception as e:
                                st.error(f"Critical execution error: {e}")

            else:
                st.info("No articles found in the export file.")
        except Exception as e:
            st.error(f"Failed to read data file: {e}")
    else:
        st.warning("No data found. Click 'Sync Latest Data' to fetch articles.")

    st.markdown("---")
    st.markdown("### Recent Activity Log")
    log_file = BASE_DIR / "refinery.log"  # Assuming standard log file
    if log_file.exists():
        with open(log_file, "r") as f:
            logs = f.readlines()[-20:] # Last 20 lines
            st.code("".join(logs))
    else:
        st.text("No logs found yet.")
