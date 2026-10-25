"""The dashboard server exposes Luna-branded commands and guidance in UI payloads."""

from hermes_cli.web_server_oauth import _OAUTH_PROVIDER_CATALOG
from hermes_cli.web_server_dashboard import _HEADLESS_MSG
from hermes_cli.web_server_config import _dashboard_skew_restart_hint
from hermes_cli.web_routers import actions, chat_ws_errors, messaging
from hermes_cli.web_routers._common import CORRUPT_STORE_DETAIL


def test_documentation_path_reaches_luna_instead_of_swagger(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from hermes_cli import web_server
    from hermes_cli.web_server_dashboard import mount_spa
    (tmp_path / "index.html").write_text('<html><head></head><body>LUNA_PRODUCT_DOCS</body></html>')
    monkeypatch.setattr(web_server, "WEB_DIST", tmp_path)
    monkeypatch.setattr(web_server.app.router, "routes", [route for route in web_server.app.router.routes
                        if getattr(route, "path", "") != "/{full_path:path}"])
    monkeypatch.delenv("HERMES_SERVE_HEADLESS", raising=False)
    mount_spa(web_server.app)
    response = TestClient(web_server.app).get("/docs")
    assert response.status_code == 200
    assert "LUNA_PRODUCT_DOCS" in response.text
    assert "swagger-ui" not in response.text


def test_oauth_catalog_commands_use_luna_cli():
    commands = {
        row["id"]: row["cli_command"]
        for row in _OAUTH_PROVIDER_CATALOG
        if row["cli_command"].startswith("hermes ")
    }

    assert commands == {}
    assert next(row for row in _OAUTH_PROVIDER_CATALOG if row["id"] == "nous")["cli_command"] == (
        "luna auth add nous"
    )
    assert next(row for row in _OAUTH_PROVIDER_CATALOG if row["id"] == "anthropic")["cli_command"] == (
        "luna auth add anthropic"
    )


def test_visible_dashboard_and_recovery_copy_uses_luna_commands(monkeypatch):
    monkeypatch.delenv("HERMES_SERVE_HEADLESS", raising=False)

    assert "luna serve" in _HEADLESS_MSG
    assert "luna dashboard --port" in _dashboard_skew_restart_hint()
    assert "hermes" not in chat_ws_errors.CHAT_START_FAILED.lower()
    assert "luna doctor" in CORRUPT_STORE_DETAIL["message"]
    assert "Luna gateway setup" in messaging._MESSAGING_ENV_FALLBACKS["WEIXIN_ACCOUNT_ID"]["description"]


def test_update_copy_rebrands_commands_but_keeps_package_identifiers():
    copy = actions._luna_update_copy(
        "Hermes Agent runs as a published image; run `hermes update`; package: hermes-agent; "
        "Hermes Relay; Hermes Model API; ghcr.io/nousresearch/hermes-agent:latest"
    )

    assert "Luna runs as a published image" in copy
    assert "run `luna update`" in copy
    assert "hermes-agent" in copy
    assert "Hermes Relay" in copy
    assert "Hermes Model API" in copy
    assert "ghcr.io/nousresearch/hermes-agent:latest" in copy
    assert "hermes update" not in copy
