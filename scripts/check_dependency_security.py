#!/usr/bin/env python3
"""Audit every Python lock entry and every npm lock; never silently skip an ecosystem."""
from __future__ import annotations
import collections
import hashlib
import os
import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    failures = []
    packages = collections.defaultdict(list)
    for package in tomllib.loads((ROOT / "uv.lock").read_text())["package"]:
        if "registry" in package.get("source", {}):
            packages[package["name"]].append(package["version"])
    with tempfile.TemporaryDirectory(prefix="luna-audit-") as directory:
        # uv can lock several versions for different platform markers. Audit each
        # version, including Windows/macOS entries, without resolving/installing it.
        for index in range(max(map(len, packages.values()))):
            requirements = Path(directory) / f"requirements-{index}.txt"
            requirements.write_text("\n".join(sorted(
                f"{name}=={versions[index]}" for name, versions in packages.items() if len(versions) > index)) + "\n")
            result = subprocess.run(["uvx", "--from", "pip-audit==2.10.1", "pip-audit", "--no-deps", "--disable-pip", "-r", str(requirements)], cwd=ROOT)
            if result.returncode: failures.append(f"Python lock layer {index}")
    for lock in subprocess.check_output(["git", "ls-files", "*package-lock.json"], cwd=ROOT, text=True).splitlines():
        with tempfile.TemporaryDirectory(prefix="luna-npm-audit-") as directory:
            prefix = (ROOT / lock).parent
            if Path(lock).name != "package-lock.json":
                # Nix carries a renamed npm lock for its build tool. npm audit
                # needs the conventional filename, even without installing it.
                prefix = Path(directory)
                data = json.loads((ROOT / lock).read_text())
                shutil.copyfile(ROOT / lock, prefix / "package-lock.json")
                (prefix / "package.json").write_text(json.dumps(data["packages"][""]))
            result = subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "audit", "--audit-level=low", "--prefix", str(prefix)], cwd=ROOT)
            if result.returncode: failures.append(lock)
    # The GTK3 backport must be the crate Cargo actually selects. This check is
    # paired with cargo-audit's single documented advisory exception in CI.
    cargo = ROOT / "apps/bootstrap-installer/src-tauri"
    patch = tomllib.loads((cargo / "Cargo.toml").read_text())["patch"]["crates-io"]["glib"]
    lock = tomllib.loads((cargo / "Cargo.lock").read_text())
    glib = next(package for package in lock["package"] if package["name"] == "glib")
    source = (cargo / patch["path"] / "src/variant_iter.rs").read_text()
    if glib.get("source") or glib["version"] != "0.18.5" or hashlib.sha256(source.encode()).hexdigest() != "a0f5ee8acb8faa089bcdfbc9a57372609fce7654026ccef7d9a224d05a654ccc":
        failures.append("GTK3 glib security backport")
    if failures:
        raise SystemExit("Security checks failed: " + ", ".join(failures))
    print("All Python/npm dependency and GTK3 patch checks passed.")


if __name__ == "__main__":
    main()
