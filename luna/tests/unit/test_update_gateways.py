"""Runtime updates restore only companions that were active before publication."""
import importlib.util
from pathlib import Path
import signal
import sys

import pytest

spec = importlib.util.spec_from_file_location("update_gateways", Path(__file__).resolve().parents[2] / "deploy/update_gateways.py")
gateways = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateways)


@pytest.mark.parametrize("fail_install", [False, True])
def test_running_profiles_resume_even_when_install_fails(tmp_path, monkeypatch, fail_install):
    active = tmp_path / "profiles/active"
    inactive = tmp_path / "profiles/inactive"
    active.mkdir(parents=True)
    inactive.mkdir()
    state = {tmp_path: True, active: True, inactive: False}
    events = []
    monkeypatch.setattr(gateways, "_running", lambda python, profile: state[profile])
    monkeypatch.setattr(gateways, "_check_owner", lambda python, profile: None)
    def stop(python, profile):
        events.append(("stop", profile, python))
        state[profile] = False
    def start(python, profile):
        events.append(("start", profile, python))
        state[profile] = True
    monkeypatch.setattr(gateways, "_stop", stop)
    monkeypatch.setattr(gateways, "_start", start)
    def install():
        with gateways.paused_gateways(tmp_path, "old", lambda: "old" if fail_install else "new"):
            assert not any(state.values())
            if fail_install:
                raise ValueError("installation failed")
    if fail_install:
        with pytest.raises(ValueError, match="installation failed"):
            install()
    else:
        install()
    assert state == {tmp_path: True, active: True, inactive: False}
    assert [(e[0], e[1]) for e in events] == [("stop", tmp_path), ("stop", active), ("start", tmp_path), ("start", active)]
    assert all(e[2] == ("old" if fail_install else "new") for e in events if e[0] == "start")


def test_partial_stop_failure_restores_already_stopped_profiles(tmp_path, monkeypatch):
    active = tmp_path / "profiles/active"
    active.mkdir(parents=True)
    state = {tmp_path: True, active: True}
    monkeypatch.setattr(gateways, "_running", lambda python, profile: state[profile])
    monkeypatch.setattr(gateways, "_check_owner", lambda python, profile: None)
    def stop(python, profile):
        state[profile] = False
        if profile == active:
            raise RuntimeError("stop failed")
    monkeypatch.setattr(gateways, "_stop", stop)
    monkeypatch.setattr(gateways, "_start", lambda python, profile: state.update({profile: True}))
    with pytest.raises(RuntimeError, match="stop failed"):
        with gateways.paused_gateways(tmp_path, "old", lambda: "old"):
            pytest.fail("installation should not proceed")
    assert all(state.values())


def test_cancellation_restores_companion(tmp_path, monkeypatch):
    state = {tmp_path: True}
    monkeypatch.setattr(gateways, "_running", lambda python, profile: state[profile])
    monkeypatch.setattr(gateways, "_check_owner", lambda python, profile: None)
    monkeypatch.setattr(gateways, "_stop", lambda python, profile: state.update({profile: False}))
    monkeypatch.setattr(gateways, "_start", lambda python, profile: state.update({profile: True}))
    with pytest.raises(InterruptedError):
        with gateways.paused_gateways(tmp_path, "old", lambda: "old"):
            signal.raise_signal(signal.SIGTERM)
    assert state[tmp_path]


def test_repeated_cancellation_does_not_interrupt_recovery(tmp_path, monkeypatch):
    state = {tmp_path: True}
    monkeypatch.setattr(gateways, "_running", lambda python, profile: state[profile])
    monkeypatch.setattr(gateways, "_check_owner", lambda python, profile: None)
    monkeypatch.setattr(gateways, "_stop", lambda python, profile: state.update({profile: False}))
    def start(python, profile):
        signal.raise_signal(signal.SIGTERM)
        state[profile] = True
    monkeypatch.setattr(gateways, "_start", start)
    with pytest.raises(InterruptedError):
        with gateways.paused_gateways(tmp_path, "old", lambda: "old"):
            signal.raise_signal(signal.SIGTERM)
    assert state[tmp_path]


def test_named_profile_action_drops_default_profile_secret(tmp_path, monkeypatch):
    profile = tmp_path / "profiles/other"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("{}\n")
    (tmp_path / ".env").write_text("LUNA_TEST_PROFILE_SECRET=private\n")
    monkeypatch.setenv("LUNA_TEST_PROFILE_SECRET", "private")
    env = gateways._action_env(Path(sys.executable), profile)
    assert "LUNA_TEST_PROFILE_SECRET" not in env
    assert env["HERMES_HOME"] == str(profile)
    assert env["LUNA_HOME"] == str(profile)


def test_installed_service_blocks_publication_even_if_profile_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(gateways, "_running", lambda python, profile: False)
    def check_service(python, profile):
        raise RuntimeError("service still references the old runtime")
    monkeypatch.setattr(gateways, "_check_owner", check_service)
    with pytest.raises(RuntimeError, match="service still references"):
        with gateways.paused_gateways(tmp_path, "old", lambda: "new"):
            pytest.fail("publication would leave a stale service executable")


def test_installed_service_has_actionable_error(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(gateways.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=4))
    with pytest.raises(RuntimeError, match="service.*old runtime"):
        gateways._check_owner("old", tmp_path)
