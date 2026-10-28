"""Luna's dashboard updater: published bundles, verified staging, explicit reopen.

The engine's git/ZIP updater stays blocked. Personal data and gateway lifecycle
remain owned by the existing release installer.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid

from packaging.version import InvalidVersion, Version

REPOSITORY = "thesamehosuh/luna-harness"
RELEASES_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
DOWNLOAD_BASE = f"https://github.com/{REPOSITORY}/releases/download/"
MAX_ARCHIVE = 500_000_000
MAX_UNPACKED = 2_000_000_000


def installation():
    from hermes_cli.product_runtime import installation_home
    from luna_core.runtime import home
    return installation_home(home()).resolve()


def running_version():
    return json.loads((Path(__file__).resolve().parents[3] / "luna-release.json").read_text())["version"]


def installed_version(root):
    marker = root / "current-release.json"
    if marker.is_file():
        return json.loads(marker.read_text())["version"]
    manifest = root / "current/luna-release.json"
    return json.loads(manifest.read_text())["version"] if manifest.is_file() else running_version()


def _request(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "Luna-Release-Updater", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        if not response.geturl().startswith("https://"):
            raise ValueError("Release downloads require HTTPS")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release metadata exceeds its size limit")
    return json.loads(data)


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", value):
        raise ValueError("Invalid Luna release version")
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise ValueError("Invalid Luna release version") from exc


def discover(current):
    """Use the release list: GitHub's /latest excludes Luna's alpha releases."""
    releases = _request(RELEASES_URL, 2_000_000)
    if not isinstance(releases, list):
        raise ValueError("Invalid response from Luna's release service")
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name", "")
        try:
            version = _version(tag.removeprefix("v"))
        except (ValueError, AttributeError):
            continue
        if (release.get("prerelease") or version.is_prerelease) and not _version(current).is_prerelease:
            continue
        expected = DOWNLOAD_BASE + tag + "/luna-launcher-release.json"
        if tag != "v" + tag.removeprefix("v") or not any(
            isinstance(asset, dict) and asset.get("name") == "luna-launcher-release.json"
            and asset.get("browser_download_url") == expected for asset in release.get("assets", [])
        ):
            continue
        candidates.append((version, tag.removeprefix("v"), expected))
    if not candidates:
        raise ValueError("No compatible published Luna release was found")
    _, version, url = max(candidates)
    descriptor = _request(url, 65536)
    expected_archive = DOWNLOAD_BASE + "v" + version + f"/luna-{version}.tar.gz"
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get("runtime"), dict):
        raise ValueError("The published Luna release descriptor is invalid")
    runtime = descriptor["runtime"]
    checksum = runtime.get("sha256", "")
    if descriptor.get("version") != version or runtime.get("url") != expected_archive or not isinstance(checksum, str) or not re.fullmatch("[a-fA-F0-9]{64}", checksum):
        raise ValueError("The published Luna release descriptor is invalid")
    return descriptor


def _uv(root):
    bundled = root / "runtime/uv" / ("uv.exe" if os.name == "nt" else "uv")
    return str(bundled) if bundled.is_file() else shutil.which("uv")


def can_install(root):
    return bool(_uv(root)) and ((root / "current-release.json").is_file() or (os.name != "nt" and (root / "current").is_symlink()))


def check(force=False):
    root = installation()
    current = running_version()
    installed = installed_version(root)
    restart = _version(installed) > _version(current)
    result = {"install_method": "luna-release", "current_version": current, "installed_version": installed,
              "behind": None, "update_available": False, "can_apply": can_install(root),
              "update_command": "Luna release update", "message": None, "restart_required": restart}
    cache = root / "cache/luna-release-check.json"
    try:
        cached = json.loads(cache.read_text()) if not force and cache.is_file() else {}
        if cached.get("checked_at", 0) + 900 > time.time():
            descriptor = cached["release"]
        else:
            descriptor = discover(current)
            from luna_core.settings import _replace
            cache.parent.mkdir(parents=True, exist_ok=True)
            _replace(cache, json.dumps({"checked_at": time.time(), "release": descriptor}))
        latest = descriptor["version"]
        result.update(latest_version=latest, release_url=DOWNLOAD_BASE.replace("/download/", "/tag/") + "v" + latest,
                      update_available=_version(latest) > _version(installed), behind=0)
        if result["update_available"]:
            result["behind"] = -1
            result["message"] = f"Luna {latest} is available. Stop your companion in Control Center before installing."
        elif restart:
            result["message"] = f"Luna {installed} is installed. Quit and reopen Luna to use it."
        else:
            result["message"] = "You're on the latest published Luna version."
        if not result["can_apply"]:
            result["message"] = "This source checkout is not a managed Luna installation. Install the current Luna desktop app to receive dashboard updates."
    except Exception:
        result["message"] = f"Luna {installed} is installed. Quit and reopen Luna to use it." if restart else "Could not reach Luna's release service. Try Check for updates again."
    return result


def download(descriptor, target):
    digest = hashlib.sha256()
    request = urllib.request.Request(descriptor["runtime"]["url"], headers={"User-Agent": "Luna-Release-Updater"})
    total = 0
    deadline = time.monotonic() + 900
    with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as output:
        if not response.geturl().startswith("https://"):
            raise ValueError("Release downloads require HTTPS")
        while chunk := response.read(262144):
            total += len(chunk)
            if total > MAX_ARCHIVE or time.monotonic() > deadline:
                raise ValueError("The runtime download exceeded its size or time limit")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != descriptor["runtime"]["sha256"].lower():
        raise ValueError("The runtime checksum did not match; the installed version was retained")


def unpack(archive, target, version):
    total = 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "luna-" + version or "\\" in member.name:
                raise ValueError("Unsafe Luna archive path")
            if member.isdir():
                continue
            if not member.isfile() or len(path.parts) < 2:
                raise ValueError("Luna archives must contain regular files")
            total += member.size
            if total > MAX_UNPACKED:
                raise ValueError("The unpacked release exceeds its size limit")
            destination = target.joinpath(*path.parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, destination.open("xb") as output:
                shutil.copyfileobj(incoming, output)
            destination.chmod(member.mode & 0o755)
    manifest = json.loads((target / "luna-release.json").read_text())
    if manifest.get("product") != "Luna" or manifest.get("version") != version:
        raise ValueError("The runtime identity did not match the release")


def require_stopped(root):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from luna_core.data_ops import require_stopped as check_stopped
    token = set_hermes_home_override(root)
    try:
        check_stopped()
    except ValueError as exc:
        raise ValueError("Stop all affected companions in Control Center and wait for active chats to finish before updating Luna.") from exc
    finally:
        reset_hermes_home_override(token)


def install(descriptor, root):
    if not can_install(root):
        raise ValueError("This is not a managed Luna installation")
    require_stopped(root)
    from hermes_cli._file_lock import acquire
    with (root / ".luna-update.lock").open("a+") as lock:
        acquire(lock, blocking=False)
        if _version(descriptor["version"]) <= _version(installed_version(root)):
            return installed_version(root)
        print(f"Downloading Luna {descriptor['version']}…", flush=True)
        cache = root / "cache"
        cache.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="luna-update-", dir=cache) as temporary:
            archive = Path(temporary) / "runtime.tar.gz"
            download(descriptor, archive)
            target = root / "releases" / uuid.uuid4().hex
            target.mkdir(parents=True)
            unpack(archive, target, descriptor["version"])
        require_stopped(root)
        env = dict(os.environ, HERMES_HOME=str(root), LUNA_HOME=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env["PATH"] = str(Path(_uv(root)).parent) + os.pathsep + env.get("PATH", "")
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            env.pop(key, None)
        if (root / "current-release.json").is_file():
            command = [sys.executable, str(target / "luna/deploy/desktop_install.py"), "--home", str(root), "--uv", _uv(root)]
        else:
            command = ["bash", str(target / "install.sh"), str(root)]
            env.update(BUILD_DASHBOARD="0", SKIP_SYSTEMD="1")
        print("Installing and verifying the new runtime. Your current runtime remains available for rollback.", flush=True)
        subprocess.run(command, cwd=target, env=env, check=True, timeout=1800,
                       creationflags=0x08000000 if os.name == "nt" else 0)
        if installed_version(root) != descriptor["version"]:
            raise ValueError("The installer did not select the expected runtime")
        print(f"Luna {descriptor['version']} installed. Quit and reopen Luna to use it. Start your companion from Control Center when ready.", flush=True)
        return descriptor["version"]


def main():
    from hermes_constants import set_hermes_home_override
    from hermes_cli.update_receipt import begin_update_receipt, record_step, record_skip, finalize_update_receipt
    root = installation()
    set_hermes_home_override(root)
    begin_update_receipt()
    try:
        version = install(discover(running_version()), root)
        record_step("Luna runtime verified and selected", True, version)
        record_skip("gateway restart", "Owner starts companions after reopening Luna")
        finalize_update_receipt("success", stop_reason="Quit and reopen Luna to use the installed runtime")
        return 0
    except Exception as exc:
        detail = str(exc) if isinstance(exc, (ValueError, BlockingIOError)) else "Luna could not finish installing. The previous runtime was retained; retry the update."
        print(detail, flush=True)
        record_step("Luna release update", False, detail)
        finalize_update_receipt("failed", stop_reason=detail)
        return 1


if __name__ == "__main__":
    sys.exit(main())
