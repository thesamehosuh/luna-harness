"""Exercise the installed service entry point across a real Python exec boundary."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import venv


def test_pinned_service_entrypoint_executes_selected_runtime(tmp_path):
    source = Path(__file__).resolve().parents[3]
    home = tmp_path / "Luna home"
    old, selected = home / "releases/old", home / "releases/new"
    python_name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    for release in (old, selected):
        venv.EnvBuilder(with_pip=False).create(release / "venv")
        python = release / "venv" / python_name
        site = subprocess.check_output(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True,
        ).strip()
        Path(site, "test-release.pth").write_text(str(release) + "\n", encoding="utf-8")
        (release / "luna_cli").mkdir()
        (release / "luna_cli/__init__.py").touch()
        (release / ".luna-state-home").write_text(str(home), encoding="utf-8")
        (release / ".ready").write_text("verified\n", encoding="utf-8")
    # Use the real shipped entry point and pointer resolver in the old runtime.
    shutil.copy2(source / "luna/lib/luna_cli/main.py", old / "luna_cli/main.py")
    (old / "hermes_cli").mkdir()
    (old / "hermes_cli/__init__.py").touch()
    shutil.copy2(source / "hermes_cli/product_runtime.py", old / "hermes_cli/product_runtime.py")
    # The selected fixture reports which interpreter and argv actually reached it.
    (selected / "luna_cli/main.py").write_text(
        "import json,sys; print(json.dumps({'prefix':sys.prefix,'argv':sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    (home / "current-release.json").write_text(
        json.dumps({"format": 1, "path": "releases/new", "version": "fixture"}),
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", "LUNA_HOME"}}
    env.update(HERMES_HOME=str(home), VIRTUAL_ENV=str(old / "venv"))
    result = subprocess.run(
        [str(old / "venv" / python_name), "-m", "luna_cli.main", "gateway", "run"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30, check=True,
    )
    received = json.loads(result.stdout)
    assert Path(received["prefix"]).resolve() == (selected / "venv").resolve()
    assert received["argv"] == ["gateway", "run"]
