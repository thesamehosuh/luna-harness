"""Docker Desktop prerequisites through native installers; existing engines stay owned by their users."""
from pathlib import Path
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from luna_core.runtime import home


def _run(args, *, timeout=30, **kwargs):
    from hermes_cli._subprocess_compat import windows_hide_flags
    return subprocess.run(list(map(str, args)), capture_output=True, text=True,
                          timeout=timeout, creationflags=windows_hide_flags(), **kwargs)


def _binary():
    found = shutil.which("docker")
    if found: return found
    candidates = [Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
                  Path("/opt/docker-desktop/bin/docker"),
                  Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/resources/bin/docker.exe",
                  Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe"]
    return next((str(p) for p in candidates if p.is_file()), None)


def command():
    """Shared by setup, backups and maintenance: never run `docker context use` for normal operations."""
    from luna_core import config_read
    record = home() / "honcho/.docker-runtime.json"
    value = json.loads(record.read_text()) if record.exists() else {}
    binary = _binary() or "docker"
    context = str(config_read.section("luna", "memory_stack", "docker_context", default="") or value.get("context") or "")
    if (home() / "honcho/.embedding-contract.json").exists() and value.get("context") and context != value["context"]:
        raise ValueError("This memory database belongs to another Docker context. Migrate its backup before switching contexts.")
    return [binary, "--context", context] if context else [binary]


def _usable(prefix):
    try:
        # Local bind mounts must never be sent to a remote Docker host by accident.
        if "--context" not in prefix and os.environ.get("DOCKER_HOST", "").startswith(("tcp:", "ssh:")):
            return False
        name = prefix[prefix.index("--context") + 1] if "--context" in prefix else _run([prefix[0], "context", "show"]).stdout.strip()
        endpoint = _run([prefix[0], "context", "inspect", name, "--format", "{{.Endpoints.docker.Host}}"])
        if endpoint.returncode or not endpoint.stdout.strip().startswith(("unix://", "npipe://")):
            return False
        return _run([*prefix, "info", "--format", "{{.ServerVersion}}"]).returncode == 0 and _run([*prefix, "compose", "version", "--short"]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _installer(progress):
    system, machine = platform.system(), platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "amd64" if machine in {"x86_64", "amd64"} else ""
    if not arch: raise RuntimeError("Docker has no supported installer for this CPU")
    distro = platform.freedesktop_os_release().get("ID", "") if system == "Linux" else ""
    if system == "Linux" and arch != "amd64":
        raise RuntimeError("Docker Desktop for Linux requires x64. Connect an existing local Docker Engine in Memory settings on ARM Linux.")
    filename = {"Windows": "Docker Desktop Installer.exe", "Darwin": "Docker.dmg"}.get(system)
    if system == "Linux":
        filename = "docker-desktop-amd64.deb" if distro in {"ubuntu", "debian"} else "docker-desktop-x86_64.rpm" if distro == "fedora" else "docker-desktop-x86_64.pkg.tar.zst" if distro in {"arch", "endeavouros"} else None
    if not filename: raise RuntimeError("This Linux distribution needs an existing local Docker Engine. Memory can remain skipped while chat works.")
    base = f"https://desktop.docker.com/{'win' if system=='Windows' else 'mac' if system=='Darwin' else 'linux'}/main/{arch}/"
    progress("docker-download", "Downloading Docker’s native installer…")
    with urllib.request.urlopen(base + "checksums.txt", timeout=30) as response:
        text = response.read(32_768).decode()
    matches = [line.split(maxsplit=1)[0] for line in text.splitlines() if line.endswith(" *" + filename)]
    if len(matches) != 1 or len(matches[0]) != 64: raise RuntimeError("Docker's installer checksum is unavailable. Please retry.")
    checksum = matches[0]
    cache = home() / "cache/docker-installer"; cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = cache / filename
    if not target.is_file() or hashlib.file_digest(target.open("rb"), "sha256").hexdigest() != checksum:
        partial = cache / (filename + ".partial")
        digest, size = hashlib.sha256(), 0
        with urllib.request.urlopen(base + urllib.parse.quote(filename), timeout=60) as source, partial.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk); size += len(chunk)
                if size > 2_000_000_000: raise RuntimeError("Docker installer exceeds its size limit")
                output.write(chunk)
        if digest.hexdigest() != checksum:
            partial.unlink(missing_ok=True)
            raise RuntimeError("Docker installer checksum did not match. Please retry.")
        os.replace(partial, target)
    progress("docker-install", "Your operating system may ask permission to install Docker…")
    if system == "Windows":
        # PowerShell 5.1 / no-profile / hidden-console conventions match the vendored installer.
        script = "$s=Get-AuthenticodeSignature -LiteralPath $env:LUNA_DOCKER_INSTALLER; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Docker Inc'){exit 23}; $p=Start-Process -FilePath $env:LUNA_DOCKER_INSTALLER -ArgumentList 'install' -Verb RunAs -PassThru -Wait; exit $p.ExitCode"
        result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], timeout=1200,
                      env=dict(os.environ, LUNA_DOCKER_INSTALLER=str(target)))
    elif system == "Darwin":
        mount = cache / "mount"; mount.mkdir(exist_ok=True)
        attached = _run(["hdiutil", "attach", target, "-readonly", "-nobrowse", "-mountpoint", mount], timeout=120)
        if attached.returncode: raise RuntimeError("Docker's disk image could not be opened")
        try:
            app = mount / "Docker.app"
            if _run(["codesign", "--verify", "--deep", "--strict", app]).returncode or _run(["spctl", "--assess", "--type", "execute", app]).returncode:
                raise RuntimeError("macOS could not verify Docker's signature")
            # JSON quoting is for AppleScript's string; shlex quotes the actual shell argument.
            install = shlex.quote(str(app / "Contents/MacOS/install"))
            result = _run(["osascript", "-e", "do shell script " + json.dumps(install) + " with administrator privileges"], timeout=1200)
        finally:
            _run(["hdiutil", "detach", mount], timeout=60)
    else:
        helper = Path(__file__).resolve().with_name("docker_admin.py")
        result = _run(["pkexec", sys.executable, helper, str(target), checksum], timeout=1200)
    if result.returncode:
        raise RuntimeError("Docker installation did not finish. Approve the OS installer, then retry Memory setup.")


