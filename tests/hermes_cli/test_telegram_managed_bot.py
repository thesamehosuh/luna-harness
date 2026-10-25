"""Tests for hermes_cli.telegram_managed_bot — QR codes, deep links, pairing."""

from __future__ import annotations

from pathlib import PureWindowsPath
from unittest.mock import MagicMock, patch

from hermes_cli.telegram_managed_bot import (
    TELEGRAM_ONBOARDING_URL_ENV,
    TelegramPairing,
    _api_url,
    auto_setup_telegram_bot_result,
    create_pairing,
    poll_for_setup_result,
    print_qr_code,
    render_qr_terminal,
)
from hermes_cli import setup_platforms


VALID_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
SECOND_VALID_TOKEN = "987654321:abcdefghijklmnopqrstuvwxyzABCDEF"


class TestQRCode:
    def test_render_returns_string(self):
        result = render_qr_terminal("https://example.com")
        if result:
            assert isinstance(result, str)
            assert len(result) > 10

    def test_render_graceful_without_qrcode(self):
        with patch.dict("sys.modules", {"qrcode": None}):
            render_qr_terminal("https://example.com")

    def test_print_qr_code_with_url(self, capsys):
        print_qr_code("https://t.me/newbot/Bot/test_bot")
        captured = capsys.readouterr()
        assert "https://t.me/newbot/Bot/test_bot" in captured.out

    def test_print_qr_code_tip_targets_active_interpreter(self, capsys):
        # Regression for #111695: a bare `pip install` targets the wrong
        # environment when Hermes runs in an isolated venv (which has no pip
        # module at all). The fallback tip must name the interpreter that is
        # actually running, via uv.
        import sys

        with patch.dict("sys.modules", {"qrcode": None}):
            print_qr_code("https://t.me/newbot/Bot/test_bot")
        captured = capsys.readouterr()
        assert f"uv pip install --python {sys.executable} qrcode" in captured.out
        assert " pip install qrcode)" not in captured.out


