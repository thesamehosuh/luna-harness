# SPDX-License-Identifier: Apache-2.0
# Attribution and inherited MIT notices: OPENCODE_NOTICES.txt
"""Pinned, verified OpenCode installation; no npm, shell installer, or user credentials.

The native-runtime lifecycle and release-target policy follow Xratu's OpenCode
integration (Apache-2.0). See luna/docs/opencode-engine.md for provenance.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
from pathlib import Path

RELEASES = json.loads(Path(__file__).with_name("opencode-releases.json").read_text())
VERSION = RELEASES["version"]
_INSTALL_LOCK = threading.Lock()


def runtime_root() -> Path:
    from hermes_cli.config import get_hermes_home
    return Path(get_hermes_home()) / "opencode"


def isolated_environment(root: Path) -> dict[str, str]:
    """Only networking/OS plumbing crosses the boundary, never Luna's .env.

    OpenCode owns a separate HOME and XDG tree: it cannot load the operator's
    OpenCode credentials, plugins, project MCP servers, or paid subscriptions.
    """
    keep = {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC",
            "PATHEXT", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
            "https_proxy", "all_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS"}
    env = {key: value for key, value in os.environ.items() if key in keep}
    home = root / "home"
    for path in (home, root / "config", root / "data", root / "cache", root / "state"):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(root / "config"),
               XDG_DATA_HOME=str(root / "data"), XDG_CACHE_HOME=str(root / "cache"),
               XDG_STATE_HOME=str(root / "state"), NO_PROXY="127.0.0.1,localhost,::1",
               no_proxy="127.0.0.1,localhost,::1", OPENCODE_DISABLE_AUTOUPDATE="1")
    return env


def check_binary(binary: Path, root: Path) -> str:
    try:
        result = subprocess.run([str(binary), "--version"], env=isolated_environment(root),
                                cwd=root, capture_output=True, text=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("The OpenCode executable could not run on this system. Reinstall it from Setup.") from exc
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)\b", result.stdout + result.stderr)
    if not match or not ((2, 0, 30) <= tuple(map(int, match.groups())) < (2, 2, 0)):
        raise RuntimeError(f"OpenCode {VERSION} is required; install it from Luna setup.")
    return match.group(0)


def find_binary(root: Path | None = None) -> tuple[Path, str] | None:
    root = root or runtime_root()
    executable = "opencode.exe" if os.name == "nt" else "opencode"
    candidates = [root / "bin" / VERSION / executable]
    if binary := shutil.which("opencode"):
        candidates.append(Path(binary))
    candidates.append(Path.home() / ".opencode" / "bin" / executable)
    for candidate in dict.fromkeys(candidates):
        if candidate.is_file():
            try:
                return candidate.resolve(), check_binary(candidate, root)
            except (OSError, subprocess.SubprocessError, RuntimeError):
                continue
    return None


def release_target() -> str:
    os_name = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(platform.system())
    arch = {"x86_64": "x64", "AMD64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    libc = platform.libc_ver()[0]
    musl = os_name == "linux" and (libc == "musl" or
            (not libc and any(Path("/lib").glob("ld-musl-*.so.1"))))
    target = f"{os_name}-{arch}" + ("-baseline" if arch == "x64" else "") + ("-musl" if musl else "")
    if target not in RELEASES["targets"]:
        raise RuntimeError("OpenCode has no supported download for this operating system and CPU.")
    return target


def install(root: Path | None = None) -> tuple[Path, str]:
    root = root or runtime_root()
    with _INSTALL_LOCK:
        if existing := find_binary(root):
            return existing
        release = RELEASES["targets"][release_target()]
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=root) as staging:
            archive = Path(staging) / "release.tgz"
            digest = hashlib.sha512()
            size = 0
            with urllib.request.urlopen(release["tarball"], timeout=60) as response, archive.open("xb") as output:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 500 * 1024 * 1024:
                        raise RuntimeError("OpenCode download exceeds the size limit.")
                    digest.update(chunk)
                    output.write(chunk)
            expected = base64.b64decode(release["integrity"].removeprefix("sha512-"), validate=True)
            if digest.digest() != expected:
                raise RuntimeError("OpenCode release integrity check failed.")
            executable = "opencode.exe" if os.name == "nt" else "opencode"
            # Extract exactly one regular member. Never extract paths, links or archive metadata.
            candidate = Path(staging) / executable
            with tarfile.open(archive, "r:gz") as bundle:
                member = bundle.getmember(f"package/bin/{executable}")
                if not member.isfile() or member.size > 500 * 1024 * 1024:
                    raise RuntimeError("OpenCode archive has no regular executable.")
                with bundle.extractfile(member) as source, candidate.open("xb") as output:
                    shutil.copyfileobj(source, output)
            candidate.chmod(0o755)
            if check_binary(candidate, root) != VERSION:
                raise RuntimeError("OpenCode download returned an unexpected version.")
            destination = root / "bin" / VERSION / executable
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Never rewrite a binary another worker may currently be executing.
            try:
                os.link(candidate, destination)
            except FileExistsError:
                if check_binary(destination, root) != VERSION:
                    raise RuntimeError("The managed OpenCode executable has an unexpected version.")
            return destination, VERSION
