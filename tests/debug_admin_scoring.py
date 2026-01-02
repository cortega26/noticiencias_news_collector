
import json
import toml
import os

JSON_PATH = "data/exports/latest_articles.json"
CONFIG_PATH = "config.toml"

def debug_scoring():
    if not os.path.exists(JSON_PATH):
        print(f"JSON not found: {JSON_PATH}")
        return
    if not os.path.exists(CONFIG_PATH):
        print(f"Config not found: {CONFIG_PATH}")
        return
        
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        articles = payload.get("articles", [])
    else:
        articles = payload
        
    with open(CONFIG_PATH, "r") as f:
        config_data = toml.load(f)
        
    current_weights = config_data["scoring"]["weights"]
    print(f"Loaded Weights: {current_weights}")
    
    for i, art in enumerate(articles[:3]):
        print(f"\n--- Article {i} ---")
        comps = art.get("components", {})
        print(f"Raw Components: {comps}")
        
        s_score = comps.get("source_credibility", 0.0)
        r_score = comps.get("recency", 0.0)
        q_score = comps.get("content_quality", 0.0)
        c_score = comps.get("cognitive_engagement_norm", 0.0)
        
        print(f"Inputs: S={s_score}, R={r_score}, Q={q_score}, C={c_score}")
        
        new_final = (
            s_score * current_weights.get("source_credibility", 0.25) +
            r_score * current_weights.get("recency", 0.20) +
            q_score * current_weights.get("content_quality", 0.25) +
            c_score * current_weights.get("engagement_potential", 0.30)
        )
        
        print(f"Calculated: {new_final}")
        print(f"Stored Score: {art.get('score')}")

if __name__ == "__main__":
    debug_scoring()
