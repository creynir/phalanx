"""Cost aggregation for token usage across agents and teams.

Records per-agent token consumption and provides aggregation views by role,
agent, and model. Cost/pricing fields have been removed; only token counts
are tracked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from phalanx.db import StateDB

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Parsed token usage from a backend."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AgentCostBreakdown:
    """Per-agent token breakdown."""

    agent_id: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    records: int = 0


@dataclass
class TeamCostBreakdown:
    """Per-team token breakdown with role and agent aggregations."""

    team_id: str
    by_agent: dict[str, AgentCostBreakdown] = field(default_factory=dict)
    by_role: dict[str, dict] = field(default_factory=dict)
    by_model: dict[str, dict] = field(default_factory=dict)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        d = {
            "team_id": self.team_id,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "by_role": self.by_role,
            "by_model": self.by_model,
        }
        return d


class CostAggregator:
    """Records and aggregates token usage."""

    def __init__(self, db: StateDB) -> None:
        self._db = db

    def record_usage(
        self,
        team_id: str,
        agent_id: str,
        role: str,
        backend: str,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Persist a single token usage record.

        Validates input before recording. Gracefully handles DB failures.
        """
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            logger.warning(
                "Non-integer token counts for %s — skipping",
                agent_id,
            )
            return

        if input_tokens < 0 or output_tokens < 0:
            logger.warning(
                "Invalid token counts for %s: in=%d out=%d — skipping",
                agent_id,
                input_tokens,
                output_tokens,
            )
            return

        try:
            self._db.record_token_usage(
                team_id=team_id,
                agent_id=agent_id,
                role=role,
                backend=backend,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception as e:
            logger.error(
                "Failed to record token usage for %s: %s — monitoring continues",
                agent_id,
                e,
            )

    def get_team_costs(self, team_id: str) -> TeamCostBreakdown:
        """Aggregate token usage by role, agent, and model for a team."""
        records = self._db.get_team_token_usage(team_id)
        breakdown = TeamCostBreakdown(team_id=team_id)

        for r in records:
            inp = r["input_tokens"]
            out = r["output_tokens"]
            total = r["total_tokens"]

            breakdown.total_input_tokens += inp
            breakdown.total_output_tokens += out
            breakdown.total_tokens += total

            agent_id = r["agent_id"]
            if agent_id not in breakdown.by_agent:
                breakdown.by_agent[agent_id] = AgentCostBreakdown(agent_id=agent_id)
            ab = breakdown.by_agent[agent_id]
            ab.total_input_tokens += inp
            ab.total_output_tokens += out
            ab.total_tokens += total
            ab.records += 1

            role = r["role"]
            if role not in breakdown.by_role:
                breakdown.by_role[role] = {"input_tokens": 0, "output_tokens": 0}
            breakdown.by_role[role]["input_tokens"] += inp
            breakdown.by_role[role]["output_tokens"] += out

            model = r.get("model") or "unknown"
            if model not in breakdown.by_model:
                breakdown.by_model[model] = {"input_tokens": 0, "output_tokens": 0}
            breakdown.by_model[model]["input_tokens"] += inp
            breakdown.by_model[model]["output_tokens"] += out

        return breakdown

    def get_agent_costs(self, agent_id: str) -> AgentCostBreakdown:
        """Get cumulative token usage for a single agent."""
        records = self._db.get_agent_token_usage(agent_id)
        ab = AgentCostBreakdown(agent_id=agent_id)

        for r in records:
            ab.total_input_tokens += r["input_tokens"]
            ab.total_output_tokens += r["output_tokens"]
            ab.total_tokens += r["total_tokens"]
            ab.records += 1

        return ab
