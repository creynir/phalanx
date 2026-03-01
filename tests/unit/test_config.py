"""Tests for phalanx.config module."""

from __future__ import annotations

from pathlib import Path

import pytest

from phalanx.config import (
    _deep_merge,
    _coerce,
    get_config_value,
    load_config,
    save_global_config,
    set_config_value,
    GLOBAL_CONFIG_PATH,
)


class TestDeepMerge:
    def test_flat(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_override(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested(self):
        base = {"x": {"a": 1, "b": 2}}
        over = {"x": {"b": 3, "c": 4}}
        assert _deep_merge(base, over) == {"x": {"a": 1, "b": 3, "c": 4}}

    def test_no_mutation(self):
        base = {"x": {"a": 1}}
        _deep_merge(base, {"x": {"b": 2}})
        assert base == {"x": {"a": 1}}


class TestCoerce:
    def test_int(self):
        assert _coerce("42") == 42

    def test_float(self):
        assert _coerce("3.14") == 3.14

    def test_bool_true(self):
        assert _coerce("true") is True

    def test_bool_false(self):
        assert _coerce("False") is False

    def test_string(self):
        assert _coerce("hello") == "hello"


class TestLoadConfig:
    def test_loads_shipped_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_DIR", tmp_path)
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")
        cfg = load_config()
        assert "models" in cfg
        assert "cursor" in cfg["models"]
        assert cfg["models"]["cursor"]["default"] == "gemini-3.1-pro"

    def test_global_overrides_shipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_DIR", tmp_path)
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        import tomli_w
        custom = {"models": {"cursor": {"coder": "opus-4.6"}}}
        with (tmp_path / "config.toml").open("wb") as f:
            tomli_w.dump(custom, f)

        cfg = load_config()
        assert cfg["models"]["cursor"]["coder"] == "opus-4.6"
        assert cfg["models"]["cursor"]["default"] == "gemini-3.1-pro"  # from shipped

    def test_workspace_overrides_global(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_DIR", tmp_path / "global")
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_PATH", tmp_path / "global" / "config.toml")

        ws = tmp_path / "workspace"
        ws_cfg_dir = ws / ".phalanx"
        ws_cfg_dir.mkdir(parents=True)

        import tomli_w
        ws_config = {"defaults": {"backend": "gemini"}}
        with (ws_cfg_dir / "config.toml").open("wb") as f:
            tomli_w.dump(ws_config, f)

        cfg = load_config(workspace=ws)
        assert cfg["defaults"]["backend"] == "gemini"


class TestGetConfigValue:
    def test_nested(self):
        cfg = {"models": {"cursor": {"coder": "sonnet-4.6"}}}
        assert get_config_value(cfg, "models.cursor.coder") == "sonnet-4.6"

    def test_missing_raises(self):
        with pytest.raises(KeyError):
            get_config_value({}, "no.such.key")


class TestSetConfigValue:
    def test_set_and_read(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_DIR", tmp_path)
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        cfg = set_config_value("models.cursor.coder", "opus-4.6")
        assert cfg["models"]["cursor"]["coder"] == "opus-4.6"

        reloaded = load_config()
        assert reloaded["models"]["cursor"]["coder"] == "opus-4.6"


class TestSaveGlobalConfig:
    def test_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_DIR", tmp_path)
        monkeypatch.setattr("phalanx.config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        data = {"test": {"key": "value", "num": 42}}
        save_global_config(data)

        from phalanx.config import _load_toml
        loaded = _load_toml(tmp_path / "config.toml")
        assert loaded == data
