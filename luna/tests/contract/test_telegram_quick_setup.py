"""Telegram quick setup must be opt-in, and must say who it talks to.

`/api/telegram/onboarding/*` proxies to a service that creates the bot and learns the user's Telegram
user id. The dashboard presented that as a green-badged "Quick setup — recommended", so a self-hoster
reading their own dashboard would conclude Luna had vetted the service. It had not: the host was a
hardcoded default pointing at a third party.

So the service is opt-in (`luna.telegram.onboarding_service_url`, empty by default), the panel hides
itself when it is unset, and the badge names the trade rather than endorsing the path.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    root = tmp_path / "luna-home"
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("LUNA_HOME", str(root))
    monkeypatch.delenv("TELEGRAM_ONBOARDING_URL", raising=False)
    (root / "config.yaml").write_text("luna:\n  telegram:\n    onboarding_service_url: \"\"\n", encoding="utf-8")
    return root


def _set_config(monkeypatch, value: str) -> None:
    from hermes_cli.config import load_config, save_config

    config = load_config()
    config.setdefault("luna", {}).setdefault("telegram", {})["onboarding_service_url"] = value
    save_config(config)


# --- the default is off -------------------------------------------------------------


def test_quick_setup_is_off_by_default(home):
    """No hardcoded host. The upstream service URL is documentation, not a default."""
    from hermes_cli.web_server_messaging import _telegram_onboarding_base_url, telegram_onboarding_available

    assert _telegram_onboarding_base_url() == ""
    assert telegram_onboarding_available() is False


def test_the_third_party_host_is_not_used_as_a_fallback(home):
    """Regression guard on the specific failure: the old default resolved to a live host."""
    from hermes_cli.web_server_messaging import _telegram_onboarding_base_url

    resolved = _telegram_onboarding_base_url()
    assert "nousresearch.com" not in resolved
    assert "hermes-agent" not in resolved


def test_env_var_still_overrides(home, monkeypatch):
    """Operators who set the env var rather than the config key keep working."""
    from hermes_cli.web_server_messaging import _telegram_onboarding_base_url

    monkeypatch.setenv("TELEGRAM_ONBOARDING_URL", "https://setup.example.invalid")
    assert _telegram_onboarding_base_url() == "https://setup.example.invalid"


def test_trailing_slash_is_normalised(home, monkeypatch):
    from hermes_cli.web_server_messaging import _telegram_onboarding_base_url

    monkeypatch.setenv("TELEGRAM_ONBOARDING_URL", "https://setup.example.invalid/")
    assert _telegram_onboarding_base_url() == "https://setup.example.invalid"


# --- an explicitly configured service works ----------------------------------------


def test_configured_service_is_honoured(home):
    from hermes_cli.web_server_messaging import _telegram_onboarding_base_url, telegram_onboarding_available

    _set_config(__import__("pytest").MonkeyPatch(), "https://setup.example.invalid")
    assert _telegram_onboarding_base_url() == "https://setup.example.invalid"
    assert telegram_onboarding_available() is True


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",   # this URL is dialed by the server with a bearer token
        "file:///etc/passwd",
        "   ",
        "not-a-url",
    ],
)
def test_non_http_service_urls_are_refused(home, monkeypatch, value):
    """Only http(s) is dialed. The value goes into an outbound request carrying a bearer token."""
    from hermes_cli.web_server_messaging import _telegram_onboarding_base_url

    monkeypatch.setenv("TELEGRAM_ONBOARDING_URL", value)
    assert _telegram_onboarding_base_url() == ""


# --- the user agent ------------------------------------------------------------------


def test_user_agent_says_luna():
    """The service saw `HermesDashboard/<ver>` for requests the dashboard made as Luna."""
    from hermes_cli.web_server_messaging import _TELEGRAM_ONBOARDING_USER_AGENT

    assert _TELEGRAM_ONBOARDING_USER_AGENT.startswith("Luna/")
    assert "Hermes" not in _TELEGRAM_ONBOARDING_USER_AGENT


# --- the dashboard honours it -------------------------------------------------------


def test_catalog_reports_availability_only_for_configured_telegram(home, monkeypatch):
    """The panel is gated on this field, so it must be false when nothing is configured."""
    from hermes_cli.web_server_messaging import _build_catalog_entry

    monkeypatch.setenv("TELEGRAM_ONBOARDING_URL", "")
    assert _build_catalog_entry("telegram")["onboarding_available"] is False
    # Other platforms never have quick setup; they must not inherit the flag's meaning.
    assert _build_catalog_entry("discord")["onboarding_available"] is False

    monkeypatch.setenv("TELEGRAM_ONBOARDING_URL", "https://setup.example.invalid")
    assert _build_catalog_entry("telegram")["onboarding_available"] is True


def test_dashboard_platform_descriptions_use_the_luna_brand():
    """Channel copy says Luna, preserving the separately branded Hermes Relay product."""
    from hermes_cli.web_server_messaging import _PLATFORM_OVERRIDES

    descriptions = {
        platform: entry.get("description", "")
        for platform, entry in _PLATFORM_OVERRIDES.items()
    }
    branded = {name for name, description in descriptions.items() if "Hermes" in description}
    assert branded == {"relay"}
    assert "Hermes Relay" in descriptions["relay"]


def test_dashboard_hides_the_panel_when_it_is_not_configured():
    """Source-level: the QR panel is gated on the flag, not merely described as optional.

    A comment saying the panel is optional while rendering it unconditionally is exactly the
    failure this phase is about, so the gate is asserted at the call site.
    """
    source = (REPO_ROOT / "web" / "src" / "pages" / "ChannelsPage.tsx").read_text(encoding="utf-8")
    assert 'platform.id === "telegram" && platform.onboarding_available === true && (' in source, (
        "TelegramOnboardingPanel is not gated on onboarding_available — quick setup would be "
        "offered on installs that have not opted in"
    )


def test_the_recommendation_badge_is_gone():
    """A green 'recommended' badge on a third-party path is the claim being withdrawn."""
    source = (REPO_ROOT / "web" / "src" / "pages" / "ChannelsPage.tsx").read_text(encoding="utf-8")
    assert "<Badge tone=\"success\">recommended</Badge>" not in source
    assert "fewer steps" in source, "the trade should be named instead"
