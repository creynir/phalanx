"""Configuration management.

Loads from .phalanx/config.json with sensible defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CONFIG_FILE = "config.json"


@dataclass
class ContinualLearningConfig:
    """Configuration for cross-step context injection."""

    enabled: bool = False
    max_context_tokens: int = 2000
    extraction_model: str | None = None
    context_types: list[str] | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ContinualLearningConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class PhalanxConfig:
    """Runtime configuration."""

    default_backend: str = "cursor"
    default_model: str | None = None
    idle_timeout_seconds: int = 1800  # 30 minutes
    max_runtime_seconds: int = 1800  # 30 minutes
    stall_check_interval: int = 20  # seconds
    max_retries: int = 3
    gc_after_hours: int = 24
    auto_approve: bool = False
    monitor_poll_interval: int = 20
    enable_engineering_manager: bool = False
    cost_table: dict | None = None
    rate_limit_backoff_seconds: int = 60
    continual_learning: ContinualLearningConfig = field(default_factory=ContinualLearningConfig)

    def to_dict(self) -> dict:
        d = asdict(self)
        if isinstance(self.continual_learning, ContinualLearningConfig):
            d["continual_learning"] = self.continual_learning.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PhalanxConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known}
        if "continual_learning" in filtered and isinstance(filtered["continual_learning"], dict):
            filtered["continual_learning"] = ContinualLearningConfig.from_dict(
                filtered["continual_learning"]
            )
        return cls(**filtered)


def load_config(phalanx_root: Path) -> PhalanxConfig:
    """Load config from .phalanx/config.json, falling back to defaults."""
    config_path = phalanx_root / DEFAULT_CONFIG_FILE
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            return PhalanxConfig.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            pass
    return PhalanxConfig()


def save_config(phalanx_root: Path, config: PhalanxConfig) -> None:
    """Save config to .phalanx/config.json."""
    config_path = phalanx_root / DEFAULT_CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config.to_dict(), indent=2) + "\n")
