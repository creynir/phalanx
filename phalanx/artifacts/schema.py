"""Artifact Pydantic models and validation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ArtifactStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    ESCALATION = "escalation_required"


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0


class Artifact(BaseModel):
    status: ArtifactStatus
    agent_id: str
    team_id: str
    output: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
