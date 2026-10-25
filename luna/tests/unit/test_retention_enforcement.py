"""Retention *enforcement* (P6 hardening).

``luna/tools/prune_data.py`` has always held the pruning logic and unit tests for it, but nothing
in the gateway ever called it: the retention keys in the config template described an intent that
never executed, and the observe transcript (every unmentioned group message, full text) grew
without bound. These tests pin the callable seam — ``luna_core.retention.enforce`` — and its
wiring into the indexer loop, so the promise in the config template is now enforced.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from luna_core import configedit
from luna_core import retention


def _home(tmp_path, body: str = "luna:\n  data:\n    retention_days: 1\n"):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(body, encoding="utf-8")
    return home


def _seed(path, *, old: str, new: str) -> None:
    from luna_core import db

    conn = db.connect(path)
    db.init_db(conn)
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, timestamp, observed) VALUES (?,?,?,1)",
        ("old", "-100", old),
    )
    conn.execute(
        "INSERT INTO messages(message_id, chat_id, timestamp, observed) VALUES (?,?,?,1)",
        ("new", "-100", new),
    )
    conn.commit()
    conn.close()


def _count(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    finally:
        conn.close()


def _stamped(days_ago: int) -> str:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return when.isoformat()


# ── enforce() ───────────────────────────────────────────────────────────────────────────────────


def test_enforce_prunes_aged_rows_from_the_luna_index(tmp_path):
    home = _home(tmp_path)
    _seed(home / "luna-state.db", old=_stamped(9), new=_stamped(0))

    summary = retention.enforce(home)

    assert summary["luna"]["messages"] == 1
    assert summary["luna"]["failed"] == 0
    assert _count(home / "luna-state.db") == 1


def test_enforce_respects_auto_prune_off(tmp_path):
    home = _home(tmp_path, "luna:\n  data:\n    retention_days: 1\n    auto_prune: false\n")
    _seed(home / "luna-state.db", old=_stamped(9), new=_stamped(0))

    summary = retention.enforce(home)

    assert summary == {"skipped": "auto_prune disabled"}
    assert _count(home / "luna-state.db") == 2


def test_enforce_treats_zero_retention_as_keep_everything(tmp_path):
    """retention_days: 0 is the documented 'keep everything' escape hatch, not 'delete everything'."""
    home = _home(tmp_path, "luna:\n  data:\n    retention_days: 0\n")
    _seed(home / "luna-state.db", old=_stamped(400), new=_stamped(0))

    summary = retention.enforce(home)

    assert summary["skipped"] == "retention_days <= 0"
    assert _count(home / "luna-state.db") == 2


def test_enforce_is_a_noop_on_a_fresh_home(tmp_path):
    home = _home(tmp_path)
    assert "luna" in retention.enforce(home)


def test_enforce_never_raises_on_a_corrupt_database(tmp_path):
    """Retention is housekeeping: it must never take the gateway down or block indexing."""
    home = _home(tmp_path)
    (home / "luna-state.db").write_bytes(b"this is not a sqlite database")

    summary = retention.enforce(home)  # must not raise

    assert summary["luna"]["failed"] == 1


def test_enforce_skips_gateway_prune_without_an_indexer_watermark(tmp_path):
    """Without the watermark, gateway rows may still be un-indexed raw log — deleting them first
    is how an indexer outage longer than the window loses room history permanently."""
    home = _home(tmp_path, "luna:\n  data:\n    retention_days: 1\n    prune_gateway_state: true\n")
    _seed(home / "luna-state.db", old=_stamped(9), new=_stamped(0))

    summary = retention.enforce(home)

    assert summary["gateway"]["skipped"] == "no indexer watermark"


def test_enforce_reads_the_window_from_the_config_template_default(tmp_path):
    """The shipped default is 1 day; a config that omits the key must land on that, not 'forever'."""
    home = _home(tmp_path, "luna: {}\n")
    _seed(home / "luna-state.db", old=_stamped(3), new=_stamped(0))

    summary = retention.enforce(home)

    assert summary["retention_days"] == retention.DEFAULT_RETENTION_DAYS
    assert summary["luna"]["messages"] == 1


def test_configedit_round_trips_the_retention_keys(tmp_path):
    """The new auto_prune keys are only real if the dashboard's comment-preserving writer
    accepts them (AGENTS.md §6: a key that exists only in raw YAML is not done)."""
    home = tmp_path / "home"
    home.mkdir()
    text = "luna:\n  data:\n    # keep me\n    retention_days: 1\n"

    text = configedit.write_config_value(text, ["luna", "data", "auto_prune"], False)
    text = configedit.write_config_value(
        text, ["luna", "data", "auto_prune_interval_minutes"], 30
    )

    assert "auto_prune: false" in text
    assert "auto_prune_interval_minutes: 30" in text
    assert "# keep me" in text


# ── indexer-loop wiring ─────────────────────────────────────────────────────────────────────────


def _plugin():
    import importlib.util
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root / "luna" / "lib"))
    spec = importlib.util.spec_from_file_location(
        "luna_logger_plugin_retention", repo_root / "luna" / "plugins" / "luna-logger" / "__init__.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _drive_loop(plugin, monkeypatch, *, interval: int, observe_for: float = 0.2):
    """Run ``_loop`` on a daemon thread for ``observe_for`` seconds; return the call count."""
    import threading

    calls: list[int] = []
    stop = threading.Event()
    monkeypatch.setattr(plugin, "index_once", lambda: 0)
    monkeypatch.setattr(plugin, "_enforce_retention", lambda: calls.append(1))
    monkeypatch.setattr(plugin, "_retention_interval_seconds", lambda: interval)
    monkeypatch.setattr(plugin, "_STOP", stop)
    thread = threading.Thread(target=plugin._loop, args=(0.001,), daemon=True)
    thread.start()
    stop.wait(observe_for)
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive(), "indexer loop ignored the stop flag"
    return calls


def test_indexer_loop_enforces_retention_on_its_cadence(monkeypatch):
    """The loop must prune on its own initiative — that is what makes the promise true."""
    plugin = _plugin()
    assert _drive_loop(plugin, monkeypatch, interval=0)


def test_retention_runs_on_the_first_pass_not_one_interval_late(monkeypatch):
    """A gateway restarted more often than the interval must still prune.

    Seeding the loop clock at "now" deferred the first pass by a full interval, so short-lived
    processes accumulated without bound and never pruned once.
    """
    plugin = _plugin()
    calls = _drive_loop(plugin, monkeypatch, interval=3600, observe_for=0.2)
    assert calls, "first retention pass never ran; a short-lived process would never prune"


def test_retention_does_not_run_on_every_iteration(monkeypatch):
    """One pass per interval, not per poll — otherwise pruning competes with indexing."""
    plugin = _plugin()
    calls = _drive_loop(plugin, monkeypatch, interval=3600, observe_for=0.2)
    # The loop polls every 1ms, so 0.2s is ~200 iterations. Only the initial pass may fire.
    assert len(calls) == 1, f"retention ran {len(calls)} times inside one 1h interval"


def test_retention_pass_swallows_failures(monkeypatch):
    plugin = _plugin()

    def boom(*_a, **_k):
        raise RuntimeError("prune exploded")

    monkeypatch.setattr(plugin.retention, "enforce", boom)

    plugin._enforce_retention()  # must not raise


@pytest.mark.parametrize(
    ("env", "expected"),
    [("60", 3600), ("1", 60), ("0", 60), ("garbage", 3600)],
)
def test_retention_interval_reads_the_environment(monkeypatch, env, expected):
    plugin = _plugin()
    monkeypatch.setenv("LUNA_DATA_AUTO_PRUNE_INTERVAL_MINUTES", env)
    assert plugin._retention_interval_seconds() == expected


def test_retention_interval_falls_back_to_the_config_key(monkeypatch, tmp_path):
    """The dashboard exposes luna.data.auto_prune_interval_minutes, so env-only would gate nothing."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "luna:\n  data:\n    auto_prune_interval_minutes: 5\n", encoding="utf-8"
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("LUNA_DATA_AUTO_PRUNE_INTERVAL_MINUTES", raising=False)
    assert retention.auto_prune_interval_seconds(60) == 300


