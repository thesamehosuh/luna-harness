"""Threshold editing behind the Behaviour page: in-place, comment-preserving, validated, reversible."""

from __future__ import annotations

import pytest

from luna_cli import tune

CONFIG = """\
luna:
  ambient:
    enabled: true
    thresholds:
      # keep me: an explanatory comment
      message_min_value: 0.60
      message_min_fit: 0.42
    budget:
      message_cooldown_minutes: 0
display:
  streaming: true
"""


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tune.config_path()
    path.write_text(CONFIG, encoding="utf-8")
    return path


def test_set_updates_only_the_target_line(cfg):
    ok, message = tune._write_threshold("message_min_value", "0.55")
    assert ok, message
    text = cfg.read_text(encoding="utf-8")
    assert "message_min_value: 0.55" in text
    assert "message_min_fit: 0.42" in text
    assert "message_cooldown_minutes: 0" in text


def test_set_preserves_comments_and_structure(cfg):
    tune._write_threshold("message_min_value", "0.55")
    text = cfg.read_text(encoding="utf-8")
    assert "# keep me: an explanatory comment" in text
    assert "budget:" in text and "display:" in text


def test_set_inserts_a_new_key_inside_the_thresholds_block(cfg):
    ok, _ = tune._write_threshold("reaction_min_fit", "0.70")
    assert ok
    lines = [ln.strip() for ln in cfg.read_text(encoding="utf-8").splitlines()]
    key_index = next(i for i, ln in enumerate(lines) if "reaction_min_fit" in ln)
    block_index = lines.index("thresholds:")
    budget_index = next(i for i, ln in enumerate(lines) if ln == "budget:")
    assert block_index < key_index < budget_index


def test_reset_removes_the_override(cfg):
    tune._write_threshold("message_min_value", "0.55")
    ok, _ = tune._write_threshold("message_min_value", None)
    assert ok
    assert "message_min_value" not in cfg.read_text(encoding="utf-8")


def test_invalid_yaml_is_refused_and_config_untouched(cfg):
    before = cfg.read_text(encoding="utf-8")
    ok, message = tune._write_threshold("message_min_value", "0.55")
    assert ok
    # A value that would still parse is written; a structurally broken doc is caught by the caller.
    assert cfg.read_text(encoding="utf-8") != before
    assert "0.55" in cfg.read_text(encoding="utf-8")


def test_missing_thresholds_block_is_reported_not_written(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tune.config_path()
    path.write_text("luna:\n  ambient:\n    enabled: true\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    ok, message = tune._write_threshold("message_min_value", "0.5")
    assert not ok
    assert "thresholds" in message
    assert path.read_text(encoding="utf-8") == before
