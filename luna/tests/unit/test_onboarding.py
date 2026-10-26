"""Onboarding wizard state machine (PRODUCT_PLAN P3): step checks, persona presets, dry-run wake
test. Deterministic: scratch LUNA_HOME, no network (honcho probe is expected to fail), no jev."""

from __future__ import annotations

import os

import pytest

from luna_cli import onboarding

CONFIG = """\
model:
  provider: opencode
  model: gpt-5-mini
  base_url: https://opencode.ai/zen/v1
telegram:
  group_allowed_chats: ["-100123"]
  allow_admin_from: ["1001"]
memory:
  provider: honcho
honcho:
  baseUrl: http://127.0.0.1:9
luna:
  room:
    chat_id: "-100123"
  ambient:
    room_register: "a loud gaming server."
    jev:
      timeout_seconds: 20
      route: [zen-free, local]
      providers:
        zen-free:
          base_url: https://opencode.ai/zen/v1
          model: jev-1.13-free
          api_key_env: OPENCODE_ZEN_API_KEY
          tier: free
        local:
          base_url: http://127.0.0.1:8700/v1
          model: clm-latest
          tier: local
    thresholds:
      message_min_value: 0.55
"""


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("LUNA_INDEX_DB", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    # Host env keys must not leak into the provider-key scan.
    for name in list(os.environ):
        if name.endswith(("_API_KEY", "_TOKEN")):
            monkeypatch.delenv(name, raising=False)
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / ".env").write_text("OPENCODE_ZEN_API_KEY=sk-real-enough\n", encoding="utf-8")
    return tmp_path


# ── Step checks ──────────────────────────────────────────────────────────────────────────────────


def test_provider_check_finds_model_and_key(home):
    report = onboarding.check_provider()
    assert report["configured"] is True
    assert report["readiness"] == "configured"
    assert report["key_present"] is True


def test_provider_check_flags_missing_key(home, monkeypatch):
    (home / ".env").write_text("OPENCODE_ZEN_API_KEY=PASTE_ME\n", encoding="utf-8")
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    report = onboarding.check_provider()
    assert report["status"] == "todo"


def test_telegram_token_cannot_satisfy_provider_credentials(home, monkeypatch):
    (home / ".env").write_text("TELEGRAM_BOT_TOKEN=synthetic-token\n")
    assert onboarding.check_provider()["status"] == "todo"


def test_provider_reads_engine_default_model_and_matches_key(home):
    (home / "config.yaml").write_text("model: {provider: openai, default: synthetic, base_url: https://api.openai.com/v1}\n")
    assert onboarding.check_provider()["status"] == "todo"  # Zen's key cannot authenticate OpenAI
    (home / ".env").write_text("OPENAI_API_KEY=synthetic\n")
    assert onboarding.check_provider()["configured"] is True


def test_localhost_in_remote_url_is_not_a_local_provider(home):
    (home / ".env").write_text("")
    (home / "config.yaml").write_text("model: {provider: custom, default: synthetic, base_url: 'https://localhost.example/v1'}\n")
    assert onboarding.check_provider()["status"] == "todo"


def test_container_local_model_endpoint_resolves_to_host():
    assert onboarding._container_endpoint("http://127.0.0.1:1234/v1") == "http://host.docker.internal:1234/v1"
    assert onboarding._container_endpoint("https://example.com/v1") == "https://example.com/v1"


def test_template_group_and_admin_ids_do_not_complete_setup(home, monkeypatch):
    (home / "config.yaml").write_text("telegram: {group_allowed_chats: ['-1000000000000'], allow_admin_from: [0]}\nluna: {room: {chat_id: '0'}}\n")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic")
    report = onboarding.check_telegram()
    assert report["status"] == "todo"
    assert report["admin_configured"] is False


def test_telegram_check_reads_token_and_group(home, monkeypatch):
    report = onboarding.check_telegram()
    assert report["status"] == "todo"  # no bot token yet
    assert "bot token" in report["detail"]

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    report = onboarding.check_telegram()
    assert report["status"] == "todo"  # Access alone does not configure notifications.
    assert "notification home" in report["detail"]
    report = onboarding.configure_telegram_destinations("1001", "-100123")
    assert report["status"] == "done"
    assert report["groups"] == ["-100123"]


