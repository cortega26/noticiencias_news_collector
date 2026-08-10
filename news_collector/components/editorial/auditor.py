import json
import os
import random
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from news_collector.infrastructure.llm.factory import get_provider
from news_collector.infrastructure.llm.model_registry import (
    ModelRegistryError,
    get_model_for_stage,
)
from news_collector.utils.logger import get_logger
from noticiencias.config_manager import load_config

# Use centralized logger
logger = get_logger().create_module_logger("components.editorial.auditor")


class EditorialAuditor:
    @staticmethod
    def _resolve_positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(str(value).strip())
            return parsed if parsed > 0 else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _read_env_int(var_name: str) -> Optional[int]:
        raw = os.getenv(var_name)
        if raw is None:
            return None
        try:
            parsed = int(raw.strip())
            if parsed > 0:
                return parsed
        except ValueError:
            return None
        return None

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
        self.optional = not self.blocking

        ci_default_timeout = (
            20
            if str(os.getenv("CI", "")).strip().lower()
            in {
                "1",
                "true",
                "yes",
            }
            else 45
        )
        cfg_timeout = get_cfg(audit_cfg, "timeout_seconds", ci_default_timeout)
        cfg_retries = get_cfg(audit_cfg, "max_retries", 2)
        cfg_health_timeout = get_cfg(audit_cfg, "health_timeout_seconds", 2)
        self.timeout_seconds = self._read_env_int("OLLAMA_TIMEOUT_SECONDS") or (
            self._resolve_positive_int(cfg_timeout, ci_default_timeout)
        )
        self.max_retries = self._read_env_int("OLLAMA_RETRY_ATTEMPTS") or (
            self._resolve_positive_int(cfg_retries, 2)
        )
        self.health_timeout_seconds = self._read_env_int(
            "OLLAMA_HEALTH_TIMEOUT_SECONDS"
        ) or self._resolve_positive_int(cfg_health_timeout, 2)

        # Triggers
        self.trigger_keywords = [
            "tratamiento",
            "therapy",
            "treatment",
            "drug",
            "patients",
            "prevent",
            "cura",
            "fármaco",
            "terapia",
            "clinical",
            "clínico",
            "prevención",
            "vaccine",
            "vacuna",
            "cancer",
            "cáncer",
            "alzheimer",
            "milagro",
        ]
        self.trigger_categories = [
            "health",
            "medicine",
            "biology",
            "salud",
            "biología",
            "medicina",
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
        fallback_config = None
        if isinstance(ollama_cfg, dict):
            api_url = ollama_cfg.get("api_url")
        else:
            api_url = getattr(ollama_cfg, "api_url", None)
        if not api_url:
            fallback_config = load_config()
            api_url = fallback_config.ollama.api_url
            logger.warning(
                "Auditor initialized with config missing ollama.api_url; using load_config() fallback."
            )

        try:
            model = get_model_for_stage("auditor", config=config, logger=logger)
        except ModelRegistryError as exc:
            if fallback_config is None:
                fallback_config = load_config()
            logger.warning(
                f"Auditor model resolution fallback due to invalid config: {exc}"
            )
            model = get_model_for_stage(
                "auditor", config=fallback_config, logger=logger
            )

        self.api_url = api_url
        self.model = model

        # OBJECTIVE 2: Strict Timeout Enforcement (15s)
        self.provider = get_provider(
            config=self.config,
            api_url=self.api_url,
            model=self.model,
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
        )
        logger.info(
            f"Auditor configured: endpoint={self.api_url} model={self.model} timeout={self.timeout_seconds}s retries={self.max_retries} health_timeout={self.health_timeout_seconds}s optional={self.optional}"
        )

        self.prompts = self._load_prompts()
        self.rolling_avg_file = self.metadata_dir / "auditor_rolling_average.json"

        # Circuit Breaker State
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.circuit_open_until = 0.0
        self.COOLDOWN_SECONDS = 1800  # 30 minutes

    def _load_prompts(self) -> dict:
        """Loads prompt templates from yaml config."""
        try:
            project_root = Path(__file__).resolve().parents[3]
            prompts_path = project_root / "config" / "prompts.yaml"

            import yaml

            if prompts_path.exists():
                data = yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
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
            logger.warning(
                f"Auditor Circuit Open. Skipping. (Opens until {datetime.fromtimestamp(self.circuit_open_until)})"
            )
            return False

        # 1. Trigger by Category
        category = article.get("category", "").lower()
        meta_category = (article.get("metadata") or {}).get("category", "").lower()

        if (
            category in self.trigger_categories
            or meta_category in self.trigger_categories
        ):
            logger.info(
                f"Auditor Triggered: Category match ({category or meta_category})"
            )
            return True

        # 2. Trigger by Keywords
        content_lower = content[:5000].lower()
        for kw in self.trigger_keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", content_lower):
                logger.info(f"Auditor Triggered: Keyword match ('{kw}')")
                return True

        # 3. Random Sampling
        if random.random() < self.sampling_rate:  # noqa: S311
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
            "issues": [],
        }

    def _normalize_audit_result(self, raw: Any) -> Dict[str, Any]:  # noqa: C901
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
                    pass  # Keep default, no log noise

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
            elif isinstance(default_val, str) and isinstance(val, str):
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
                if isinstance(data, dict):
                    audit = data.get("audit")
                    return audit if isinstance(audit, dict) else None
        except Exception as e:
            logger.warning(f"Failed to read cached score for {article_id}: {e}")
        return None

    def audit_article_sync(  # noqa: C901
        self,
        article_id: str,
        content: str,
        source_url: str,
        article_data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Synchronous worker method. SHOULD BE CALLED VIA EXECUTOR.
        Handles LLM interaction, result parsing, and persistence.
        """
        if article_data is None:
            article_data = {}
        try:
            is_ready, readiness_reason = self.provider.check_health(
                timeout_seconds=float(self.health_timeout_seconds)
            )
            if not is_ready:
                reason = (
                    f"Ollama unavailable before audit call ({readiness_reason}); "
                    "audit skipped."
                )
                logger.warning(f"Auditor skipped for {article_id}: {reason}")
                result = {
                    "status": "audit_failed",
                    "reason": reason,
                    "model": self.model,
                    "endpoint": self.api_url,
                    "timeout_seconds": self.timeout_seconds,
                    "max_retries": self.max_retries,
                    "attempts": 0,
                    "blocking": self.blocking,
                }
                self._save_audit_status(article_id, result)
                return result

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
                model=self.model,
                log_errors_as_warning=self.optional,
            )

            raw_data = {}

            # OBJECTIVE 4: Harden Extraction Layer
            # Gracefully handle various return types
            if isinstance(provider_result, dict):
                raw_data = provider_result
            elif isinstance(provider_result, str):
                raw_data = self.provider._extract_json(provider_result)
            elif hasattr(provider_result, "__iter__"):
                # Best effort for iterators (though prompt warns against assumption)
                try:
                    text = "".join(str(chunk) for chunk in provider_result)
                    raw_data = self.provider._extract_json(text)
                except (ValueError, TypeError, json.JSONDecodeError):
                    pass  # Treated as invalid by _normalize
            else:
                logger.warning(
                    f"Auditor received invalid provider output type ({type(provider_result)}). Using defaults."
                )
                raw_data = {}

            # Validate & Normalize (Handles non-dict raw_data internally)
            # This satisfies Objective 6 (Invariant: never raise exception from output type)
            validated_result = self._normalize_audit_result(raw_data)

            # Only persist a score when the provider actually returned usable
            # data — i.e. at least one of the real audit fields is present.
            # Persisting the all-zeros default as a real "audit_passed" score
            # poisons the cache: a later editorial run with a threshold
            # enabled would block the article forever even though it was never
            # really audited. A truthy-but-keyless dict (e.g. {"error": ...})
            # is exactly as poisonous as an empty one, so key presence (not
            # truthiness) is the discriminator.
            has_usable_data = bool(raw_data) and any(
                key in raw_data for key in self._get_default_audit_result()
            )
            if has_usable_data:
                # Save Score
                self._save_score(article_id, validated_result)

                # Update Rolling Average
                self._update_rolling_average(validated_result)

            # SUCCESS: Reset Circuit Breaker
            self.failure_count = 0

            result = {
                "status": "audit_passed" if has_usable_data else "audit_unavailable",
                "reason": "",
                "model": self.model,
                "endpoint": self.api_url,
                "timeout_seconds": self.timeout_seconds,
                "max_retries": self.max_retries,
                "attempts": 1,
                "blocking": self.blocking,
            }
            self._save_audit_status(article_id, result)

            logger.info(
                f"Audit Complete for {article_id}. Epistemic Score: {validated_result.get('epistemic_rigor_score')}"
            )
            return result

        except Exception as e:
            msg = f"Auditor Error for {article_id}: {e}"
            if self.optional:
                logger.warning(msg)
            else:
                logger.error(msg)

            # FAILURE: Update Circuit Breaker
            self.failure_count += 1
            if self.failure_count >= 3:
                self.circuit_open_until = time.time() + self.COOLDOWN_SECONDS
                logger.critical(
                    f"Auditor Circuit Breaker TRIPPED. Pausing audits for 30 mins. Failure count: {self.failure_count}"
                )
            reason = str(e)
            attempts = self.max_retries + 1
            if isinstance(e, requests.Timeout):
                reason = (
                    f"timeout after {attempts} attempts "
                    f"(timeout={self.timeout_seconds}s): {e}"
                )
            result = {
                "status": "audit_failed",
                "reason": reason,
                "model": self.model,
                "endpoint": self.api_url,
                "timeout_seconds": self.timeout_seconds,
                "max_retries": self.max_retries,
                "attempts": attempts,
                "blocking": self.blocking,
            }
            self._save_audit_status(article_id, result)
            return result

    def _save_audit_status(self, article_id: str, status_data: Dict[str, Any]) -> None:
        try:
            safe_id = str(article_id).replace("/", "_").replace("\\", "_")
            article_meta_dir = self.metadata_dir / safe_id
            article_meta_dir.mkdir(parents=True, exist_ok=True)

            status_file = article_meta_dir / "auditor_status.json"
            payload = {"timestamp": datetime.now().isoformat(), **status_data}
            with tempfile.NamedTemporaryFile(
                "w", dir=str(article_meta_dir), delete=False, encoding="utf-8"
            ) as tf:
                json.dump(payload, tf, indent=2)
                temp_name = tf.name

            os.replace(temp_name, status_file)
        except Exception as exc:
            logger.error(f"Failed to save auditor status: {exc}")
            if "temp_name" in locals() and os.path.exists(temp_name):
                os.unlink(temp_name)

    def _save_score(self, article_id: str, score_data: Dict[str, Any]):
        """
        OBJECTIVE 5: Persist Audit Results Safely (Atomic Write).
        """
        try:
            safe_id = str(article_id).replace("/", "_").replace("\\", "_")
            article_meta_dir = self.metadata_dir / safe_id
            article_meta_dir.mkdir(parents=True, exist_ok=True)

            score_file = article_meta_dir / "auditor_score.json"

            final_data = {"timestamp": datetime.now().isoformat(), "audit": score_data}

            # Atomic Write
            # cast dir to str for compatibility, enforce utf-8
            with tempfile.NamedTemporaryFile(
                "w", dir=str(article_meta_dir), delete=False, encoding="utf-8"
            ) as tf:
                json.dump(final_data, tf, indent=2)
                temp_name = tf.name

            os.replace(temp_name, score_file)

        except Exception as e:
            logger.error(f"Failed to save auditor score: {e}")
            if "temp_name" in locals() and os.path.exists(temp_name):
                os.unlink(temp_name)

    def _update_rolling_average(self, new_score: Dict[str, Any]):
        try:
            current_avg = {}
            if self.rolling_avg_file.exists():
                try:
                    current_avg = json.loads(
                        self.rolling_avg_file.read_text(encoding="utf-8")
                    )
                except json.JSONDecodeError:
                    current_avg = {}

            fields = [
                "epistemic_rigor_score",
                "clarity_score",
                "speculation_control_score",
                "engagement_score",
            ]

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
            with tempfile.NamedTemporaryFile(
                "w", dir=str(self.metadata_dir), delete=False, encoding="utf-8"
            ) as tf:
                json.dump(updated, tf, indent=2)
                temp_name = tf.name

            os.replace(temp_name, self.rolling_avg_file)

        except Exception as e:
            logger.error(f"Failed to update rolling average: {e}")
            if "temp_name" in locals() and os.path.exists(temp_name):
                os.unlink(temp_name)