def test_retention_env_beats_the_config_key(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "luna:\n  data:\n    auto_prune_interval_minutes: 5\n", encoding="utf-8"
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("LUNA_DATA_AUTO_PRUNE_INTERVAL_MINUTES", "90")
    assert retention.auto_prune_interval_seconds(60) == 5400


def test_enforce_honours_the_index_db_env_override(tmp_path, monkeypatch):
    """Every other Luna surface honours LUNA_INDEX_DB; hardcoding the path made retention prune a
    database nothing reads while the real transcript grew forever."""
    home = _home(tmp_path)
    _seed(home / "luna-state.db", old=_stamped(9), new=_stamped(0))
    alt = tmp_path / "alt"
    alt.mkdir()
    monkeypatch.setenv("LUNA_INDEX_DB", str(alt / "luna-state.db"))
    _seed(alt / "luna-state.db", old=_stamped(9), new=_stamped(0))

    summary = retention.enforce(home)

    assert summary["luna"]["messages"] == 1
    assert _count(alt / "luna-state.db") == 1, "the overridden index db was not pruned"
    assert _count(home / "luna-state.db") == 2, "pruned a database the indexer never uses"


def test_enforce_skips_when_the_config_cannot_be_read(tmp_path):
    """An unreadable config must not resolve to the 1-day default and delete a month of history."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("luna: [this is not: valid: yaml\n  - broken", encoding="utf-8")
    _seed(home / "luna-state.db", old=_stamped(300), new=_stamped(0))

    summary = retention.enforce(home)

    assert summary["skipped"] == "config unreadable"
    assert _count(home / "luna-state.db") == 2, "deleted history on a config read failure"


def test_failed_prune_reports_no_deleted_rows(tmp_path, monkeypatch):
    """All deletes share one transaction, so a failure rolls them back — the counts must not claim
    rows were pruned when they are still on disk."""
    home = _home(tmp_path)
    _seed(home / "luna-state.db", old=_stamped(9), new=_stamped(0))

    real_connect = retention.sqlite3.connect

    class _FailsOnSixthStatement:
        """Passes the PRAGMA, BEGIN, existence check and the messages DELETE, then fails."""

        def __init__(self, conn):
            self._conn = conn
            self._calls = 0

        def execute(self, sql, *args, **kwargs):
            self._calls += 1
            if self._calls == 6:
                raise retention.sqlite3.OperationalError("database is locked")
            return self._conn.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    monkeypatch.setattr(retention.sqlite3, "connect", lambda *a, **k: _FailsOnSixthStatement(real_connect(*a, **k)))

    summary = retention.enforce(home)

    assert summary["luna"]["failed"] == 1
    assert summary["luna"]["messages"] == 0, "claimed a delete that the rollback undid"


# ── The standalone runner also enforces ───────────────────────────────────────────────────────────
#
# PRODUCT_PLAN and the threat model both claim the out-of-process runner prunes. An operator who
# runs the systemd unit instead of the plugin thread must not silently lose retention.


def test_standalone_runner_enforces_retention_on_a_cadence():
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "luna" / "plugins" / "luna-logger" / "run.py"
    source = path.read_text(encoding="utf-8")
    # Source-level: run.py has no test seam (it is an infinite loop), so pin the wiring itself.
    assert "_enforce_retention()" in source, "run.py never enforces retention"
    assert "_retention_interval_seconds()" in source, "run.py does not read the configured cadence"
    assert "time.monotonic() - interval" in source, (
        "run.py defers its first pass by a full interval, so a short-lived runner never prunes"
    )
