"""Team context store for accumulated cross-step learnings.

Persists context entries to the team_context SQLite table and provides
retrieval with token budget truncation.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from phalanx.db import StateDB

logger = logging.getLogger(__name__)


@dataclass
class ContextEntry:
    """A single learning extracted from a completed step."""

    context_type: str  # convention, pattern, constraint, discovery
    content: str
    step_name: str | None = None
    source_agent_id: str | None = None
    skill_run_id: str | None = None

    VALID_TYPES = ("convention", "pattern", "constraint", "discovery")

    def validate(self) -> list[str]:
        errors = []
        if self.context_type not in self.VALID_TYPES:
            errors.append(f"Invalid context_type '{self.context_type}'")
        if not self.content:
            errors.append("Content is required")
        return errors

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]


class TeamContextStore:
    """Manages accumulated cross-step learnings for a team."""

    def __init__(self, db: StateDB) -> None:
        self._db = db

    def add_entries(self, team_id: str, entries: list[ContextEntry]) -> int:
        """Persist new context entries. Deduplicates by content hash.

        Returns the count of entries actually added.
        """
        added = 0
        for entry in entries:
            errors = entry.validate()
            if errors:
                logger.warning("Invalid context entry: %s", errors)
                continue

            result = self._db.add_team_context(
                team_id=team_id,
                context_type=entry.context_type,
                content=entry.content,
                content_hash=entry.content_hash,
                skill_run_id=entry.skill_run_id,
                step_name=entry.step_name,
                source_agent_id=entry.source_agent_id,
            )
            if result is not None:
                added += 1

        return added

    def get_context(
        self,
        team_id: str,
        max_tokens: int = 2000,
    ) -> str:
        """Retrieve accumulated context, truncated to token budget.

        Most recent entries are prioritized. Uses rough 4-char-per-token
        estimation for budget management.
        """
        entries = self._db.get_team_context(team_id)
        if not entries:
            return ""

        char_budget = max_tokens * 4
        parts = []
        used = 0

        for entry in reversed(entries):
            line = f"- [{entry['context_type']}] {entry['content']}"
            if used + len(line) > char_budget:
                break
            parts.append(line)
            used += len(line)

        parts.reverse()
        return "\n".join(parts)

    def clear(self, team_id: str) -> None:
        """Reset all context for a team."""
        self._db.clear_team_context(team_id)