class TestCreatePairing:
    def test_no_service_is_configured_by_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("LUNA_HOME", str(tmp_path))
        monkeypatch.delenv(TELEGRAM_ONBOARDING_URL_ENV, raising=False)
        (tmp_path / "config.yaml").write_text("luna:\n  telegram:\n    onboarding_service_url: ''\n")

        assert _api_url() == ""
        with patch("hermes_cli.telegram_managed_bot.httpx.post") as post:
            assert create_pairing() is None
        post.assert_not_called()

    def test_auto_setup_explains_disabled_service_and_keeps_manual_path(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("LUNA_HOME", str(tmp_path))
        monkeypatch.delenv(TELEGRAM_ONBOARDING_URL_ENV, raising=False)
        (tmp_path / "config.yaml").write_text("luna:\n  telegram:\n    onboarding_service_url: ''\n")

        with patch("hermes_cli.telegram_managed_bot.httpx.post") as post:
            assert auto_setup_telegram_bot_result() is None
        post.assert_not_called()
        output = capsys.readouterr().out
        assert "Quick Telegram setup is off" in output
        assert "manual BotFather setup" in output

    def test_configured_service_uses_the_dashboard_setting(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("LUNA_HOME", str(tmp_path))
        monkeypatch.delenv(TELEGRAM_ONBOARDING_URL_ENV, raising=False)
        (tmp_path / "config.yaml").write_text(
            "luna:\n  telegram:\n    onboarding_service_url: https://setup.example.invalid/\n"
        )

        assert _api_url() == "https://setup.example.invalid"

    def test_explicit_api_url_still_requires_http_scheme(self):
        with patch("hermes_cli.telegram_managed_bot.httpx.post") as post:
            assert create_pairing("javascript:alert(1)") is None
        post.assert_not_called()

    def test_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "pairing_id": "abcdefghijklmnop",
            "poll_token": "secret-token",
            "suggested_username": "hermes_abcdefghijklmnop_bot",
            "deep_link": "https://t.me/newbot/HermesSetupBot/hermes_abcdefghijklmnop_bot?name=Hermes+Agent",
            "qr_payload": "https://t.me/newbot/HermesSetupBot/hermes_abcdefghijklmnop_bot?name=Hermes+Agent",
            "expires_at": "2026-05-18T00:00:00.000Z",
        }

        with patch(
            "hermes_cli.telegram_managed_bot.httpx.post", return_value=mock_resp
        ) as post:
            pairing = create_pairing("https://api.example.com", bot_name="Hermes Agent")

        assert pairing == TelegramPairing(
            pairing_id="abcdefghijklmnop",
            poll_token="secret-token",
            suggested_username="hermes_abcdefghijklmnop_bot",
            deep_link="https://t.me/newbot/HermesSetupBot/hermes_abcdefghijklmnop_bot?name=Hermes+Agent",
            qr_payload="https://t.me/newbot/HermesSetupBot/hermes_abcdefghijklmnop_bot?name=Hermes+Agent",
            expires_at="2026-05-18T00:00:00.000Z",
        )
        post.assert_called_once_with(
            "https://api.example.com/v1/telegram/pairings",
            json={"bot_name": "Hermes Agent"},
            timeout=10.0,
        )

    def test_failure_status(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch(
            "hermes_cli.telegram_managed_bot.httpx.post", return_value=mock_resp
        ):
            assert create_pairing("https://api.example.com") is None


    def test_uses_env_override(self, monkeypatch):
        monkeypatch.setenv(TELEGRAM_ONBOARDING_URL_ENV, "https://worker.example")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch(
            "hermes_cli.telegram_managed_bot.httpx.post", return_value=mock_resp
        ) as post:
            create_pairing()
        assert post.call_args.args[0] == "https://worker.example/v1/telegram/pairings"


class TestPollForToken:
    def pairing(self):
        return TelegramPairing(
            pairing_id="abcdefghijklmnop",
            poll_token="secret-token",
            suggested_username="hermes_abcdefghijklmnop_bot",
            deep_link="https://t.me/newbot/HermesSetupBot/hermes_abcdefghijklmnop_bot",
            qr_payload="https://t.me/newbot/HermesSetupBot/hermes_abcdefghijklmnop_bot",
        )

    def test_immediate_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "bot_username": "hermes_abcdefghijklmnop_bot",
            "owner_user_id": 42,
            "status": "ready",
            "token": VALID_TOKEN,
        }

        with patch(
            "hermes_cli.telegram_managed_bot.httpx.get", return_value=mock_resp
        ) as get:
            with patch("hermes_cli.telegram_managed_bot.time.sleep"):
                result = poll_for_setup_result(
                    "https://api.example.com", self.pairing(), timeout=5
                )

        assert result is not None and result.token == VALID_TOKEN
        assert (
            get.call_args.args[0]
            == "https://api.example.com/v1/telegram/pairings/abcdefghijklmnop"
        )
        assert get.call_args.kwargs["headers"] == {
            "Authorization": "Bearer secret-token"
        }




    def test_eventual_success(self):
        not_ready = MagicMock()
        not_ready.status_code = 200
        not_ready.json.return_value = {"status": "waiting"}

        ready = MagicMock()
        ready.status_code = 200
        ready.json.return_value = {"status": "ready", "token": SECOND_VALID_TOKEN}

        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return not_ready
            return ready

        with patch("hermes_cli.telegram_managed_bot.httpx.get", side_effect=fake_get):
            with patch("hermes_cli.telegram_managed_bot.time.sleep"):
                result = poll_for_setup_result(
                    "https://api.example.com", self.pairing(), timeout=30
                )
                assert result is not None and result.token == SECOND_VALID_TOKEN


class TestSetupTelegramAuto:
    def test_setup_wizard_defaults_to_manual_botfather_flow(self, monkeypatch):
        from hermes_cli import setup

        prompt_calls = []

        def fake_prompt(question, default=None, **kwargs):
            prompt_calls.append((question, default))
            return default

        monkeypatch.setattr(setup, "_info", lambda *args: None)
        monkeypatch.setattr(setup, "print_error", lambda *args: None)
        monkeypatch.setattr(setup, "prompt", fake_prompt)
        monkeypatch.setattr(setup_platforms, "_prompt_telegram_bot_token", lambda: VALID_TOKEN)
        monkeypatch.setattr(
            setup_platforms,
            "_setup_telegram_auto_result",
            lambda: (_ for _ in ()).throw(AssertionError("quick setup should not be the default")),
        )

        token, result = setup_platforms._obtain_telegram_token()

        assert (token, result) == (VALID_TOKEN, None)
        assert prompt_calls == [("Choice [1/2]", "2")]

    def test_gateway_setup_defaults_to_manual_botfather_flow(self, monkeypatch):
        from hermes_cli import gateway

        prompt_calls = []

        def fake_prompt(question, default=None, **kwargs):
            prompt_calls.append((question, default))
            return default

        monkeypatch.setattr(gateway, "_print_info_lines", lambda *args: None)
        monkeypatch.setattr(gateway, "prompt", fake_prompt)

        assert gateway._telegram_auto_setup("TELEGRAM_BOT_TOKEN") == (False, None)
        assert prompt_calls == [("  Choice [1/2]", "2")]

    def test_setup_result_passes_profile_name_for_profile_home(self, monkeypatch, tmp_path):
        from hermes_cli import setup

        seen = {}
        profile_home = tmp_path / ".hermes" / "profiles" / "oracle"
        profile_home.mkdir(parents=True)

        monkeypatch.setattr(setup, "get_hermes_home", lambda: profile_home)

        def fake_auto_setup_telegram_bot_result(*, profile_name=None):
            seen["profile_name"] = profile_name
            return None

        monkeypatch.setattr(
            "hermes_cli.telegram_managed_bot.auto_setup_telegram_bot_result",
            fake_auto_setup_telegram_bot_result,
        )

        assert setup_platforms._setup_telegram_auto_result() is None
        assert seen["profile_name"] == "oracle"

    def test_profile_name_from_home_path_handles_windows_separators(self):
        from hermes_cli.setup_platforms import _profile_name_from_hermes_home

        assert (
            _profile_name_from_hermes_home(
                PureWindowsPath(r"C:\Users\test\AppData\Local\hermes\profiles\oracle")
            )
            == "oracle"
        )