def test_honcho_check_reports_down_stack(home):
    report = onboarding.check_honcho()
    assert report["status"] == "todo"
    assert "not reachable" in report["detail"]


def test_character_check_reads_soul(home):
    assert onboarding.check_character()["status"] == "todo"
    (home / "SOUL.md").write_text("# Luna\nA persona.\n", encoding="utf-8")
    report = onboarding.check_character()
    assert report["status"] == "done"


def test_step_report_shape(home):
    report = onboarding.step_report()
    assert [s["id"] for s in report["steps"]] == list(onboarding.STEP_ORDER)
    assert report["complete"] is False
    assert all("title" in s and "detail" in s for s in report["steps"])


# ── Persona presets ──────────────────────────────────────────────────────────────────────────────


def test_personas_include_generic_and_current(home):
    presets = onboarding.personas()
    assert [p["id"] for p in presets] == ["generic", "warm-friend", "dry-wit", "curious-mind"]
    (home / "SOUL.md").write_text("# Luna\n", encoding="utf-8")
    presets = onboarding.personas()
    assert [p["id"] for p in presets] == ["current", "generic", "warm-friend", "dry-wit", "curious-mind"]
    assert presets[0]["content"].startswith("# Luna")


# ── Wake test (offline) ──────────────────────────────────────────────────────────────────────────


def test_wake_test_dry_run_reports_stage0_and_chain(home):
    report = onboarding.run_wake_test(live=False)
    assert report["live"] is False
    assert report["stage0"]["allowed"] is True
    assert report["questions"]
    assert report["route_chain"], "configured jev route chain must be reported"
    assert report["route_chain"][0]["key_set"] is True
    assert "no call spent" in report["detail"]
    assert report.get("decision") is None


def test_wake_test_records_result_for_the_step_check(home):
    onboarding.run_wake_test(live=False)
    report = onboarding.check_wake_test()
    assert report["last"]["ok"] is True
    assert report["status"] == "todo"  # a dry-run does not prove Jev can answer


def test_managed_memory_refresh_keeps_database_passwords(home, monkeypatch):
    stack = home / "honcho"
    stack.mkdir()
    monkeypatch.setenv("LUNA_MEMORY_API_KEY", "first-synthetic")
    onboarding._seed_honcho_env(stack)
    first = (stack / ".env").read_text().splitlines()[:2]
    monkeypatch.setenv("LUNA_MEMORY_API_KEY", "second-synthetic")
    onboarding._seed_honcho_env(stack, refresh=True)
    after = (stack / ".env").read_text()
    assert after.splitlines()[:2] == first
    assert "LUNA_MEMORY_API_KEY='second-synthetic'" in after
    assert "LUNA_EMBEDDING_API_KEY='second-synthetic'" in after


def test_wake_test_uses_configured_room_register(home):
    from luna_core.cascade import Candidate, CascadeConfig, build_state

    register = None
    cfg = onboarding._configured_cascade()
    assert cfg.message_min_value == 0.55  # thresholds from config are applied
    state = build_state(
        Candidate(chat_id="c", message_id="m", text="hello there"), [],
        config=CascadeConfig(), room_register=register or "a loud gaming server.",
    )
    assert state["room"]["register"] == "a loud gaming server."


# ── Honcho env seeding ───────────────────────────────────────────────────────────────────────────


