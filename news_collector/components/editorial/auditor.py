import json
import logging
import random
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.utils.logger import get_logger

# Use centralized logger
logger = get_logger().create_module_logger("components.editorial.auditor")

class EditorialAuditor:
    def __init__(self, config: Any):
        """
        Initialize the Auditor with configuration.
        """
        self.config = config
        
        # Load Auditor Config (Safe navigation)
        # We handle config as either a dict or an object depending on how it's passed
        audit_cfg = {}
        if isinstance(config, dict):
            audit_cfg = config.get("editorial_auditor", {})
        else:
            audit_cfg = getattr(config, "editorial_auditor", {})
            if not isinstance(audit_cfg, dict):
                # If it's an object, convert to dict or access attributes
                # For safety, let's assume we can getattr
                pass

        # Helper to get config value safely
        def get_cfg(obj, key, default):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        self.enabled = get_cfg(audit_cfg, "enabled", True)
        self.sampling_rate = get_cfg(audit_cfg, "sampling_rate", 0.2)
        self.blocking = get_cfg(audit_cfg, "blocking", False)

        # Triggers
        self.trigger_keywords = [
            "tratamiento", "therapy", "treatment", "drug", "patients", "prevent", 
            "cura", "fármaco", "terapia", "clinical", "clínico", "prevención",
            "vaccine", "vacuna", "cancer", "cáncer", "alzheimer", "milagro"
        ]
        self.trigger_categories = [
            "health", "medicine", "biology", "salud", "biología", "medicina"
        ]

        # Paths
        paths = getattr(config, "paths", None) or {}
        if not isinstance(paths, dict): # If it's an object
             # Quick fallback
             data_dir = getattr(paths, "data_dir", "./data")
        else:
             data_dir = paths.get("data_dir", "./data")
        
        self.metadata_dir = Path(data_dir) / "article_metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # LLM Setup
        ollama_cfg = getattr(config, "ollama", None) or {}
        api_url = "http://localhost:11434/api/generate"
        model = "llama3.2"
        
        if isinstance(ollama_cfg, dict):
             api_url = ollama_cfg.get("api_url", api_url)
             model = ollama_cfg.get("model", model)
        else:
             api_url = getattr(ollama_cfg, "api_url", api_url)
             model = getattr(ollama_cfg, "model", model)

        self.api_url = api_url
        self.model = model
        
        self.provider = OllamaProvider(
            api_url=self.api_url, 
            model=self.model, 
            timeout=120 
        )
        
        self.prompts = self._load_prompts()
        self.rolling_avg_file = self.metadata_dir / "auditor_rolling_average.json"

    def _load_prompts(self) -> dict:
        """Loads prompt templates from yaml config."""
        try:
            project_root = Path(__file__).resolve().parents[3]
            prompts_path = project_root / "config" / "prompts.yaml"
            
            import yaml
            if prompts_path.exists():
                return yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load prompts: {e}")
        return {}

    def _should_run(self, article: Dict[str, Any], content: str) -> bool:
        """
        Determines if the auditor should run based on sampling or triggers.
        """
        if not self.enabled:
            return False

        # 1. Trigger by Category
        category = article.get("category", "").lower()
        meta_category = (article.get("metadata") or {}).get("category", "").lower()
        
        if category in self.trigger_categories or meta_category in self.trigger_categories:
            logger.info(f"Auditor Triggered: Category match ({category or meta_category})")
            return True

        # 2. Trigger by Keywords
        content_lower = content[:5000].lower()
        for kw in self.trigger_keywords:
            if kw in content_lower:
                logger.info(f"Auditor Triggered: Keyword match ('{kw}')")
                return True

        # 3. Random Sampling
        if random.random() < self.sampling_rate:
            logger.info("Auditor Triggered: Random Sampling")
            return True

        return False

    def audit_article(self, article_id: str, content: str, source_url: str, article_data: Dict[str, Any] = {}) -> None:
        """
        Main entry point. Runs the audit if triggered and saves results.
        Failures are caught and logged (non-blocking).
        """
        try:
            if not self._should_run(article_data, content):
                return

            logger.info(f"Starting Editorial Audit for {article_id}...")
            
            system_prompt = self.prompts.get("auditor", {}).get("system", "")
            if not system_prompt:
                # Fallback if config is missing
                system_prompt = "Analyze validity. Output JSON."

            user_prompt = f"Title: {article_data.get('title', 'Unknown')}\nURL: {source_url}\n\nContent:\n{content[:10000]}" # Limit context

            # Call LLM
            # Using generate_sync with stream=False should return the full response object or string depending on provider imp.
            # Checking ai_editor usage: it iterates over generator.
            # Let's handle generator.
            generator = self.provider.generate_sync(
                user_prompt, 
                system=system_prompt, 
                stream=False,
                model=self.model
            )
            
            response_text = ""
            # If provider returns a string when stream=False, great. If generator, consume it.
            if isinstance(generator, str):
                response_text = generator
            else:
                 for chunk in generator:
                     response_text += chunk

            # Extract JSON
            result = self.provider._extract_json(response_text)
            if not result:
                logger.warning(f"Auditor failed to produce JSON for {article_id}")
                return

            # Save Score
            self._save_score(article_id, result)
            
            # Update Rolling Average
            self._update_rolling_average(result)
            
            logger.info(f"Audit Complete for {article_id}. Epistemic Score: {result.get('epistemic_rigor_score')}")

        except Exception as e:
            logger.error(f"Auditor Error for {article_id}: {e}")
            # Non-blocking, simply exit

    def _save_score(self, article_id: str, score_data: Dict[str, Any]):
        try:
            safe_id = str(article_id).replace("/", "_").replace("\\", "_")
            article_meta_dir = self.metadata_dir / safe_id
            article_meta_dir.mkdir(parents=True, exist_ok=True)
            
            score_file = article_meta_dir / "auditor_score.json"
            
            final_data = {
                "timestamp": datetime.now().isoformat(),
                "audit": score_data
            }
            
            score_file.write_text(json.dumps(final_data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save auditor score: {e}")

    def _update_rolling_average(self, new_score: Dict[str, Any]):
        try:
            current_avg = {}
            if self.rolling_avg_file.exists():
                try:
                    current_avg = json.loads(self.rolling_avg_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    current_avg = {}
            
            fields = ["epistemic_rigor_score", "clarity_score", "speculation_control_score", "engagement_score"]
            
            count = current_avg.get("count", 0)
            new_count = count + 1
            
            updated = {"count": new_count, "last_updated": datetime.now().isoformat()}
            
            for f in fields:
                old_val = float(current_avg.get(f, 0.0))
                # Handle possible string/none in new_score
                try:
                    new_val_raw = new_score.get(f, 0.0)
                    if new_val_raw is None: 
                        new_val = 0.0 
                    else:
                        new_val = float(new_val_raw)
                except (ValueError, TypeError):
                    new_val = 0.0
                
                updated_val = old_val + (new_val - old_val) / new_count
                updated[f] = round(updated_val, 4)
            
            self.rolling_avg_file.write_text(json.dumps(updated, indent=2), encoding="utf-8")
            
        except Exception as e:
            logger.error(f"Failed to update rolling average: {e}")
