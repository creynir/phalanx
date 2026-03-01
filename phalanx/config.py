"""Configuration loading, saving, and merging for Phalanx CLI."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 12):
    import tomllib
else:
    import tomli as tomllib


GLOBAL_CONFIG_DIR = Path.home() / ".phalanx"
GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_DIR / "config.toml"
WORKSPACE_CONFIG_DIR_NAME = ".phalanx"
WORKSPACE_CONFIG_FILE = "config.toml"

_DEFAULTS_DIR = Path(__file__).parent / "defaults"
_SHIPPED_CONFIG = _DEFAULTS_DIR / "config.toml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*. Returns a new dict."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def ensure_global_config() -> Path:
    """Copy shipped defaults to ~/.phalanx/config.toml if missing. Returns path."""
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not GLOBAL_CONFIG_PATH.exists():
        shutil.copy2(_SHIPPED_CONFIG, GLOBAL_CONFIG_PATH)
    return GLOBAL_CONFIG_PATH


def load_config(workspace: Path | None = None) -> dict[str, Any]:
    """Load merged config: shipped defaults → global → workspace overlay."""
    shipped = _load_toml(_SHIPPED_CONFIG)
    ensure_global_config()
    global_cfg = _load_toml(GLOBAL_CONFIG_PATH)
    merged = _deep_merge(shipped, global_cfg)

    if workspace is not None:
        ws_config = workspace / WORKSPACE_CONFIG_DIR_NAME / WORKSPACE_CONFIG_FILE
        if ws_config.exists():
            ws_cfg = _load_toml(ws_config)
            merged = _deep_merge(merged, ws_cfg)

    return merged


def save_global_config(cfg: dict[str, Any]) -> None:
    """Write full config dict to ~/.phalanx/config.toml."""
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with GLOBAL_CONFIG_PATH.open("wb") as f:
        tomli_w.dump(cfg, f)


def set_config_value(dotted_key: str, value: str) -> dict[str, Any]:
    """Set a single value by dotted path (e.g. 'models.cursor.coder') and save."""
    cfg = load_config()
    keys = dotted_key.split(".")
    target = cfg
    for k in keys[:-1]:
        target = target.setdefault(k, {})
    # Try to preserve types: int, float, bool, else str
    target[keys[-1]] = _coerce(value)
    save_global_config(cfg)
    return cfg


def _coerce(value: str) -> Any:
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def get_config_value(cfg: dict[str, Any], dotted_key: str) -> Any:
    """Read a value by dotted path. Raises KeyError if missing."""
    keys = dotted_key.split(".")
    target = cfg
    for k in keys:
        target = target[k]
    return target
