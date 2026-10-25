"""``luna_cli`` — the standalone ``luna`` command.

It runs the hermes CLI bound to the Luna home and rebrands the user-facing program name, so the
product presents as **Luna**, not Hermes, without diverging from the upstream package layout (which
keeps upstream merges cheap).
"""

from __future__ import annotations

__all__ = ["main"]
