"""Linux-only native package installation, invoked by pkexec after an OS consent dialog."""
from pathlib import Path
import hashlib
import os
import platform
import re
import subprocess
import sys
import urllib.request


def main():
    if os.geteuid() != 0: raise SystemExit("OS administrator approval is required")
    package, checksum = Path(sys.argv[1]).resolve(), sys.argv[2]
    with package.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != checksum: raise SystemExit("Installer verification failed")
    info = platform.freedesktop_os_release()
    distro = info.get("ID")
    if distro in {"ubuntu", "debian"}:
        codename = info.get("VERSION_CODENAME", "")
        if not re.fullmatch(r"[a-z0-9]+", codename): raise SystemExit("Unsupported OS release")
        keys = Path("/etc/apt/keyrings"); keys.mkdir(mode=0o755, exist_ok=True)
        with urllib.request.urlopen(f"https://download.docker.com/linux/{distro}/gpg", timeout=30) as response:
            key = response.read(64_000)
        (keys / "luna-docker.asc").write_bytes(key); (keys / "luna-docker.asc").chmod(0o644)
        source = Path("/etc/apt/sources.list.d/luna-docker.sources")
        if not source.exists():
            source.write_text(f"Types: deb\nURIs: https://download.docker.com/linux/{distro}\nSuites: {codename}\nComponents: stable\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/luna-docker.asc\n")
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(["apt-get", "install", "-y", str(package)], check=True)
    elif distro == "fedora":
        repo = Path("/etc/yum.repos.d/luna-docker-ce.repo")
        if not repo.exists():
            with urllib.request.urlopen("https://download.docker.com/linux/fedora/docker-ce.repo", timeout=30) as response:
                repo.write_bytes(response.read(64_000))
        subprocess.run(["dnf", "install", "-y", str(package)], check=True)
    elif distro in {"arch", "endeavouros"}:
        subprocess.run(["pacman", "-U", "--noconfirm", str(package)], check=True)
    else:
        raise SystemExit("Unsupported Linux installer")


if __name__ == "__main__": main()
