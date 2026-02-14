import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("editorial.policy")

class IntegrityError(Exception):
    """Raised when policy integrity check fails."""
    pass

@dataclass
class EditorialPolicy:
    mode: str
    critic_threshold: float
    auditor_threshold: float
    require_caveats: bool
    require_no_hallucinations: bool = False
    
    # Integrity Metadata
    version: str = "1.0.0"
    policy_sha256: str = ""

    def compute_sha256(self) -> str:
        """Computes SHA256 of core policy fields."""
        # Canonical representation:
        # We sort keys to ensure deterministic hash.
        # Format: key=value|key=value|...
        # Fields: mode, critic_threshold, auditor_threshold, require_caveats, require_no_hallucinations
        
        data = {
            "mode": self.mode,
            "critic_threshold": self.critic_threshold,
            "auditor_threshold": self.auditor_threshold,
            "require_caveats": self.require_caveats,
            "require_no_hallucinations": self.require_no_hallucinations
        }
        
        # Sort keys
        sorted_keys = sorted(data.keys())
        
        # Build string
        parts = []
        for key in sorted_keys:
             val = data[key]
             # Handle bools explicitly
             if isinstance(val, bool):
                 val_str = "true" if val else "false"
             elif isinstance(val, float):
                 val_str = f"{val:.1f}" # Ensure consistent float formatting (1 decimal place for thresholds)
             else:
                 val_str = str(val)
             parts.append(f"{key}={val_str}")
             
        canonical_str = "|".join(parts)
        # logger.debug(f"Canonical Policy String: {canonical_str}")
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def verify_integrity(self, manifest_path: Path):
        """
        Verifies loaded policy against the provided manifest file.
        Raises IntegrityError on failure.
        """
        if not manifest_path.exists():
            raise IntegrityError(f"Policy Manifest not found at {manifest_path}")

        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            
            # Check Version (Optional but good practice)
            manifest_version = manifest_data.get("version")
            if manifest_version != self.version:
                 logger.warning(f"Policy Version Mismatch: Loaded {self.version}, Manifest {manifest_version}")

            # Verify Hash
            expected_hash = manifest_data.get("sha256")
            computed_hash = self.compute_sha256()
            
            if computed_hash != expected_hash:
                 error_msg = (
                     f"CRITICAL: Policy Integrity Failure!\n"
                     f"Expected SHA256: {expected_hash}\n"
                     f"Computed SHA256: {computed_hash}\n"
                     f"Mode: {self.mode}\n"
                     f"Policy has likely been tampered with or drifted from manifest."
                 )
                 logger.critical(error_msg)
                 raise IntegrityError(error_msg)
            
            self.policy_sha256 = computed_hash
            logger.info(f"✅ Policy Integrity Verified: {computed_hash[:8]}...")
            
        except Exception as e:
            if isinstance(e, IntegrityError):
                raise e
            raise IntegrityError(f"Failed to verify manifest: {e}") 

    @classmethod
    def from_mode(cls, mode: str) -> "EditorialPolicy":
        """
        Factory to create policy from mode string.
        Defaults to 'standard' if mode is unknown.
        """
        normalized_mode = mode.lower() if mode else "standard"
        
        if normalized_mode == "velocity":
            return cls(
                mode="velocity",
                critic_threshold=70.0,
                auditor_threshold=0.0, # Advisory
                require_caveats=False
            )
            
        elif normalized_mode == "strict":
            return cls(
                mode="strict",
                critic_threshold=85.0,
                auditor_threshold=8.5,
                require_caveats=True,
                require_no_hallucinations=True
            )
            
        else: # Standard (Default)
            return cls(
                mode="standard",
                critic_threshold=80.0,
                auditor_threshold=8.0,
                require_caveats=True
            )
