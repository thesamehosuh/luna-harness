"""Structured models behind /api/luna/* — verdict parsing, ledger reads, threshold writes,
identity operations. Deterministic: scratch LUNA_HOME, no network, no jev calls."""

from __future__ import annotations

import json

import pytest

from luna_cli import api_models
from luna_core import db as luna_db
from luna_core.identity import IdentityRegistry

# The verdict log carries ids, reasons and weights — never message or reply text.
VERDICT_LINE = (
    "2026-10-02 12:00:01 [luna-ambient] [MSG] at=2026-10-02T12:00:01 via=free "
    "verdict=message value=0.71 addressed=0.10 openq=0.60 fit=0.50 "
    "reason=useful answer is welcome | who=\"iris\"\n"
)
SAID_LINE = (
    "2026-10-02 12:00:05 [luna-ambient] at=2026-10-02T12:00:05 via=free event=said "
    "who=\"iris\"\n"
)
NOISE_LINE = "2026-10-02 12:00:02 gateway connected\n"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("LUNA_INDEX_DB", raising=False)
    monkeypatch.delenv("LUNA_PEER_PREFIX", raising=False)
    (tmp_path / "config.yaml").write_text(
        "luna:\n  ambient:\n    thresholds:\n      message_min_value: 0.55\n",
        encoding="utf-8",
    )
    (tmp_path / "logs").mkdir()
    return tmp_path


def _index_db(home):
    path = home / "luna-state.db"
    conn = luna_db.connect(path)
    luna_db.init_db(conn)
    return conn


# ── Verdict events ───────────────────────────────────────────────────────────────────────────────


def test_parse_verdict_line_is_structured():
    event = api_models.parse_verdict_line(VERDICT_LINE)
    assert event["kind"] == "verdict"
    assert event["action"] == "message"
    assert event["route"] == "free"
    assert event["who"] == "iris"
    assert "text" not in event  # privacy: no message text in the log
    assert event["value"] == "0.71"
    assert event["reason"].startswith("useful answer")


def test_parse_verdict_line_said_event():
    event = api_models.parse_verdict_line(SAID_LINE)
    assert event["kind"] == "said"
    assert event["who"] == "iris"
    assert "reply" not in event  # privacy: no reply text in the log


def test_parse_verdict_line_ignores_noise():
    assert api_models.parse_verdict_line(NOISE_LINE) is None


def test_verdicts_tails_and_filters(home):
    log = home / "logs" / "agent.log"
    log.write_text(NOISE_LINE + VERDICT_LINE + SAID_LINE, encoding="utf-8")
    events = api_models.verdicts(10)
    assert [e["kind"] for e in events] == ["verdict", "said"]
    assert api_models.verdict_log_state()["exists"] is True


# ── Wake ledger ──────────────────────────────────────────────────────────────────────────────────


def test_wakes_reads_the_ledger(home):
    conn = _index_db(home)
    try:
        conn.execute(
            "INSERT INTO wakes(kind, chat_id, trigger_message_id, created_at, detail) VALUES (?,?,?,?,?)",
            ("reaction", "-1001", "42", "2026-10-02T12:00:00Z",
             json.dumps({"emoji": "😭", "value": 0.8, "reason": "chaos"})),
        )
        conn.commit()
    finally:
        conn.close()
    wakes = api_models.wakes(10)
    assert len(wakes) == 1
    assert wakes[0]["kind"] == "reaction" and wakes[0]["emoji"] == "😭"
    assert wakes[0]["reason"] == "chaos"


def test_wakes_missing_db_is_empty(home):
    assert api_models.wakes(10) == []


# ── Thresholds ───────────────────────────────────────────────────────────────────────────────────


def test_thresholds_reports_defaults_and_overrides(home):
    state = api_models.thresholds()
    assert state["values"]["message_min_value"]["overridden"] is True
    assert state["values"]["message_min_fit"]["overridden"] is False
    assert state["values"]["message_min_fit"]["default"] is not None
    assert state["values"]["message_min_value"]["type"] == "float"


def test_thresholds_always_carry_usable_bounds(home):
    """Every threshold must reach the client with a real range.

    The Behaviour page rendered every slider with a hardcoded ``max=1`` because the API never sent
    bounds. A threshold whose true range is 0-1440 (``min_minutes_since_luna``) then painted pinned
    to the far right, and dragging left wrote 0 — silently zeroing a wake cooldown in config.yaml.
    A missing bound makes the client fall back to a plain number input, so bounds are not optional.
    """
    values = api_models.thresholds()["values"]
    assert values, "no thresholds resolved"
    for key, entry in values.items():
        assert isinstance(entry.get("min"), (int, float)), key
        assert isinstance(entry.get("max"), (int, float)), key
        assert entry["max"] > entry["min"], key
        assert isinstance(entry.get("step"), (int, float)), key
        assert entry["step"] > 0, key


