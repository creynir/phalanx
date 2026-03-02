"""Configuration management.

Loads from .phalanx/config.json with sensible defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_CONFIG_FILE = "config.json"


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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PhalanxConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


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
