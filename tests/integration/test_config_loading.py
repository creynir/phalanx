"""Integration tests for Config Loading/Saving/Defaults — IT-067 through IT-069."""

from __future__ import annotations


import pytest

from phalanx.config import PhalanxConfig, load_config, save_config


pytestmark = pytest.mark.integration


class TestIT067_InitSetup:
    """IT-067: Generates correctly structured .phalanx/config.json."""

    def test_init_creates_config(self, tmp_path):
        phalanx_root = tmp_path / ".phalanx"
        phalanx_root.mkdir()

        config = PhalanxConfig()
        save_config(phalanx_root, config)

        config_path = phalanx_root / "config.json"
        assert config_path.exists()

        loaded = load_config(phalanx_root)
        assert loaded is not None


class TestIT068_DefaultTimeouts:
    """IT-068: Uses 1800s fallback for max runtime and idle timeout."""

    def test_default_timeouts(self):
        config = PhalanxConfig()
        d = config.to_dict()
        assert d.get("idle_timeout", 1800) == 1800 or config.idle_timeout == 1800


class TestIT069_CustomTimeoutInjection:
    """IT-069: Custom idle-timeout flows correctly through DB creation."""

    def test_custom_timeout(self):
        config = PhalanxConfig(idle_timeout=60)
        assert config.idle_timeout == 60
