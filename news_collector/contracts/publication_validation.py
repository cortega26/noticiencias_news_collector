"""Typed contracts for frontend publication validation and publication attempts."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ._constants import SCHEMA_VERSION

PublicationFailureClass = Literal[
    "schema_mismatch",
    "sidecar_missing_or_malformed",
    "permalink_collision",
    "taxonomy_contract_violation",
    "frontend_build_failure",
    "frontend_dist_failure",
    "frontend_audit_failure",
    "deploy_smoke_regression",
]


class FrontendCheckResult(BaseModel):
    """Result for one frontend command or staging step."""

    name: str
    command: str
    success: bool
    returncode: int = 0
    duration_seconds: float = Field(default=0.0, ge=0.0)
    stdout: str = ""
    stderr: str = ""
    failure_class: Optional[PublicationFailureClass] = None


class PublicationValidationSummary(BaseModel):
    """Machine-readable summary for a backend-driven frontend validation run."""

    schema_version: int = SCHEMA_VERSION
    generated_at: str
    frontend_root: str
    post_path: str
    manifest_path: str
    success: bool
    overall_failure_class: Optional[PublicationFailureClass] = None
    checks: List[FrontendCheckResult] = Field(default_factory=list)
    artifacts: Dict[str, str] = Field(default_factory=dict)


class PublicationAttemptStageResult(BaseModel):
    """Stage-level summary for a Refinery publication attempt."""

    name: str
    success: bool
    details: Dict[str, Any] = Field(default_factory=dict)


class PublicationAttemptSummary(BaseModel):
    """Machine-readable summary for a generated publication artifact / PR attempt."""

    schema_version: int = SCHEMA_VERSION
    generated_at: str
    article_id: str
    target_repo: Optional[str] = None
    output_filename: Optional[str] = None
    final_slug: Optional[str] = None
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    validation_summary_path: Optional[str] = None
    success: bool
    failure_class: Optional[PublicationFailureClass] = None
    stages: List[PublicationAttemptStageResult] = Field(default_factory=list)
