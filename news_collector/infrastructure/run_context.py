"""
Module role: Maintains a global singleton to manage execution run contexts, ensuring operations link to a specific environment and run ID.

Inputs:
- Environment variables (`RUN_ENVIRONMENT`, `CI`, `GITHUB_ACTIONS`).
- Explicit environment override strings.

Outputs:
- A context dictionary containing the run ID, detected environment, and start timestamp.

Side effects:
- None (strictly in-memory state management dependent on environment configuration).

Invariants:
- Maintains exactly one instantiated singleton state per application runtime.
- Constrains valid manual environment overrides to a predefined set of recognized environments.

Failure modes:
- Raises ValueError if an explicit environment assignment is not part of the recognized whitelist.
- Silently defaults to 'development' if environment variables are absent or unrecognized during detection.
"""

import os
import uuid
from datetime import datetime


class RunContextManager:
    """
    Singleton managing global context for the current execution run.
    Ensures every operation is attributable to a specific run_id and environment.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RunContextManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.run_id = str(uuid.uuid4())
        self.start_time = datetime.utcnow()
        self.environment = self._detect_environment()
        self._initialized = True

    def _detect_environment(self) -> str:
        """
        Detects the runtime environment.
        Priority:
        1. Explicit ENV var: RUN_ENVIRONMENT (production, staging, test, canary)
        2. Detection of CI/Test runners
        3. Default: development (local)
        """
        env_var = os.getenv("RUN_ENVIRONMENT", "").lower()
        if env_var in ["production", "staging", "test", "canary", "dry_run"]:
            return env_var

        # CI Detection
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
            return "test"

        # Default
        return "development"

    def set_environment(self, env: str):
        """Allow manual override (e.g., from CLI flags like --dry-run)."""
        valid_envs = [
            "production",
            "staging",
            "test",
            "canary",
            "dry_run",
            "development",
        ]
        if env not in valid_envs:
            raise ValueError(f"Invalid environment: {env}")
        self.environment = env

    def get_context(self) -> dict:
        return {
            "run_id": self.run_id,
            "environment": self.environment,
            "timestamp": self.start_time.isoformat(),
        }


# Global Singleton
run_context = RunContextManager()
