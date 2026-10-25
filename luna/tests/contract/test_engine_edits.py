"""Contract: Luna's engine edits are folded into the tree and recorded.

We own the engine tree (PRODUCT_PLAN P1): the pre-P1 ``luna/patches/`` series is normal code
now. Every engine file carrying a Luna product edit must be listed in
``luna/docs/engine-vendor.md`` so a future re-vendor can re-apply the edits cheaply. The
behavioural contract tier (private symbols, cache invariant, routing, cron guards) gates the
edits themselves; this tier gates the *inventory*.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PATCH_DIR = REPO_ROOT / "luna" / "patches"
VENDOR_DOC = REPO_ROOT / "luna" / "docs" / "engine-vendor.md"

# Engine files carrying Luna product edits (folded patch series 0001-0015 + P1 trims + P2 hooks).
# Keep in step with luna/docs/engine-vendor.md.
EDITED_ENGINE_FILES = (
    "hermes_constants.py",
    "hermes_cli/product_runtime.py",
    "hermes_cli/config_home.py",
    "hermes_cli/profiles.py",
    "hermes_cli/plugins_discovery.py",
    "plugins/memory/__init__.py",
    "hermes_cli/main_tui_launch.py",
    "hermes_cli/free_tier_bootstrap.py",
    "hermes_cli/skin_engine.py",
    "tui_gateway/server.py",
    "tui_gateway/change_watcher.py",
    "agent/system_prompt.py",
    "agent/bedrock_adapter.py",
    "agent/vertex_adapter.py",
    "gateway/slash_access.py",
    "hermes_cli/web_routers/status.py",
    "hermes_cli/config.py",
    "hermes_cli/config_lock.py",
    "hermes_cli/_file_lock.py",
    "scripts/install.ps1",
    "apps/bootstrap-installer/src-tauri/src/launcher.rs",
    "apps/bootstrap-installer/src-tauri/src/desktop_controls.rs",
    "apps/bootstrap-installer/src/desktop-controls.tsx",
    "web/src/themes/theme-runtime.ts",
    "hermes_cli/auth_device_flow.py",
    "hermes_cli/session_export_html.py",
    "hermes_cli/dashboard_auth/middleware.py",
    "hermes_cli/dashboard_auth/routes.py",
    "apps/bootstrap-installer/src-tauri/src/lib.rs",
    "apps/bootstrap-installer/src-tauri/build.rs",
    "web/src/pages/MemoryPage.tsx",
    "web/src/components/MemoryReasoningSelector.tsx",
    "web/src/components/AutoField.tsx",
    "plugins/memory/honcho/client.py",
    "agent/agent_init.py",
    "agent/auxiliary_client.py",
    "agent/conversation_loop.py",
    "agent/turn_finalizer.py",
    "agent/turn_context.py",
    "hermes_cli/runtime_provider.py",
    "gateway/operator_route.py",
    "gateway/platforms/base.py",
    "gateway/run.py",
    "gateway/run_busy.py",
    "gateway/run_config_loaders.py",
    "gateway/run_inbound.py",
    "gateway/run_notifications.py",
    "gateway/run_turn.py",
    "gateway/run_turn_runner.py",
    "hermes_cli/_parser.py",
    "hermes_cli/_startup_fast.py",
    "hermes_cli/banner.py",
    "hermes_cli/cli_commands_mixin.py",
    "hermes_cli/cli_info_mixin.py",
    "hermes_cli/config_defaults.py",
    "hermes_cli/tools_config.py",
    "hermes_cli/dashboard_auth/login_page.py",
    "hermes_cli/main.py",
    "hermes_cli/mcp_config.py",
    "hermes_cli/plugin_catalog.py",
    "hermes_cli/plugins.py",
    "hermes_cli/subcommands/doctor.py",
    "hermes_cli/tips.py",
    "hermes_cli/update_cmd_deps.py",
    "hermes_cli/update_contract.py",
    "hermes_cli/uninstall.py",
    "hermes_cli/web_routers/config_env.py",
    "hermes_cli/web_routers/dashboard_ui.py",
    "hermes_cli/web_routers/messaging.py",
    "hermes_cli/web_server.py",
    "hermes_cli/web_server_dashboard.py",
    "hermes_cli/web_server_config.py",
    "hermes_cli/completion.py",
    "hermes_cli/telegram_managed_bot.py",
    "hermes_cli/setup_platforms.py",
    "hermes_cli/gateway.py",
    "hermes_cli/web_server_messaging.py",
    "hermes_cli/web_server_oauth.py",
    "hermes_cli/web_server_lifecycle.py",
    "hermes_cli/web_server_gateway.py",
    "hermes_cli/web_routers/actions.py",
    "hermes_cli/web_routers/sessions.py",
    "hermes_cli/web_routers/_common.py",
    "hermes_cli/web_routers/chat_ws_errors.py",
    "hermes_logging.py",
    "hermes_cli/web_server_chat.py",
    "hermes_cli/web_routers/models.py",
    "plugins/platforms/telegram/adapter.py",
    "cron/scheduler.py",
    "cron/scheduler_delivery.py",
    "tools/cronjob_job_args.py",
    "tools/cronjob_tools.py",
)


def test_no_patch_series_remains():
    leftover = sorted(p.name for p in PATCH_DIR.glob("*.patch")) if PATCH_DIR.is_dir() else []
    assert not leftover, (
        f"luna/patches/ still ships a patch series {leftover}; engine edits live in the tree "
        "(PRODUCT_PLAN P1) and are recorded in luna/docs/engine-vendor.md"
    )


def test_every_edited_engine_file_is_recorded():
    text = VENDOR_DOC.read_text(encoding="utf-8")
    missing = [rel for rel in EDITED_ENGINE_FILES if rel not in text]
    assert not missing, (
        f"engine files with Luna edits missing from luna/docs/engine-vendor.md: {missing}"
    )


def test_every_edited_engine_file_exists():
    missing = [rel for rel in EDITED_ENGINE_FILES if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"recorded engine edits point at missing files: {missing}"


def test_recorded_paths_exist():
    """Every ``*.py`` path listed in the vendor doc's edit table must exist in the tree."""
    text = VENDOR_DOC.read_text(encoding="utf-8")
    listed = set(re.findall(
        r"`((?:gateway|cron|tools|plugins|hermes_cli)/[^`]+|hermes_logging\.py)`", text
    ))
    missing = sorted(
        p for p in listed
        if p.endswith(".py") and not (REPO_ROOT / p).is_file()
    )
    assert not missing, f"luna/docs/engine-vendor.md lists paths that do not exist: {missing}"
