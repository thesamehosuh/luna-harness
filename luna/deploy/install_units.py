"""Install service definitions for this home without stopping or enabling any gateway."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
from pathlib import Path


def install_units() -> list[str]:
    from hermes_cli.gateway import generate_systemd_unit, get_service_name

    home = Path(os.environ["HERMES_HOME"]).resolve()
    product = home / "luna"
    unit_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    name = get_service_name() + ".service"
    (unit_dir / name).write_text(generate_systemd_unit(), encoding="utf-8")
    installed = [name]
    suffix = hashlib.sha256(str(home).encode()).hexdigest()[:8]
    for stem in ("luna-log-retention", "luna-data-retention", "luna-logger"):
        if stem == "luna-logger" and os.getenv("LUNA_LOGGER_SERVICE") != "1":
            continue
        for extension in ("service", "timer"):
            template = product / "systemd" / f"{stem}.{extension}"
            if not template.exists():
                continue
            lines = []
            for line in template.read_text().splitlines():
                key, separator, value = line.partition("=")
                if separator and key in {"ExecStart", "Environment", "EnvironmentFile", "WorkingDirectory"}:
                    arguments = [arg.replace("@HERMES_HOME@", str(home)).replace("@REPO_ROOT@", str(home))
                                 for arg in shlex.split(value)]
                    def quote(argument: str) -> str:
                        return '"' + argument.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'
                    line = key + "=" + " ".join(quote(arg) for arg in arguments)
                lines.append(line)
            rendered = "\n".join(lines) + "\n"
            rendered = rendered.replace(f"Unit={stem}.service", f"Unit={stem}-{suffix}.service")
            unit_name = f"{stem}-{suffix}.{extension}"
            (unit_dir / unit_name).write_text(rendered, encoding="utf-8")
            installed.append(unit_name)
    (home / ".luna-units.json").write_text(json.dumps(installed) + "\n")
    print("==> installed service definitions (not started or enabled): " + ", ".join(installed))
    return installed


if __name__ == "__main__":
    install_units()
