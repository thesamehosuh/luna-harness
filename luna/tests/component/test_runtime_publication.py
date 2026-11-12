"""Runtime publication excludes old and new gateway startup across the installation."""
import os
from pathlib import Path
import subprocess
import sys

from hermes_cli._file_lock import acquire


def probe(root, code):
    source = Path(__file__).resolve().parents[3]
    env = dict(os.environ, HERMES_HOME=str(root), LUNA_HOME=str(root),
               PYTHONPATH=os.pathsep.join((str(source / "luna/lib"), str(source))))
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=15, check=True)


def test_new_gateway_cannot_start_while_release_publication_lock_is_held(tmp_path):
    root = tmp_path / "home"
    root.mkdir()
    # A newly created profile wasn't in an installer's original inventory. Its
    # start still uses the installation lock, not just its own runtime lock.
    profile = root / "profiles/new"
    profile.mkdir(parents=True)
    with (root / ".release.lock").open("a+") as handle:
        acquire(handle)
        result = probe(profile, "from gateway.status import acquire_gateway_runtime_lock; print(acquire_gateway_runtime_lock())")
    assert result.stdout.strip() == "False"


def test_publication_fences_legacy_runtime_claim_and_releases_locks(tmp_path):
    import importlib.util
    source = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("test_publication_gateways", source / "luna/deploy/update_gateways.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "home"
    root.mkdir()
    profile = root / "profiles/second"
    profile.mkdir(parents=True)
    code = "from gateway.status import _try_acquire_file_lock; from hermes_constants import get_process_hermes_home; h=(get_process_hermes_home()/'gateway.lock').open('a+'); print(_try_acquire_file_lock(h))"
    with module.stopped_gateway_locks(root):
        assert probe(root, code).stdout.strip() == "False"
        assert probe(profile, code).stdout.strip() == "False"
    assert probe(root, code).stdout.strip() == "True"
    assert probe(profile, code).stdout.strip() == "True"
