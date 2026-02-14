import json
import logging
import random
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, List
import tempfile
import os

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
        audit_cfg = {}
        if isinstance(config, dict):
            audit_cfg = config.get("editorial_auditor", {})
        else:
            audit_cfg = getattr(config, "editorial_auditor", {})
            if not isinstance(audit_cfg, dict):
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
        if not isinstance(paths, dict):
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
        
        # OBJECTIVE 2: Strict Timeout Enforcement (15s)
        self.provider = OllamaProvider(
            api_url=self.api_url, 
            model=self.model, 
            timeout=15,  # Recommended 15s max
            max_retries=0 # STRICT ONE-SHOT: Auditor is non-critical, do not retry.
        )
        
        self.prompts = self._load_prompts()
        self.rolling_avg_file = self.metadata_dir / "auditor_rolling_average.json"

        # Circuit Breaker State
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.circuit_open_until = 0.0
        self.COOLDOWN_SECONDS = 1800 # 30 minutes

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

    def should_run_fast(self, article: Dict[str, Any], content: str) -> bool:
        """
        OBJECTIVE 4: CPU Load Minimization.
        Checks ALL conditions (Circuit Breaker, Sampling, Triggers) BEFORE submission.
        """
        if not self.enabled:
            return False

        # Check Circuit Breaker
        now = time.time()
        if now < self.circuit_open_until:
             logger.warning(f"Auditor Circuit Open. Skipping. (Opens until {datetime.fromtimestamp(self.circuit_open_until)})")
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

    def _get_default_audit_result(self) -> Dict[str, Any]:
        """Returns the robust default schema for audit results."""
        return {
            "epistemic_rigor_score": 0.0,
            "clarity_score": 0.0,
            "speculation_control_score": 0.0,
            "engagement_score": 0.0,
            "has_therapeutic_claims": False,
            "has_proper_caveats": False,
            "opening_strength": "moderate",
            "issues": []
        }

    def _normalize_audit_result(self, raw: Any) -> Dict[str, Any]:
        """
        OBJECTIVE 2 & 3: Strict Normalization & Single Warning.
        Silently corrects types. Returns safe defaults if structure is invalid.
        """
        defaults = self._get_default_audit_result()
        
        if not isinstance(raw, dict):
            logger.warning("Auditor received invalid provider output. Using defaults.")
            return defaults
            
        normalized = defaults.copy()
        
        for key, default_val in defaults.items():
            if key not in raw:
                continue
                
            val = raw[key]
            
            # 1. Float Normalization (Clamp 0.0 - 10.0)
            if isinstance(default_val, float):
                try:
                    # Handle string floats "5.0" or real floats 5.0
                    f_val = float(val)
                    normalized[key] = max(0.0, min(10.0, f_val))
                except (ValueError, TypeError):
                    pass # Keep default, no log noise

            # 2. Bool Normalization (Strict)
            elif isinstance(default_val, bool):
                if isinstance(val, bool):
                     normalized[key] = val
                # Option: Accept "true"/"false" strings if needed? 
                # Prompt says "Strict bool". So probably strict type or safe defaults.
                # We leave default if not bool.
            
            # 3. List Normalization (Strict)
            elif isinstance(default_val, list):
                if isinstance(val, list):
                    normalized[key] = val
                # Prevent "bool is not iterable" by rejecting non-lists
            
            # 4. String Normalization
            elif isinstance(default_val, str):
                if isinstance(val, str):
                    normalized[key] = val

        return normalized

    def get_cached_score(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the last known auditor score for an article, if available.
        Does NOT trigger a new audit.
        """
        try:
            safe_id = str(article_id).replace("/", "_").replace("\\", "_")
            score_file = self.metadata_dir / safe_id / "auditor_score.json"
            
            if score_file.exists():
                data = json.loads(score_file.read_text(encoding="utf-8"))
                return data.get("audit") # Return inner audit object
        except Exception as e:
            logger.warning(f"Failed to read cached score for {article_id}: {e}")
        return None

    def audit_article_sync(self, article_id: str, content: str, source_url: str, article_data: Dict[str, Any] = {}) -> None:
        """
        Synchronous worker method. SHOULD BE CALLED VIA EXECUTOR.
        Handles LLM interaction, result parsing, and persistence.
        """
        try:
            logger.info(f"Starting Editorial Audit for {article_id}...")
            
            system_prompt = self.prompts.get("auditor", {}).get("system", "")
            if not system_prompt:
                system_prompt = "Analyze validity. Output JSON."

            user_prompt = f"Title: {article_data.get('title', 'Unknown')}\nURL: {source_url}\n\nContent:\n{content[:10000]}"

            # Call LLM with Timeout (handled in provider init)
            # OBJECTIVE 1: Rename ambiguous variable
            provider_result = self.provider.generate_sync(
                user_prompt, 
                system=system_prompt, 
                stream=False,
                model=self.model
            )
            
            raw_data = {}
            
            # OBJECTIVE 4: Harden Extraction Layer
            # Gracefully handle various return types
            if isinstance(provider_result, dict):
                raw_data = provider_result
            elif isinstance(provider_result, str):
                 raw_data = self.provider._extract_json(provider_result)
            elif hasattr(provider_result, '__iter__'):
                 # Best effort for iterators (though prompt warns against assumption)
                 try:
                     text = "".join(str(chunk) for chunk in provider_result)
                     raw_data = self.provider._extract_json(text)
                 except Exception:
                     pass # Treated as invalid by _normalize
            else:
                 logger.warning(f"Auditor received invalid provider output type ({type(provider_result)}). Using defaults.")
                 raw_data = {}
            
            # Validate & Normalize (Handles non-dict raw_data internally)
            # This satisfies Objective 6 (Invariant: never raise exception from output type)
            validated_result = self._normalize_audit_result(raw_data)

            # Save Score
            self._save_score(article_id, validated_result)
            
            # Update Rolling Average
            self._update_rolling_average(validated_result)
            
            # SUCCESS: Reset Circuit Breaker
            self.failure_count = 0
            
            logger.info(f"Audit Complete for {article_id}. Epistemic Score: {validated_result.get('epistemic_rigor_score')}")

        except Exception as e:
            logger.error(f"Auditor Error for {article_id}: {e}")
            
            # FAILURE: Update Circuit Breaker
            self.failure_count += 1
            if self.failure_count >= 3:
                 self.circuit_open_until = time.time() + self.COOLDOWN_SECONDS
                 logger.critical(f"Auditor Circuit Breaker TRIPPED. Pausing audits for 30 mins. Failure count: {self.failure_count}")

    def _save_score(self, article_id: str, score_data: Dict[str, Any]):
        """
        OBJECTIVE 5: Persist Audit Results Safely (Atomic Write).
        """
        try:
            safe_id = str(article_id).replace("/", "_").replace("\\", "_")
            article_meta_dir = self.metadata_dir / safe_id
            article_meta_dir.mkdir(parents=True, exist_ok=True)
            
            score_file = article_meta_dir / "auditor_score.json"
            
            final_data = {
                "timestamp": datetime.now().isoformat(),
                "audit": score_data
            }
            
            # Atomic Write
            # cast dir to str for compatibility, enforce utf-8
            with tempfile.NamedTemporaryFile("w", dir=str(article_meta_dir), delete=False, encoding="utf-8") as tf:
                 json.dump(final_data, tf, indent=2)
                 temp_name = tf.name
            
            os.replace(temp_name, score_file)
            
        except Exception as e:
            logger.error(f"Failed to save auditor score: {e}")
            if 'temp_name' in locals() and os.path.exists(temp_name):
                os.unlink(temp_name)

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
                # New values are strictly validated floats now
                new_val = new_score.get(f, 0.0) 
                
                updated_val = old_val + (new_val - old_val) / new_count
                updated[f] = round(updated_val, 4)
            
            # Atomic Write for Average too
            with tempfile.NamedTemporaryFile("w", dir=str(self.metadata_dir), delete=False, encoding="utf-8") as tf:
                 json.dump(updated, tf, indent=2)
                 temp_name = tf.name
            
            os.replace(temp_name, self.rolling_avg_file)
            
        except Exception as e:
            logger.error(f"Failed to update rolling average: {e}")
            if 'temp_name' in locals() and os.path.exists(temp_name):
                os.unlink(temp_name)
