"""Artifact schema definition and validation."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field


@dataclass
class Artifact:
    """Structured work product from an agent.

    v1.0.0: Added optional `debt` field for typed compromise tracking.
    A "success" artifact is no longer terminal — agents must remain
    responsive to post-artifact directives.
    """

    status: str  # success, failure, escalation
    output: dict | str = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    debt: list[dict] = field(default_factory=list)
    agent_id: str = ""
    team_id: str = ""
    created_at: float = field(default_factory=time.time)

    VALID_STATUSES = ("success", "failure", "escalation")

    def validate(self) -> list[str]:
        errors = []
        if self.status not in self.VALID_STATUSES:
            errors.append(f"Invalid status '{self.status}'. Must be one of: {self.VALID_STATUSES}")
        return errors

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> Artifact:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> Artifact:
        return cls.from_dict(json.loads(text))
