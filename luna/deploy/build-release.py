"""Build a portable release bundle with prebuilt dashboard assets and a checksum."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

from assemble import assemble
from bundle_embeddings import bundle


def build(source: Path, output: Path, *, skip_build: bool = False, download_base: str = "") -> Path:
    source = source.resolve()
    if output.resolve().is_relative_to(source):
        raise ValueError("release output must be outside the source checkout")
    if not skip_build:
        if not (source / "node_modules/.bin/vite").exists() or not (source / "node_modules/@hermes/ink").exists():
            subprocess.run(["npm", "ci", "--workspace", "web", "--workspace", "ui-tui", "--include-workspace-root"], cwd=source, check=True)
        subprocess.run(["npm", "run", "build", "--workspace", "web"], cwd=source, check=True)
        subprocess.run(["npm", "run", "build", "--workspace", "ui-tui"], cwd=source, check=True)
        destination = source / "hermes_cli/tui_dist/entry.js"
        destination.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(source / "ui-tui/dist/entry.js", destination)
        (destination.parent / "package.json").write_text('{"name":"luna-chat","private":true,"type":"module"}\n')
    if not (source / "hermes_cli/web_dist/index.html").is_file():
        raise ValueError("dashboard assets are missing")
    if not (source / "hermes_cli/tui_dist/entry.js").is_file():
        raise ValueError("dashboard chat assets are missing")
    version = json.loads((source / "luna-release.json").read_text())["version"]
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"luna-{version}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="luna-release-") as tmp:
        runtime = Path(tmp) / f"luna-{version}"
        assemble(source, runtime)
        import shutil
        cache = Path(os.environ.get("LUNA_EMBEDDING_BUNDLE") or Path.home() / ".cache/luna/release-embeddings-v1")
        bundle(cache)
        assets = runtime / "luna/assets/embeddings"
        shutil.copytree(cache, assets, dirs_exist_ok=True)
        # Reuse only the vendored native Git stage. No clone, Electron, PATH or gateway stages.
        windows = runtime / "luna/deploy/windows-bootstrap.ps1"
        shutil.copy2(source / "scripts/install.ps1", windows)
        inventory = runtime / ".luna-assemble-manifest.json"
        entries = json.loads(inventory.read_text())
        entries["files"] = sorted(set(entries["files"]) | {str(p.relative_to(runtime)) for p in assets.rglob("*") if p.is_file()} | {str(windows.relative_to(runtime))})
        inventory.write_text(json.dumps(entries, indent=2) + "\n")
        with tarfile.open(artifact, "w:gz") as tar:
            tar.add(runtime, arcname=runtime.name)
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    artifact.with_suffix(artifact.suffix + ".sha256").write_text(f"{checksum}  {artifact.name}\n")
    if download_base:
        from urllib.parse import urlparse
        if urlparse(download_base).scheme != "https":
            raise ValueError("Published release URLs require HTTPS")
        (output / "luna-launcher-release.json").write_text(json.dumps({
            "version": version, "runtime": {"url": download_base.rstrip("/") + "/" + artifact.name, "sha256": checksum}
        }, indent=2) + "\n")
    return artifact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--skip-build", action="store_true", help="use already-built dashboard assets")
    parser.add_argument("--download-base", default="", help="HTTPS release-assets directory baked into the native launcher")
    args = parser.parse_args()
    print(build(Path(__file__).resolve().parents[2], args.output, skip_build=args.skip_build, download_base=args.download_base))
