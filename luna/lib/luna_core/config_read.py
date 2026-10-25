"""Canonical config reads for the Luna overlay plugins.

The engine owns config loading (profile overlay, managed scope, env interpolation), so plugins
must go through ``hermes_cli.config`` rather than parsing ``config.yaml`` themselves — that is
what ``tests/hermes_cli/test_config_read_guard.py`` enforces.

``hermes_cli`` is imported lazily: the overlay is also exercised by the luna unit suite in a
lightweight venv with no engine dependencies, where these helpers fall back to a direct read so
plugin code keeps working in isolation.
"""

from __future__ import annotations

from luna_core.runtime import home as runtime_home, getenv

import os
from pathlib import Path
from typing import Any, Dict, Optional


def with_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Merge raw/staged editor settings without expanding credential references."""
    import copy
    try:
        from hermes_cli.config import DEFAULT_CONFIG, _deep_merge
    except ImportError:
        return copy.deepcopy(raw)
    return _deep_merge(copy.deepcopy(DEFAULT_CONFIG), raw)


def hermes_home() -> Path:
    return runtime_home()


def _canonical() -> Optional[Dict[str, Any]]:
    """The engine's merged config, or ``None`` when the engine is not importable."""
    try:
        from hermes_cli.config import load_config_readonly
    except ImportError:
        return None
    return load_config_readonly() or {}


def load_config() -> Dict[str, Any]:
    """Merged config via the engine loader, falling back to the raw user file."""
    data = _canonical()
    if data is not None:
        return data
    import yaml

    path = hermes_home() / "config.yaml"
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}


def section(*keys: str, default: Any = None) -> Any:
    """Walk nested keys through the merged config (``section("luna", "room", "chat_id")``)."""
    node: Any = load_config()
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return default if node is None else node