def _start_desktop():
    system = platform.system()
    if system == "Darwin": return _run(["open", "-a", "Docker"])
    if system == "Linux": return _run(["systemctl", "--user", "start", "docker-desktop"], timeout=60)
    for base in (Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker", Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop"):
        app = base / "Docker Desktop.exe"
        if app.is_file():
            from hermes_cli._subprocess_compat import windows_detach_popen_kwargs
            return subprocess.Popen([str(app)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **windows_detach_popen_kwargs())
    raise RuntimeError("Docker is installed but its app could not be found. Open Docker Desktop, then retry Memory setup.")


def ensure(progress=lambda stage, detail: None):
    prefix = command()
    if _usable(prefix):
        from luna_core.settings import _replace
        context = prefix[prefix.index("--context") + 1] if "--context" in prefix else _run([prefix[0], "context", "show"]).stdout.strip()
        _replace(home() / "honcho/.docker-runtime.json", json.dumps({"context": context}))
        return [prefix[0], "--context", context]
    binary = _binary()
    # A present CLI may belong to another daemon/context. Never reinstall or restart that engine.
    desktop_present = Path("/Applications/Docker.app").exists() or Path("/opt/docker-desktop").exists() or (platform.system() == "Windows" and binary and "Docker" in binary)
    if binary and not desktop_present:
        raise RuntimeError("Docker is present but its engine or Compose is unavailable. Select a working local Docker context in Memory settings and retry; Luna has kept its current configuration.")
    original_context = None
    if binary:
        result = _run([binary, "context", "show"])
        if result.returncode == 0: original_context = result.stdout.strip()
    if not desktop_present: _installer(progress)
    _start_desktop()
    progress("docker-start", "Waiting for Docker. Complete any permission or license prompts in its window…")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        binary = _binary()
        if binary:
            candidate = [binary, "--context", "desktop-linux"]
            if _usable(candidate):
                from luna_core.settings import _replace
                _replace(home() / "honcho/.docker-runtime.json", json.dumps({"context": "desktop-linux"}))
                # Desktop itself can switch the global context on first launch. Restore it;
                # Luna pins its own context per command instead of taking it over.
                if original_context:
                    current = _run([binary, "context", "show"])
                    if current.returncode == 0 and current.stdout.strip() != original_context:
                        _run([binary, "context", "use", original_context])
                return candidate
        time.sleep(2)
    raise RuntimeError("Docker needs attention in its own window, or an OS restart. Finish that step and retry Memory setup; chat still works.")
