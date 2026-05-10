"""Typed contracts for deterministic end-to-end pipeline runs."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from ._constants import SCHEMA_VERSION
from pydantic import BaseModel, Field

PipelineStageName = Literal[
    "collection",
    "validation",
    "scoring",
    "selection",
    "export",
    "approval",
    "publication",
    "frontend_validation",
]


class PipelineStageSnapshot(BaseModel):
    """Machine-readable snapshot for one major E2E pipeline stage."""

    stage: PipelineStageName
    success: bool
    details: Dict[str, Any] = Field(default_factory=dict)
    artifact_path: Optional[str] = None
    failure_class: Optional[str] = None


class PipelineE2ERunSummary(BaseModel):
    """Top-level summary for one deterministic E2E pipeline scenario run."""

    schema_version: int = SCHEMA_VERSION
    scenario: str
    generated_at: str
    fixture_path: str
    success: bool
    diagnostics_bundle_dir: str
    selected_article_id: Optional[str] = None
    expected_article_id: Optional[str] = None
    root_failure_stage: Optional[PipelineStageName] = None
    first_divergence: Optional[str] = None
    publication_attempt_summary_path: Optional[str] = None
    frontend_validation_summary_path: Optional[str] = None
    stages: List[PipelineStageSnapshot] = Field(default_factory=list)
