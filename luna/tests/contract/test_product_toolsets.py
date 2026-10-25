"""Contract: non-product tool families stay off every product surface.

PRODUCT_PLAN §4 removes the kanban / desktop_ui / browser / computer_use / homeassistant /
connections families and the non-Telegram platform toolsets (discord / yuanbao / feishu) from
the product toolsets — their code stays inert in the engine. The config template is the
shipped default: one of these names reappearing in it is a product-scope regression.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = REPO_ROOT / "luna" / "config" / "config.yaml.luna"

# Toolset names (toolsets.py TOOLSETS keys) that are not part of the product surface.
BANNED_TOOLSETS = frozenset({
    "kanban", "desktop_ui", "browser", "computer_use", "homeassistant", "connections",
    "discord", "discord_admin", "yuanbao", "feishu_doc", "feishu_drive",
})


def _config():
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def _configured_toolsets(cfg: dict) -> set[str]:
    names: set[str] = set()
    top = cfg.get("toolsets") or []
    names.update(top if isinstance(top, list) else [top])
    for surface, toolsets in (cfg.get("platform_toolsets") or {}).items():
        if isinstance(toolsets, list):
            names.update(toolsets)
        else:
            names.add(toolsets)
    return {n for n in names if isinstance(n, str)}


def test_no_removed_tool_family_is_configured():
    cfg = _config()
    leaked = sorted(_configured_toolsets(cfg) & BANNED_TOOLSETS)
    assert not leaked, f"product config enables removed tool families: {leaked}"


def test_no_non_telegram_platform_plugin_is_enabled():
    cfg = _config()
    enabled = (cfg.get("plugins") or {}).get("enabled") or []
    banned = sorted(n for n in enabled if isinstance(n, str) and (
        n.endswith("-platform") and n != "telegram-platform"
        or n in {"computer_use", "browser-browser-use", "browser-browserbase", "browser-firecrawl"}
    ))
    assert not banned, f"product config enables non-product platform plugins: {banned}"
