"""Entry point for the ``luna`` command.

Two jobs:

1. Bind the CLI to the Luna home (``$LUNA_HOME`` / ``$HERMES_HOME`` / ``~/.luna``) so state, config,
   sessions, and plugins all live under one Luna directory.
2. Present as **Luna**: the upstream parser hardcodes ``prog="hermes"`` and a "Hermes Agent"
   description; we patch the parser builder at call time (main imports it lazily) so ``luna --help``
   reads ``usage: luna`` and the product name is Luna. The banner is already Luna via the skin.

Everything else — every subcommand (`gateway`, `doctor`, `cron`, …) — is the hermes CLI,
unchanged. Terminal surfaces are dev tools now: user tasks belong to the dashboard (D4), and the
``luna tune`` / ``luna peers`` CLIs are retired (P5).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PRODUCT_NAME = "luna"
PRODUCT_DESCRIPTION = "Luna - a member of the group"


def luna_home() -> str:
    """Resolve the Luna home: ``$LUNA_HOME`` → ``$HERMES_HOME`` → ``~/.luna``."""
    installed = Path(sys.prefix).parent
    marker = installed / ".luna-state-home"
    if marker.is_file():
        default = marker.read_text().strip()
    else:
        from hermes_constants import _get_platform_default_hermes_home
        default = str(installed) if (installed / ".luna-assemble-manifest.json").is_file() else str(_get_platform_default_hermes_home())
    raw = os.getenv("LUNA_HOME") or os.getenv("HERMES_HOME") or default
    return os.path.expanduser(os.path.expandvars(raw))


def _rebrand() -> None:
    """Make the CLI present as Luna. Best-effort; never fatal."""
    try:
        import hermes_cli._parser as parser_mod
    except Exception:
        return

    original = getattr(parser_mod, "build_top_level_parser", None)
    if original is None or getattr(original, "_luna_rebranded", False):
        return

    def build_top_level_parser():  # type: ignore[no-redef]
        parser, subparsers, chat_parser = original()
        parser.prog = PRODUCT_NAME
        parser.description = PRODUCT_DESCRIPTION
        return parser, subparsers, chat_parser

    build_top_level_parser._luna_rebranded = True  # type: ignore[attr-defined]
    parser_mod.build_top_level_parser = build_top_level_parser
    # main() imports the symbol lazily, so patching the module attribute is enough.


def _handoff_selected_runtime():
    # Existing service units may pin an older immutable runtime. Resolve the
    # installation's verified pointer before importing engine/gateway modules.
    installed = Path(sys.prefix).parent.resolve()
    if (installed / ".luna-state-home").is_file():
        from hermes_cli.product_runtime import code_root
        selected = code_root(Path(os.environ["HERMES_HOME"])).resolve()
        if selected != installed:
            python = selected / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
            os.execv(str(python), [str(python), "-m", "luna_cli.main", *sys.argv[1:]])


def main() -> int:
    os.environ["HERMES_HOME"] = luna_home()
    # The entry alias must not override a named profile selected later by the engine.
    os.environ.pop("LUNA_HOME", None)
    _handoff_selected_runtime()
    # A release carries compiled assets, not the Node source/build toolchain.
    dist = Path(__file__).resolve().parents[3] / "hermes_cli" / "web_dist"
    if (dist / "index.html").is_file():
        os.environ["HERMES_WEB_DIST"] = str(dist)
    if len(sys.argv) == 1:
        sys.argv.append("dashboard")
    _rebrand()
    from hermes_cli.main import main as hermes_main

    result = hermes_main()
    return int(result) if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
