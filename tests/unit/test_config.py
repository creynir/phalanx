"""Tests for phalanx.config module."""

from __future__ import annotations

import json
from pathlib import Path

from phalanx.config import (
    load_config,
    save_config,
    PhalanxConfig,
)


def test_load_default_config(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert isinstance(cfg, PhalanxConfig)
    assert cfg.default_backend == "codex"
    assert cfg.idle_timeout_seconds == 1800


def test_load_custom_config(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_data = {
        "default_backend": "claude",
        "idle_timeout_seconds": 60,
    }
    config_file.write_text(json.dumps(config_data))

    cfg = load_config(tmp_path)
    assert cfg.default_backend == "claude"
    assert cfg.idle_timeout_seconds == 60


def test_load_backend_overrides(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_data = {
        "default_backend": "cursor",
        "backend_overrides": {"lead": "codex", "worker": "cursor"},
    }
    config_file.write_text(json.dumps(config_data))

    cfg = load_config(tmp_path)
    assert cfg.backend_overrides == {"lead": "codex", "worker": "cursor"}


def test_load_invalid_config_falls_back_to_default(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text("invalid json")

    cfg = load_config(tmp_path)
    assert cfg.default_backend == "codex"


def test_save_config(tmp_path: Path):
    cfg = PhalanxConfig(
        default_backend="gemini",
        idle_timeout_seconds=120,
        backend_overrides={"lead": "codex"},
    )
    save_config(tmp_path, cfg)

    config_file = tmp_path / "config.json"
    assert config_file.exists()

    data = json.loads(config_file.read_text())
    assert data["default_backend"] == "gemini"
    assert data["idle_timeout_seconds"] == 120
    assert data["backend_overrides"]["lead"] == "codex"


def test_from_dict_ignores_unknown_fields():
    data = {"default_backend": "codex", "unknown_field": "ignore_me"}
    cfg = PhalanxConfig.from_dict(data)
    assert cfg.default_backend == "codex"
    assert not hasattr(cfg, "unknown_field")
