"""Install only the pinned, checksum-verified Node executable needed by the bundled chat UI."""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import time
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _archive(url, target):
    """Resume public downloads and recheck the pinned digest even on cache hits."""
    from hermes_cli._file_lock import acquire
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "luna/node"
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = cache / target["filename"]
    partial = archive.with_suffix(archive.suffix + ".partial")
    with (cache / (archive.name + ".lock")).open("a+") as lock:
        acquire(lock)
        if archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest() == target["sha256"]:
            return archive
        archive.unlink(missing_ok=True)
        if partial.is_file() and hashlib.sha256(partial.read_bytes()).hexdigest() == target["sha256"]:
            os.replace(partial, archive)
            return archive
        for attempt in range(3):
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                    resumed = offset and response.status == 206 and response.headers.get("Content-Range", "").startswith(f"bytes {offset}-")
                    total = offset if resumed else 0
                    expected = int(response.headers.get("Content-Length", "0"))
                    received = 0
                    with partial.open("ab" if resumed else "wb") as output:
                        while chunk := response.read(256 * 1024):
                            total += len(chunk)
                            received += len(chunk)
                            if total > 100 * 1024 * 1024:
                                raise ValueError("Node archive exceeds size limit")
                            output.write(chunk)
                    if expected and received != expected:
                        raise OSError("Incomplete Node download")
                break
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError("Chat runtime download interrupted. Run the installer again to resume it.") from None
                time.sleep(attempt + 1)
        if hashlib.sha256(partial.read_bytes()).hexdigest() != target["sha256"]:
            partial.unlink(missing_ok=True)
            raise ValueError("Node checksum verification failed")
        os.replace(partial, archive)
        return archive


def install(release):
    manifest = json.loads(Path(__file__).with_name("node-releases.json").read_text())
    system = {"Linux": "linux", "Darwin": "darwin", "Windows": "win32"}.get(platform.system())
    arch = {"x86_64": "x64", "AMD64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    target = manifest["targets"].get(f"{system}-{arch}")
    if not target:
        raise ValueError("The dashboard chat runtime supports Linux/macOS/Windows on x64 and arm64")
    directory = release / "runtime/node"
    binary = directory / ("node.exe" if system == "win32" else "bin/node")
    directory.mkdir(parents=True, exist_ok=True)
    url = f"https://nodejs.org/dist/{manifest['version']}/{target['filename']}"
    archive = _archive(url, target)
    if system == "win32":
        prefix = target["filename"].removesuffix(".zip")
        with zipfile.ZipFile(archive) as source:
            for name in ("node.exe", "LICENSE"):
                member = source.getinfo(prefix + "/" + name)
                if member.file_size > 200 * 1024 * 1024:
                    raise ValueError("Invalid Node archive member")
                with source.open(member) as data, (directory / name).open("wb") as output:
                    shutil.copyfileobj(data, output)
        actual = subprocess.check_output([str(binary), "--version"], text=True, timeout=15,
                                         creationflags=subprocess.CREATE_NO_WINDOW).strip()
        if actual != manifest["version"]:
            raise ValueError("Installed Node version differs from the release manifest")
        return binary
    prefix = target["filename"].removesuffix(".tar.gz")
    with tarfile.open(archive) as source:
        for name, destination in [("bin/node", binary), ("LICENSE", directory / "LICENSE")]:
            member = source.getmember(prefix + "/" + name)
            if not member.isfile() or member.size > 200 * 1024 * 1024:
                raise ValueError("Invalid Node archive member")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as data, destination.open("wb") as output:
                shutil.copyfileobj(data, output)
            destination.chmod(0o755 if name == "bin/node" else 0o644)
    actual = subprocess.check_output([str(binary), "--version"], text=True, timeout=15).strip()
    if actual != manifest["version"]:
        raise ValueError("Installed Node version differs from the release manifest")
    return binary


if __name__ == "__main__":
    print(install(Path(sys.argv[1])))
