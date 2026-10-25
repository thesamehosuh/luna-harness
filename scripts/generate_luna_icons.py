#!/usr/bin/env python3
"""Regenerate dashboard and native launcher icons from the canonical Luna SVG.

Requires the workspace's installed Tauri CLI (npm install). Run from any directory.
Generated mobile/Store icons are discarded: this product ships desktop targets only.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "luna/assets/ui/luna-mark.svg"
NATIVE = ROOT / "apps/bootstrap-installer/src-tauri/icons"


def main():
    cli = ROOT / "node_modules/@tauri-apps/cli/tauri.js"
    with tempfile.TemporaryDirectory(prefix="luna-icons-") as temporary:
        output = Path(temporary)
        subprocess.run(["node", str(cli), "icon", str(SOURCE), "--output", str(output)], check=True)
        NATIVE.mkdir(parents=True, exist_ok=True)
        for name in ("32x32.png", "128x128.png", "128x128@2x.png", "icon.ico", "icon.icns"):
            shutil.copyfile(output / name, NATIVE / name)
        shutil.copyfile(output / "icon.ico", ROOT / "web/public/favicon.ico")
    shutil.copyfile(SOURCE, ROOT / "web/public/luna-mark.svg")


if __name__ == "__main__":
    main()
