"""Published release selection, hostile downloads, and atomic installation admission."""
import io
import json
from pathlib import Path
import tarfile

import pytest

from luna_cli import release_update as update


def descriptor(version="0.1.0-alpha.10", checksum="a" * 64):
    return {"version": version, "runtime": {"url": update.DOWNLOAD_BASE + f"v{version}/luna-{version}.tar.gz", "sha256": checksum}}


def published(version, *, prerelease=True, draft=False):
    return {"tag_name": "v" + version, "prerelease": prerelease, "draft": draft,
            "assets": [{"name": "luna-launcher-release.json", "browser_download_url": update.DOWNLOAD_BASE + f"v{version}/luna-launcher-release.json"}]}


def test_alpha_discovery_uses_semantic_order_and_skips_drafts(monkeypatch):
    releases = [published("0.1.0-alpha.9"), published("0.1.0-alpha.11", draft=True), published("0.1.0-alpha.10")]
    monkeypatch.setattr(update, "_request", lambda url, limit: releases if url == update.RELEASES_URL else descriptor())
    assert update.discover("0.1.0-alpha.8")["version"] == "0.1.0-alpha.10"


def test_stable_channel_does_not_silently_select_alpha(monkeypatch):
    releases = [published("0.2.0-alpha.1"), published("0.1.1", prerelease=False)]
    monkeypatch.setattr(update, "_request", lambda url, limit: releases if url == update.RELEASES_URL else descriptor("0.1.1"))
    assert update.discover("0.1.0")["version"] == "0.1.1"


@pytest.mark.parametrize("bad", [
    {"version": "0.1.0-alpha.10", "runtime": {"url": "https://other.example/runtime.tar.gz", "sha256": "a" * 64}},
    descriptor("0.1.0-alpha.9"), descriptor(checksum="no-checksum"), [],
])
def test_discovery_rejects_changed_identity_url_or_checksum(monkeypatch, bad):
    monkeypatch.setattr(update, "_request", lambda url, limit: [published("0.1.0-alpha.10")] if url == update.RELEASES_URL else bad)
    with pytest.raises(ValueError):
        update.discover("0.1.0-alpha.8")


@pytest.fixture
def home(tmp_path, monkeypatch):
    (tmp_path / "current-release.json").write_text(json.dumps({"version": "0.1.0-alpha.8"}))
    monkeypatch.setattr(update, "installation", lambda: tmp_path)
    monkeypatch.setattr(update, "running_version", lambda: "0.1.0-alpha.8")
    monkeypatch.setattr(update, "_uv", lambda root: "/fixture/uv")
    return tmp_path


def test_check_cache_force_and_reopen_state(home, monkeypatch):
    calls = []
    monkeypatch.setattr(update, "discover", lambda current: calls.append(current) or descriptor())
    assert update.check()["update_available"] is True
    assert update.check()["latest_version"] == "0.1.0-alpha.10"
    assert len(calls) == 1
    update.check(force=True)
    assert len(calls) == 2
    (home / "current-release.json").write_text(json.dumps({"version": "0.1.0-alpha.10"}))
    result = update.check()
    assert result["restart_required"] is True
    assert result["update_available"] is False
    assert "reopen" in result["message"]


def test_release_outage_does_not_report_latest(home, monkeypatch):
    monkeypatch.setattr(update, "discover", lambda current: (_ for _ in ()).throw(OSError("offline")))
    result = update.check()
    assert result["behind"] is None
    assert "Could not reach" in result["message"]


