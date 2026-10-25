"""Contract test: the gateway systemd unit stays CLI-owned.

The hermes CLI derives the gateway service name from HERMES_HOME (``hermes-gateway-bede7b14`` for
``~/.luna``) and only ever manages that name. Hand-installing a unit under the bare
``hermes-gateway.service`` leaves an enabled unit the CLI never touches: it boots, races the CLI's
unit for the single Telegram token, gets stopped and left ``failed``, and ``luna gateway restart``
then resets a unit systemd has not loaded ("Failed to reset failed state of unit ...: Unit ... not
loaded"). install.sh must delegate the unit to the CLI and only *remove* a stale bare one.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SYSTEMD_DIR = REPO_ROOT / "luna" / "systemd"
INSTALL_SH = REPO_ROOT / "luna" / "deploy" / "install.sh"


def test_gateway_unit_is_not_hand_installed():
    assert not (SYSTEMD_DIR / "hermes-gateway.service").exists(), (
        "luna/systemd/hermes-gateway.service is obsolete: `hermes gateway install` generates the "
        "unit under the CLI-resolved name for this HERMES_HOME."
    )


def test_install_uses_cli_unit_generation_without_legacy_cleanup():
    text = INSTALL_SH.read_text(encoding="utf-8")
    helper = (REPO_ROOT / "luna/deploy/install_units.py").read_text()
    assert "get_service_name" in helper
    assert "generate_systemd_unit" in helper
    assert "install_units.py" in text
    assert 'rm -f "$UNIT_DIR/hermes-gateway.service"' not in text
    assert "disable --now hermes-gateway" not in text
