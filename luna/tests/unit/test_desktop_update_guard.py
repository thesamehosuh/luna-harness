"""Desktop updates must not publish while a companion service is unsafe."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location("desktop_install_test", DEPLOY / "desktop_install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
import update_gateways


def test_desktop_installer_blocks_unsafe_service_before_publication(tmp_path, monkeypatch):
    old = tmp_path / "releases/old"
    release = tmp_path / "releases/new"
    old.mkdir(parents=True)
    release.mkdir()
    (old / ".ready").write_text("verified")
    (release / ".luna-assemble-manifest.json").write_text("{}")
    (release / "hermes_cli/web_dist").mkdir(parents=True)
    (release / "hermes_cli/web_dist/index.html").write_text("ok")
    (release / "luna-release.json").write_text('{"version": "new"}')
    (tmp_path / "honcho").mkdir()
    import releases
    monkeypatch.setattr(releases, "_snapshot_state", lambda home: None)
    marker = tmp_path / "current-release.json"
    marker.write_text(json.dumps({"path": "releases/old", "version": "old"}))
    before = marker.read_bytes()
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(update_gateways, "_check_owner", lambda *a: (_ for _ in ()).throw(RuntimeError("unsafe service")))
    with pytest.raises(RuntimeError, match="unsafe service"):
        installer._install(release, tmp_path, "uv")
    assert marker.read_bytes() == before


def test_launcher_installer_refuses_running_companion_without_pausing(tmp_path, monkeypatch):
    old = tmp_path / "releases/old"
    release = tmp_path / "releases/new"
    old.mkdir(parents=True)
    release.mkdir()
    (old / ".ready").write_text("verified")
    (release / ".luna-assemble-manifest.json").write_text("{}")
    (release / "hermes_cli/web_dist").mkdir(parents=True)
    (release / "hermes_cli/web_dist/index.html").write_text("ok")
    (tmp_path / "honcho").mkdir()
    marker = tmp_path / "current-release.json"
    marker.write_text(json.dumps({"path": "releases/old", "version": "old"}))
    before = marker.read_bytes()
    monkeypatch.setattr(update_gateways, "_check_owner", lambda *a: None)
    monkeypatch.setattr(update_gateways, "paused_gateways", lambda *a: pytest.fail("must not pause companions"))
    def run(command, **kwargs):
        if any("require_stopped" in str(arg) for arg in command):
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(installer.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        installer._install(release, tmp_path, "uv")
    assert marker.read_bytes() == before
    assert not (release / ".ready").exists()


def test_installer_holds_legacy_gateway_lock_while_publishing(tmp_path, monkeypatch):
    release = tmp_path / "releases/new"
    release.mkdir(parents=True)
    (release / ".luna-assemble-manifest.json").write_text("{}")
    (release / "hermes_cli/web_dist").mkdir(parents=True)
    (release / "hermes_cli/web_dist/index.html").write_text("ok")
    (release / "luna-release.json").write_text('{"version":"new"}')
    (tmp_path / "honcho").mkdir()
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(update_gateways, "_check_owner", lambda *a: None)
    publish = installer.atomic_json
    observed = []
    def checked_publish(path, value):
        if path.name == "current-release.json":
            handle = (tmp_path / "gateway.lock").open("a+")
            try:
                with pytest.raises(OSError):
                    update_gateways._runtime_lock(handle)
                observed.append(path)
            finally:
                handle.close()
        publish(path, value)
    monkeypatch.setattr(installer, "atomic_json", checked_publish)
    installer._install(release, tmp_path, "uv")
    assert observed == [tmp_path / "current-release.json"]
    assert json.loads((tmp_path / "current-release.json").read_text())["version"] == "new"
    with (tmp_path / "gateway.lock").open("a+") as handle:
        update_gateways._runtime_lock(handle)
        update_gateways._runtime_lock(handle, True)