def archive(tmp_path, entries):
    target = tmp_path / "test.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        for name, kind, content in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(content) if kind == tarfile.REGTYPE else 0
            member.linkname = "outside"
            tar.addfile(member, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
    return target


@pytest.mark.parametrize("name,kind", [
    ("luna-0.1.0-alpha.10/../../escape", tarfile.REGTYPE),
    ("/escape", tarfile.REGTYPE), ("wrong-root/file", tarfile.REGTYPE),
    ("luna-0.1.0-alpha.10/link", tarfile.SYMTYPE),
    ("luna-0.1.0-alpha.10/link", tarfile.LNKTYPE),
    ("luna-0.1.0-alpha.10/..\\escape", tarfile.REGTYPE),
])
def test_unpack_rejects_escape_and_links(tmp_path, name, kind):
    with pytest.raises(ValueError):
        update.unpack(archive(tmp_path, [(name, kind, b"bad")]), tmp_path / "stage", "0.1.0-alpha.10")
    assert not (tmp_path.parent / "escape").exists()


def test_unpack_requires_the_promised_runtime_identity(tmp_path):
    payload = json.dumps({"product": "Other", "version": "0.1.0-alpha.10"}).encode()
    with pytest.raises(ValueError, match="identity"):
        update.unpack(archive(tmp_path, [("luna-0.1.0-alpha.10/luna-release.json", tarfile.REGTYPE, payload)]), tmp_path / "stage", "0.1.0-alpha.10")


def test_checksum_mismatch_prevents_installer_and_preserves_pointer(home, monkeypatch):
    class Response(io.BytesIO):
        def geturl(self): return "https://release-assets.githubusercontent.com/runtime"
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: Response(b"wrong archive"))
    monkeypatch.setattr(update, "require_stopped", lambda root: None)
    monkeypatch.setattr(update.subprocess, "run", lambda *a, **k: pytest.fail("Installer ran before checksum validation"))
    before = (home / "current-release.json").read_bytes()
    with pytest.raises(ValueError, match="checksum"):
        update.install(descriptor(), home)
    assert (home / "current-release.json").read_bytes() == before


def test_running_gateway_prevents_download(home, monkeypatch):
    monkeypatch.setattr(update, "require_stopped", lambda root: (_ for _ in ()).throw(ValueError("Stop the companion")))
    monkeypatch.setattr(update, "download", lambda *a: pytest.fail("Spent bandwidth before gateway admission"))
    with pytest.raises(ValueError, match="Stop"):
        update.install(descriptor(), home)


def test_successful_install_uses_desktop_installer_and_preserves_data(home, monkeypatch):
    (home / "SOUL.md").write_text("My existing character")
    payload = json.dumps({"product": "Luna", "version": "0.1.0-alpha.10"}).encode()
    bundle = archive(home, [("luna-0.1.0-alpha.10/luna-release.json", tarfile.REGTYPE, payload)])
    monkeypatch.setattr(update, "require_stopped", lambda root: None)
    monkeypatch.setattr(update, "download", lambda desc, target: target.write_bytes(bundle.read_bytes()))
    def installer(command, **kwargs):
        assert Path(command[1]).name == "desktop_install.py"
        assert command[2:] == ["--home", str(home), "--uv", "/fixture/uv"]
        assert kwargs["env"]["HERMES_HOME"] == str(home)
        (home / "current-release.json").write_text(json.dumps({"version": "0.1.0-alpha.10", "previous": {"version": "0.1.0-alpha.8"}}))
    monkeypatch.setattr(update.subprocess, "run", installer)
    assert update.install(descriptor(), home) == "0.1.0-alpha.10"
    assert (home / "SOUL.md").read_text() == "My existing character"


def test_installer_failure_does_not_publish_or_overwrite_data(home, monkeypatch):
    import subprocess
    payload = json.dumps({"product": "Luna", "version": "0.1.0-alpha.10"}).encode()
    bundle = archive(home, [("luna-0.1.0-alpha.10/luna-release.json", tarfile.REGTYPE, payload)])
    monkeypatch.setattr(update, "require_stopped", lambda root: None)
    monkeypatch.setattr(update, "download", lambda desc, target: target.write_bytes(bundle.read_bytes()))
    monkeypatch.setattr(update.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "installer")))
    with pytest.raises(subprocess.CalledProcessError):
        update.install(descriptor(), home)
    assert update.installed_version(home) == "0.1.0-alpha.8"


def test_service_command_pinned_to_old_runtime_hands_off_before_engine_import(tmp_path, monkeypatch):
    from luna_cli import main
    from hermes_cli import product_runtime
    old = tmp_path / "releases/old"
    old.mkdir(parents=True)
    (old / ".luna-state-home").write_text(str(tmp_path))
    selected = tmp_path / "releases/new"
    selected.mkdir()
    monkeypatch.setattr(main.sys, "prefix", str(old / "venv"))
    monkeypatch.setattr(main.sys, "argv", ["luna", "gateway", "run"])
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(product_runtime, "code_root", lambda home: selected)
    calls = []
    monkeypatch.setattr(main.os, "execv", lambda executable, args: calls.append((executable, args)))
    main._handoff_selected_runtime()
    assert calls == [(str(selected / "venv/bin/python"), [str(selected / "venv/bin/python"), "-m", "luna_cli.main", "gateway", "run"])]
