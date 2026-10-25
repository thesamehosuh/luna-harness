"""Release and migration behavior with scratch files, including live WAL snapshots."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import sqlite3
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"luna/deploy/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def source(tmp_path):
    src = tmp_path / "source"
    for name, text in {
        "pyproject.toml": "[project]\nname='test'\nversion='0.1'\n",
        "README.md": "Luna", "NOTICE": "attribution", "LICENSE": "MIT",
        "AGENTS.md": "developer instructions", "SOUL.md": "engine default",
        "hermes_cli/web_dist/index.html": "<html>Luna</html>",
        "acp_adapter/edit_approval.py": "# approval guard",
        "luna/lib/luna_core/__init__.py": "# companion library",
        "luna/plugins/luna-room/__init__.py": "# plugin",
        "luna/config/config.yaml.luna": "# defaults",
        "luna/soul/SOUL.md": "example persona",
        "luna/honcho/.env.template": "KEY=REPLACE_ME",
        "luna/honcho/.env": "SECRET=private",
        ".kilo/private.txt": "local metadata", ".env": "SECRET=private",
        "luna/tests/unit/private.py": "dev test", "web/node_modules/a.js": "dev",
        "plugins/example/tests/test_plugin.py": "dev test",
        "agent/__pycache__/cached.pyc": "bytecode", "state.db": "live state",
        "ignored/validation/candidate.tar.gz": "a previous release archive",
        "ignored/validation/evidence.json": "private test evidence",
        "tmp/rehearsal.json": "temporary runtime data",
        "logs/events.json": "local events", "data/messages.json": "local messages",
        "test-results/snapshot.json": "test output",
        "playwright-report/index.html": "browser report",
    }.items():
        path = src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return src


def test_assembled_runtime_has_assets_and_no_source_or_private_dependencies(source, tmp_path):
    target = tmp_path / "runtime"
    module("assemble").assemble(source, target)
    for name in ("NOTICE", "LICENSE", "README.md", "hermes_cli/web_dist/index.html",
                 "acp_adapter/edit_approval.py", "luna/lib/luna_core/__init__.py",
                 "luna/plugins/luna-room/__init__.py", "luna/soul/SOUL.md", "luna/honcho/.env.template"):
        assert (target / name).is_file(), name
    for name in (".env", ".kilo", "AGENTS.md", "SOUL.md", "state.db", "web", "luna/tests",
                 "agent/__pycache__", "luna/honcho/.env", "ignored", "tmp", "logs", "data",
                 "test-results", "playwright-report"):
        assert not (target / name).exists(), name
    assert not (target / "plugins/example/tests").exists()


def test_assembly_dry_run_and_overlapping_paths(source, tmp_path):
    assemble = module("assemble").assemble
    target = tmp_path / "not-created"
    assert assemble(source, target, dry_run=True)
    assert not target.exists()
    for invalid in (source, source / "child", source.parent):
        with pytest.raises(ValueError, match="separate directories"):
            assemble(source, invalid)


def test_assembly_refuses_source_external_links_and_destination_write_through(source, tmp_path):
    assemble = module("assemble").assemble
    external = tmp_path / "external"
    external.write_text("private")
    (source / "leak").symlink_to(external)
    with pytest.raises(ValueError, match="source-external"):
        assemble(source, tmp_path / "target")
    (source / "leak").unlink()
    target = tmp_path / "another-target"
    target.mkdir()
    (target / "README.md").symlink_to(external)
    with pytest.raises(ValueError, match="destination symlink"):
        assemble(source, target)
    assert external.read_text() == "private"
    target = tmp_path / "overlay-target"
    target.mkdir()
    old_overlay = tmp_path / "old-overlay"
    old_overlay.mkdir()
    (target / "luna").symlink_to(old_overlay)
    with pytest.raises(ValueError, match="destination symlink"):
        assemble(source, target)
    assert not list(old_overlay.iterdir())


def test_migration_preserves_settings_identity_and_committed_wal(tmp_path):
    src, dst = tmp_path / "old", tmp_path / "trial"
    src.mkdir()
    (src / ".env").write_text("KEY=synthetic")
    (src / "SOUL.md").write_text("custom character")
    (src / "config.yaml").write_text("luna: {}\n")
    (src / "honcho.json").write_text('{"workspace":"existing"}')
    connections = []
    for name, table in (("state.db", "messages"), ("luna-state.db", "identity")):
        conn = sqlite3.connect(src / name)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"CREATE TABLE {table}(value TEXT)")
        conn.execute(f"INSERT INTO {table} VALUES ('synthetic')")
        conn.commit()
        connections.append(conn)
    try:
        report = module("migrate").snapshot(src, dst)
        assert report["databases"]["luna-state.db"]["identity"] == 1
        assert report["databases"]["state.db"]["messages"] == 1
        for name in (".env", "SOUL.md", "config.yaml", "honcho.json"):
            assert (dst / name).read_bytes() == (src / name).read_bytes()
        (dst / "SOUL.md").write_text("trial persona")
        assert (src / "SOUL.md").read_text() == "custom character"
        assert (dst / ".env").stat().st_mode & 0o777 == 0o600
        assert (dst.stat().st_mode & 0o777) == 0o700
    finally:
        for conn in connections:
            conn.close()


def test_migration_rejects_nonempty_or_overlapping_destination_and_dry_run(source, tmp_path):
    migrate = module("migrate").snapshot
    dst = tmp_path / "trial"
    migrate(source, dst, dry_run=True)
    assert not dst.exists()
    for invalid in (source, source / "trial", source.parent):
        with pytest.raises(ValueError, match="non-overlapping"):
            migrate(source, invalid)
    dst.mkdir()
    (dst / "important").write_text("keep me")
    with pytest.raises(ValueError, match="empty"):
        migrate(source, dst)
    assert (dst / "important").read_text() == "keep me"


def test_reinstall_preserves_persona_settings_and_uses_internal_plugins(tmp_path):
    runtime = tmp_path / "runtime with spaces"
    user = tmp_path / "user"
    user.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith(("LUNA_", "HERMES_"))}
    env.update(HOME=str(user), SKIP_VENV="1", BUILD_DASHBOARD="0", SKIP_SYSTEMD="1")
    # Actual packaged assets are exercised by the release smoke check; this test verifies
    # installer state preservation and path handling without a frontend build prerequisite.
    packaged = tmp_path / "release"
    module("assemble").assemble(ROOT, packaged)
    web = packaged / "hermes_cli/web_dist/index.html"
    web.parent.mkdir(parents=True, exist_ok=True)
    web.write_text("<html>Luna</html>")
    command = ["bash", str(packaged / "install.sh"), str(runtime)]
    subprocess.run(command, env=env, cwd=tmp_path, check=True, capture_output=True)
    for name in ("SOUL.md", "config.yaml", "honcho.json", "skins/luna.yaml"):
        (runtime / name).write_text("user-owned " + name)
    subprocess.run(command, env=env, cwd=tmp_path, check=True, capture_output=True)
    for name in ("SOUL.md", "config.yaml", "honcho.json", "skins/luna.yaml"):
        assert (runtime / name).read_text() == "user-owned " + name
    assert (runtime / "plugins/luna-room").resolve() == (runtime / "luna/plugins/luna-room").resolve()
    assert (user / ".local/bin/luna").resolve() == runtime / "bin/luna"
    assert (runtime / "skills/creative/humanizer/SKILL.md").is_file()
    assert (runtime / "skills/luna/local-jev/SKILL.md").is_file()
    assert not (user / ".config/systemd").exists()


def test_rollback_targets_only_recorded_units(tmp_path, monkeypatch):
    rollback = module("rollback")
    units = ["hermes-gateway-trial.service", "luna-data-retention-trial.timer"]
    (tmp_path / ".luna-units.json").write_text(json.dumps(units))
    calls = []
    monkeypatch.setattr(rollback.subprocess, "run", lambda command, **kwargs: calls.append(command))
    rollback.rollback(tmp_path)
    assert calls == [["systemctl", "--user", "disable", "--now", unit] for unit in units]
    assert (tmp_path / ".luna-units.json").exists()


def test_luna_update_cannot_replace_product_with_engine(tmp_path):
    from hermes_cli.update_contract import evaluate_update_admission
    marker = tmp_path / "luna/config/config.yaml.luna"
    marker.parent.mkdir(parents=True)
    marker.write_text("luna: {}\n")
    refusal = evaluate_update_admission(tmp_path)
    assert refusal.code == "luna-release"
    assert "Luna release bundles" in refusal.message


def test_failed_dependency_install_preserves_current_release_and_state(tmp_path):
    runtime, user = tmp_path / 'runtime', tmp_path / 'user'
    user.mkdir()
    packaged = tmp_path / 'release'
    module('assemble').assemble(ROOT, packaged)
    assets = packaged / 'hermes_cli/web_dist/index.html'
    assets.parent.mkdir(parents=True, exist_ok=True);assets.write_text('<html>Luna</html>')
    env = {key: value for key, value in os.environ.items() if not key.startswith(('LUNA_', 'HERMES_'))}
    env.update(HOME=str(user), SKIP_VENV='1', BUILD_DASHBOARD='0', SKIP_SYSTEMD='1', PYTHON=sys.executable)
    command = ['bash', str(packaged / 'install.sh'), str(runtime)]
    subprocess.run(command, env=env, check=True, capture_output=True)
    before = (runtime / 'current').resolve()
    (runtime / 'SOUL.md').write_text('# Keep this persona\n')
    fakebin = tmp_path / 'fakebin';fakebin.mkdir()
    uv = fakebin / 'uv';uv.write_text('#!/bin/sh\nexit 17\n');uv.chmod(0o755)
    env.update(SKIP_VENV='0', PATH=str(fakebin) + os.pathsep + env['PATH'])
    failed = subprocess.run(command, env=env, capture_output=True)
    assert failed.returncode == 17
    assert (runtime / 'current').resolve() == before
    assert (runtime / 'SOUL.md').read_text() == '# Keep this persona\n'


def test_assembly_preflight_failure_and_removed_code(source, tmp_path):
    target = tmp_path / 'runtime'
    assemble = module('assemble').assemble
    old = source / 'removed.py';old.write_text('old code')
    assemble(source, target)
    old.unlink()
    assemble(source, target)
    assert not (target / 'removed.py').exists()
    before = (target / 'README.md').read_bytes()
    (source / 'README.md').write_text('changed code')
    (source / 'zz-invalid').symlink_to('/etc/passwd')
    with pytest.raises(ValueError, match='source-external'):
        assemble(source, target)
    assert (target / 'README.md').read_bytes() == before


def test_version_rollback_restores_code_and_keeps_state(source, tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / 'luna/deploy'))
    try:
        releases = module('releases')
        runtime = tmp_path / 'runtime'
        first = releases.stage(source, runtime);(first / '.ready').touch()
        releases.publish(runtime, first)
        (runtime / 'SOUL.md').write_text('# User state\n')
        (source / 'README.md').write_text('second release')
        second = releases.stage(source, runtime);(second / '.ready').touch()
        releases.publish(runtime, second)
        assert (runtime / 'README.md').read_text() == 'second release'
        releases.rollback(runtime)
        assert (runtime / 'README.md').read_text() == 'Luna'
        assert (runtime / 'SOUL.md').read_text() == '# User state\n'
    finally:
        sys.path.remove(str(ROOT / 'luna/deploy'))


def test_installed_entry_point_uses_state_home_outside_release(tmp_path, monkeypatch):
    from luna_cli.main import luna_home
    release = tmp_path / 'releases/version'
    release.mkdir(parents=True)
    (release / '.luna-state-home').write_text(str(tmp_path))
    monkeypatch.setattr(sys, 'prefix', str(release / 'venv'))
    monkeypatch.delenv('LUNA_HOME', raising=False);monkeypatch.delenv('HERMES_HOME', raising=False)
    assert luna_home() == str(tmp_path)
