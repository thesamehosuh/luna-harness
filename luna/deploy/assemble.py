"""Copy code and built assets, keeping development files and local state out of releases."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Python packages declared in pyproject.toml must remain in this keep-set, including
# acp_adapter: model_tools imports its edit-approval guard on every file write.
EXCLUDED_ROOTS = {
    "apps", "website", "web", "ui-tui", "optional-skills", "optional-mcps",
    "contributors", "evals", "tests", "tests-js", "docker", "nix", "plans",
    "scripts", "MagicMock", "node_modules", "venv", "luna", "hermes_agent.egg-info",
    "luna_harness.egg-info", "PRODUCT_PLAN.md", "POLISH_PLAN.md", "CONTRIBUTING.md",
    "SECURITY.md", "Dockerfile", "cli-config.yaml.example", "setup-hermes.sh",
    "test_durations.json", "package-lock.json", "package.json",
    "output", "dist", "build", "ignored", "tmp", "logs", "data",
    "test-results", "playwright-report",
}
OVERLAY_TREES = ("lib", "plugins", "config", "soul", "skills", "honcho", "tools", "bin", "deploy", "systemd", "assets")
USER_FILES = {"config.yaml", "honcho.json", "SOUL.md", "AGENTS.md", "auth.json"}


def excluded(path: Path, *, overlay: bool = False) -> bool:
    parts = path.parts
    if any(p.startswith(".") or p in {"__pycache__", "node_modules", "venv", "tests", "__tests__"}
           or p.endswith(".egg-info") for p in parts):
        # This is a public template, never a runtime secrets file.
        if path.name != ".env.template" or any(p.startswith(".") for p in parts[:-1]):
            return True
    if path.name in {"AGENTS.md", "SOUL.md"} and not (overlay and parts[0] == "soul"):
        return True
    if path.suffix in {".pyc", ".pyo", ".db", ".log"} or path.name.endswith(("-wal", "-shm")):
        return True
    if not overlay:
        return (parts[0] in EXCLUDED_ROOTS or parts[0] in USER_FILES
                or parts[0].startswith(("README.", "CONTRIBUTING.", "SECURITY.", "Dockerfile.", "docker-compose."))
                and parts[0] != "README.md")
    return False


def validate_paths(source: Path, target: Path) -> tuple[Path, Path]:
    source, target = source.resolve(), target.expanduser().resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("source and target must be separate directories, neither inside the other")
    return source, target


def assemble(source: Path, target: Path, *, dry_run: bool = False) -> list[str]:
    source, target = validate_paths(source, target)
    if not (source / "pyproject.toml").is_file():
        raise ValueError(f"not a Luna source or release directory: {source}")
    if (target / "current").exists() or (target / "venv").exists():
        raise ValueError("assembly does not mutate installed runtimes; use the staged installer")
    if (target / "luna").is_symlink():
        raise ValueError(f"refusing to copy through a destination symlink: {target / 'luna'}")
    if not dry_run:
        assemble(source, target, dry_run=True)
    old_manifest = target / ".luna-assemble-manifest.json"
    old_files = json.loads(old_manifest.read_text()).get("files", []) if old_manifest.exists() else []
    copied: list[str] = []

    def copy_tree(root: Path, dest: Path, relative: Path, overlay: bool = False):
        if excluded(relative, overlay=overlay):
            return
        src, dst = root / relative, dest / relative
        if src.is_symlink():
            # Never package an absolute/source-external link (it can contain private data).
            link = Path(os.readlink(src))
            if link.is_absolute() or not src.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"source-external symlink cannot ship: {src}")
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.is_symlink():
                    dst.unlink()
                if dst.exists():
                    raise ValueError(f"refusing to replace a real path with a symlink: {dst}")
                dst.symlink_to(link)
            copied.append(str(dst.relative_to(target)))
        elif src.is_dir():
            if dst.is_symlink():
                raise ValueError(f"refusing to copy through a destination symlink: {dst}")
            for child in sorted(src.iterdir()):
                copy_tree(root, dest, relative / child.name, overlay)
        else:
            if dst.is_symlink():
                raise ValueError(f"refusing to overwrite a destination symlink: {dst}")
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            copied.append(str(dst.relative_to(target)))

    for child in sorted(source.iterdir()):
        copy_tree(source, target, Path(child.name))
    for name in OVERLAY_TREES:
        if (source / "luna" / name).is_dir():
            copy_tree(source / "luna", target / "luna", Path(name), overlay=True)
    if not dry_run:
        for name in set(old_files) - set(copied):
            stale = target / name
            if stale.resolve().is_relative_to(target) and stale.is_file():
                stale.unlink()
        manifest = {"format": 1, "generated": datetime.now(timezone.utc).isoformat(), "files": copied}
        (target / ".luna-assemble-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return copied


if __name__ == "__main__":
    try:
        files = assemble(Path(sys.argv[1]), Path(sys.argv[2]), dry_run=os.getenv("DRY_RUN") == "1")
    except (OSError, ValueError) as exc:
        sys.exit(f"assemble: {exc}")
    print(f"==> {'would copy' if os.getenv('DRY_RUN') == '1' else 'assembled'} {len(files)} files")