def test_threshold_bounds_contain_the_shipped_default(home):
    """A slider can only represent its default if the default sits inside the advertised range."""
    for key, entry in api_models.thresholds()["values"].items():
        default = entry["default"]
        if default is None:
            continue
        assert entry["min"] <= default <= entry["max"], key


def test_minutes_threshold_is_not_stepped_in_hundredths(home):
    """`min_minutes_since_luna` is typed float only because the cascade does arithmetic on it; a
    control stepping it by 0.01 minutes is noise."""
    entry = api_models.thresholds()["values"]["min_minutes_since_luna"]
    assert entry["step"] == 1
    assert entry["min"] == 0
    assert entry["max"] == 1440


def test_threshold_bounds_come_from_the_cascade_range_table(home):
    """The slider and the generated config form must agree on a range, so both read the same
    `_RANGES` table rather than one of them guessing."""
    from luna_cli import config_schema

    bounds = config_schema.threshold_bounds()
    values = api_models.thresholds()["values"]
    assert bounds
    for key in bounds:
        assert key in values, key
        assert values[key]["min"] == bounds[key]["min"], key
        assert values[key]["max"] == bounds[key]["max"], key


def test_thresholds_degrade_without_bounds_rather_than_guessing(home, monkeypatch):
    """Without the overlay lib there is no range to publish. The response must omit bounds so the
    client renders a number input, not invent a range it cannot justify."""
    from luna_cli import config_schema

    monkeypatch.setattr(config_schema, "threshold_bounds", dict)
    values = api_models.thresholds()["values"]
    assert values
    for entry in values.values():
        assert "min" not in entry
        assert "max" not in entry


def test_set_thresholds_updates_and_validates(home):
    result = api_models.set_thresholds({"message_min_value": 0.55, "min_new_messages": 5})
    assert result["results"]["message_min_value"]["ok"]
    assert result["results"]["min_new_messages"]["ok"]
    assert result["state"]["values"]["message_min_value"]["value"] == 0.55

    bad = api_models.set_thresholds({"message_min_value": "not-a-number"})
    assert not bad["results"]["message_min_value"]["ok"]


def test_set_thresholds_refuses_unknown_keys(home):
    result = api_models.set_thresholds({"no_such_threshold": 1})
    assert not result["results"]["no_such_threshold"]["ok"]


def test_set_thresholds_reset_via_null(home):
    api_models.set_thresholds({"message_min_value": 0.55})
    result = api_models.set_thresholds({"message_min_value": None})
    assert result["results"]["message_min_value"]["ok"]
    assert result["state"]["values"]["message_min_value"]["overridden"] is False


# ── Health / cost shapes ─────────────────────────────────────────────────────────────────────────


def test_health_shape(home):
    report = api_models.health()
    assert report["config_exists"] is True
    assert report["db_exists"] is False
    assert report["jev"]["status"] == "off"


def test_cost_without_ledger(home):
    spend = api_models.cost(7)
    assert spend["calls"] == 0
    assert spend["window"] == "last 7 days"


def test_cost_reads_jev_usage(home):
    conn = _index_db(home)
    try:
        luna_db.record_jev_usage(
            conn, route="zen-free",
            usage={"input_tokens": 100, "output_tokens": 10, "cost": 0.001},
        )
        conn.commit()
    finally:
        conn.close()
    spend = api_models.cost(0)
    assert spend["calls"] == 1
    assert spend["total_usd"] == pytest.approx(0.001)


# ── People ───────────────────────────────────────────────────────────────────────────────────────


def test_identity_upsert_and_list(home):
    result = api_models.identity_upsert(
        "telegram", "1001",
        {"display_name": "Iris", "pronouns": "she/her", "role": "friend", "aliases": ["iris"]},
    )
    assert result["ok"], result
    identities = api_models.identity_list()
    assert len(identities) == 1
    assert identities[0]["display_name"] == "Iris"
    assert identities[0]["is_manual"] is True


def test_identity_merge_reports_errors_and_success(home):
    api_models.identity_upsert("telegram", "1001", {"display_name": "Iris"})
    merged = api_models.identity_merge("1001", "1002")
    assert merged.get("error") is None, merged
    assert merged["user_id"] == "1001" and merged["user_id_alt"] == "1002"

    refused = api_models.identity_merge("1001", "1001")
    assert refused.get("error")


def test_peers_audit_ok_when_mapped(home):
    conn = _index_db(home)
    try:
        registry = IdentityRegistry(conn, prefix="telegram_")
        registry.set_manual("telegram", "1001", display_name="Iris")
    finally:
        conn.close()
    report = api_models.peers_audit()
    assert report["ok"] is True
    assert report["unmapped"] == [] and report["colliding"] == []
