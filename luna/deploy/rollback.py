"""Stop only the units recorded by this trial install; retain all state and the old deployment."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def rollback(home: Path) -> None:
    if (home / "previous").is_symlink() or (home / "current-release.json").is_file():
        from releases import rollback as restore_release
        restore_release(home)
        print("Previous code and environment restored. State retained. Start the gateway from the dashboard when ready.")
        return
    manifest = home / ".luna-units.json"
    if not manifest.exists():
        print("No service units were installed for this home. Nothing to stop.")
        return
    units = json.loads(manifest.read_text())
    for unit in units:
        if not isinstance(unit, str) or "/" in unit or not unit.endswith((".service", ".timer")):
            raise ValueError("invalid unit manifest")
        subprocess.run(["systemctl", "--user", "disable", "--now", unit], check=True)
    print("Trial units stopped. All files retained; start the previous gateway when ready.")


if __name__ == "__main__":
    rollback(Path(sys.argv[1]).expanduser().resolve())
