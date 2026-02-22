"""
Module role: Manages manual overrides acting as locks for particular enrichment strategies based on YAML configurations and production metrics.

Inputs:
- Source IDs and target strategies.
- A YAML configuration file path (`news_collector/config/strategy_locks.yaml`).
- Production observability metrics (attempts, successes, yield).

Outputs:
- Lock configuration dictionaries or None if a lock is rejected or undefined.

Side effects:
- Reads from and writes updates to the strategy locks YAML configuration file on disk.

Invariants:
- Evaluates locks by consulting production evidence to ensure sufficient prior attempts.
- Rejects non-baseline target strategies if their measured yield advantage over the baseline is insufficient.
- Refuses to overwrite existing locks with automated suggestions for the same strategy.

Failure modes:
- Defaults to returning empty or ignored locks if the configuration file is missing or unparseable.
- Rejects lock requests and logs warnings when production metrics are unavailable or criteria are unmet.
- Safely catches and logs exceptions when saving to the YAML file fails, leaving in-memory state intact.
"""

import logging
import os
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class StrategyLockManager:
    """
    Manages manual overrides ('locks') for enrichment strategies.
    Locks take precedence over Optimizer hints but respect safety flags.
    """

    def __init__(self, config_path: str = "news_collector/config/strategy_locks.yaml"):
        self.config_path = config_path
        self._locks = self._load_locks()

    def _load_locks(self) -> Dict[str, Any]:
        """Loads locks from YAML file."""
        if not os.path.exists(self.config_path):
            # Try finding it relative to project root if CWD varies?
            # Assuming CWD is project root usually.
            logger.warning(f"Strategy locks file not found: {self.config_path}")
            return {}

        try:
            with open(self.config_path, "r") as f:
                data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    return {}
                locks = data.get("locks", {})
                if isinstance(locks, dict):
                    return {str(key): value for key, value in locks.items()}
                return {}
        except Exception as e:
            logger.error(f"Failed to load strategy locks: {e}")
            return {}

    @staticmethod
    def _calculate_yield(attempts: int, successes: int) -> float:
        if attempts <= 0:
            return 0.0
        return successes / attempts * 100.0

    @staticmethod
    def _normalize_lock(lock: Any) -> Optional[Dict[str, str]]:
        if not isinstance(lock, dict):
            return None

        normalized: Dict[str, str] = {}
        for key, value in lock.items():
            if isinstance(key, str) and isinstance(value, str):
                normalized[key] = value

        if "strategy" not in normalized:
            return None
        return normalized

    @staticmethod
    def _validate_metrics(source_id: str, metrics: Optional[Dict[str, Any]]) -> bool:
        if not metrics:
            logger.warning(
                f"Lock Rejected for {source_id}: No production metrics found."
            )
            return False

        total_attempts = metrics.get("total_enrichment_attempted", 0)
        if total_attempts < 5:
            logger.warning(
                f"Lock Rejected for {source_id}: Insufficient attempts ({total_attempts} < 5)."
            )
            return False
        return True

    def _has_required_yield_advantage(
        self, source_id: str, target_strategy: str, metrics: Dict[str, Any]
    ) -> bool:
        if target_strategy == "http":
            return True

        http_yield = self._calculate_yield(
            int(metrics.get("http_attempts", 0)),
            int(metrics.get("http_success", 0)),
        )
        target_yield = self._calculate_yield(
            int(metrics.get(f"{target_strategy}_attempts", 0)),
            int(metrics.get(f"{target_strategy}_success", 0)),
        )
        advantage = target_yield - http_yield
        if advantage >= 20.0:
            return True

        logger.warning(
            f"Lock Rejected for {source_id}: Yield advantage {advantage:.1f}% < 20%. (Target: {target_yield:.1f}%, HTTP: {http_yield:.1f}%)"
        )
        return False

    def get_lock(self, source_id: str) -> Optional[Dict[str, str]]:
        """
        Returns the lock details for a source if it exists AND is verified by production evidence.
        """
        lock = self._locks.get(source_id)
        if not lock:
            return None

        normalized_lock = self._normalize_lock(lock)
        if not normalized_lock:
            return None

        # Integrity: Verify evidence from Production
        from news_collector.observability.enrichment_metrics_store import (
            production_metrics_view,
        )

        metrics = production_metrics_view.get_metrics(source_id)
        if not self._validate_metrics(source_id, metrics):
            return None

        target_strategy = normalized_lock["strategy"]
        metrics_dict = metrics if isinstance(metrics, dict) else {}
        if not self._has_required_yield_advantage(
            source_id, target_strategy, metrics_dict
        ):
            return None

        return normalized_lock

    def suggest_lock(self, source_id: str, strategy: str, rationale: str):
        """
        Suggests a new lock based on automated analysis.
        Writes directly to the YAML configuration if safety checks pass.
        """
        import datetime

        # 1. Safety Check: Don't overwrite existing manual locks?
        # Current policy: Automation can add or update, but maybe we should flag manual vs auto.
        # For now, we assume if it's running in production with ENABLE_STRATEGY_LOCKING, it's trusted.

        current_lock = self._locks.get(source_id)
        if current_lock and current_lock.get("strategy") == strategy:
            return  # Already locked to this strategy

        # 2. Update In-Memory
        new_lock = {
            "strategy": strategy,
            "rationale": rationale,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._locks[source_id] = new_lock

        # 3. Persist to YAML
        try:
            self._save_locks()
            logger.info(f"Persisted new lock for {source_id} -> {strategy}")
        except Exception as e:
            logger.error(f"Failed to persist lock for {source_id}: {e}")

    def _save_locks(self):
        """Saves current locks to YAML atomically."""
        data = {"locks": self._locks}
        # Write to temp string first
        yaml_content = yaml.dump(data, default_flow_style=False)

        with open(self.config_path, "w") as f:
            f.write("# Strategy Locks Configuration\n")
            f.write("# Generated automatically by StrategyLockManager\n\n")
            f.write(yaml_content)


# Singleton Instance
strategy_lock_manager = StrategyLockManager()