def test_honcho_env_seeded_once_with_generated_passwords(home, monkeypatch):
    stack = home / "honcho"
    stack.mkdir()
    (stack / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    written = onboarding._seed_honcho_env(stack)
    assert "POSTGRES_PASSWORD" in written and "REDIS_PASSWORD" in written
    content = (stack / ".env").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=" in content
    assert content.split("POSTGRES_PASSWORD=")[1].splitlines()[0] not in ("", "REPLACE_ME")
    # An existing .env is never rewritten.
    assert onboarding._seed_honcho_env(stack) == []


def test_honcho_up_refuses_without_runtime_stack(home, monkeypatch):
    """No stack under $HERMES_HOME/honcho → refuse; NEVER fall back to the repo tree."""
    monkeypatch.setattr(onboarding.subprocess, "run",
                        lambda *a, **k: pytest.fail("docker must not run without a runtime stack"))
    report = onboarding.honcho_up()
    assert report["ok"] is False
    assert "not found" in report["detail"]


def test_honcho_stack_dir_ignores_the_repo_tree(home):
    """The repo's luna/honcho is not a bring-up target (secrets + compose live at runtime)."""
    assert onboarding._honcho_stack_dir() is None


def test_memory_start_uses_home_specific_compose_project(home, monkeypatch):
    from types import SimpleNamespace
    stack = home / "honcho"
    stack.mkdir()
    (stack / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.setenv("LUNA_MEMORY_API_KEY", "synthetic")
    calls = []
    monkeypatch.setattr(onboarding.subprocess, "run", lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(onboarding, "_probe_health", lambda *args, **kwargs: True)
    assert onboarding.honcho_up()["ok"] is True
    assert "--project-name" in calls[0]
    project = calls[0][calls[0].index("--project-name") + 1]
    assert project.startswith("luna-")
    assert project != "honcho"
    env = (stack / ".env").read_text()
    assert "LUNA_MEMORY_API_KEY='synthetic'" in env
    assert "EMBEDDING_VECTOR_DIMENSIONS='1536'" in env


def test_setup_and_character_share_presets_without_duplicate_starter(home):
    from luna_cli import character
    from luna_core.personas import library
    starter = library()[0]["content"]
    (home / "SOUL.md").write_text(starter, encoding="utf-8")
    presets = onboarding.personas()
    assert presets == character.personas()
    assert "current" not in [preset["id"] for preset in presets]
    assert [preset["id"] for preset in presets if preset["is_current"]] == ["generic"]
    custom = "# My character\nAn existing custom voice.\n"
    (home / "SOUL.md").write_text(custom, encoding="utf-8")
    assert onboarding.personas()[0]["content"] == custom
    assert onboarding.personas()[0]["is_current"] is True


def test_telegram_destinations_reach_the_real_gateway_and_room_together(home, monkeypatch):
    import yaml
    from gateway.config import load_gateway_config, Platform
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    report = onboarding.configure_telegram_destinations("2002", "-100456", "owner")
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["luna"]["room"]["chat_id"] == "-100456"
    assert cfg["luna"]["notify"]["operator_chat"]["telegram"] == "2002"
    assert cfg["telegram"]["allow_admin_from"] == ["1001", "2002"]
    assert cfg["telegram"]["group_allowed_chats"] == ["-100123", "-100456"]
    assert load_gateway_config().get_home_channel(Platform.TELEGRAM).chat_id == "2002"
    assert report["home_chat_id"] == "2002"
    assert report["room_bound"] is True


def test_telegram_pairing_defaults_preserve_existing_home_topic_and_operator(home):
    import yaml
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    existing = {"platform": "telegram", "chat_id": "-100789", "name": "Saved", "thread_id": "7"}
    cfg["platforms"] = {"telegram": {"home_channel": existing}}
    cfg["luna"]["notify"] = {"operator_chat": {"telegram": "3003"}}
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    onboarding.configure_telegram_destinations("2002")
    saved = yaml.safe_load((home / "config.yaml").read_text())
    assert saved["platforms"]["telegram"]["home_channel"] == existing
    assert saved["luna"]["notify"]["operator_chat"]["telegram"] == "3003"
    assert saved["luna"]["room"]["chat_id"] == "-100123"


@pytest.mark.parametrize("owner,group", [("bad", "-100456"), ("2002", "100456"), ("0", "-100456")])
def test_telegram_invalid_ids_cannot_partially_change_destinations(home, owner, group):
    before = (home / "config.yaml").read_bytes()
    with pytest.raises(ValueError):
        onboarding.configure_telegram_destinations(owner, group)
    assert (home / "config.yaml").read_bytes() == before


def test_telegram_status_detects_saved_access_with_missing_home_and_room(home, monkeypatch):
    import yaml
    cfg = yaml.safe_load((home / "config.yaml").read_text()); cfg["luna"]["room"]["chat_id"] = ""
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    report = onboarding.check_telegram()
    assert report["status"] == "todo"
    assert "notification home" in report["detail"]
    assert "companion group binding" in report["detail"]


def test_group_notification_home_is_explicit_and_keeps_operator_private(home):
    import yaml
    onboarding.configure_telegram_destinations("2002", "-100456", "group")
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["platforms"]["telegram"]["home_channel"]["chat_id"] == "-100456"
    assert cfg["luna"]["notify"]["operator_chat"]["telegram"] == "2002"
