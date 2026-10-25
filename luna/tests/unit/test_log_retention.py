from __future__ import annotations

import os
from pathlib import Path

from luna.tools import prune_logs


def test_prune_truncates_active_log_and_removes_old_rotations(tmp_path):
    home = tmp_path / "home"
    logs = home / "logs"
    logs.mkdir(parents=True)
    active = logs / "agent.log"
    old = logs / "agent.log.1"
    recent = logs / "agent.log.2"
    active.write_text("telemetry", encoding="utf-8")
    old.write_text("old", encoding="utf-8")
    recent.write_text("recent", encoding="utf-8")
    os.utime(old, (0, 0))
    os.utime(recent, (2_000_000, 2_000_000))

    result = prune_logs.prune_logs(home, retention_days=1, files=("agent.log",), now=2_000_001)

    assert result == {"truncated": 1, "removed": 1, "failed": 0}
    assert active.read_text(encoding="utf-8") == ""
    assert not old.exists()
    assert recent.exists()


def test_prune_is_disabled_for_zero_days(tmp_path):
    home = tmp_path / "home"
    logs = home / "logs"
    logs.mkdir(parents=True)
    active = logs / "agent.log"
    active.write_text("telemetry", encoding="utf-8")

    result = prune_logs.prune_logs(home, retention_days=0, files=("agent.log",))

    assert result == {"truncated": 0, "removed": 0, "failed": 0}
    assert active.read_text(encoding="utf-8") == "telemetry"
