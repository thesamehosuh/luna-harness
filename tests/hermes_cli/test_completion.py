"""Tests for hermes_cli/completion.py — shell completion script generation."""

import argparse
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from hermes_cli.completion import _walk, generate_bash, generate_zsh, generate_fish


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parser(prog: str = "hermes") -> argparse.ArgumentParser:
    """Build a minimal parser that mirrors the real CLI structure.

    Defaults to ``prog="hermes"`` so the pre-existing assertions keep exercising the engine-side
    name; the binding tests below pass ``prog="luna"`` explicitly.
    """
    p = argparse.ArgumentParser(prog=prog)
    p.add_argument("--version", "-V", action="store_true")
    p.add_argument("-p", "--profile", help="Profile name")
    sub = p.add_subparsers(dest="command")

    chat = sub.add_parser("chat", help="Interactive chat with the agent")
    chat.add_argument("-q", "--query")
    chat.add_argument("-m", "--model")

    gw = sub.add_parser("gateway", help="Messaging gateway management")
    gw_sub = gw.add_subparsers(dest="gateway_command")
    gw_sub.add_parser("start", help="Start service")
    gw_sub.add_parser("stop", help="Stop service")
    gw_sub.add_parser("status", help="Show status")
    # alias — should NOT appear as a duplicate in completions
    gw_sub.add_parser("run", aliases=["foreground"], help="Run in foreground")

    sess = sub.add_parser("sessions", help="Manage session history")
    sess_sub = sess.add_subparsers(dest="sessions_action")
    sess_sub.add_parser("list", help="List sessions")
    sess_sub.add_parser("delete", help="Delete a session")

    prof = sub.add_parser("profile", help="Manage profiles")
    prof_sub = prof.add_subparsers(dest="profile_command")
    prof_sub.add_parser("list", help="List profiles")
    prof_sub.add_parser("use", help="Switch to a profile")
    prof_sub.add_parser("create", help="Create a new profile")
    prof_sub.add_parser("delete", help="Delete a profile")
    prof_sub.add_parser("show", help="Show profile details")
    prof_sub.add_parser("alias", help="Set profile alias")
    prof_sub.add_parser("rename", help="Rename a profile")
    prof_sub.add_parser("export", help="Export a profile")

    sub.add_parser("version", help="Show version")

    return p


# ---------------------------------------------------------------------------
# 1. Parser extraction
# ---------------------------------------------------------------------------

class TestWalk:
    def test_top_level_subcommands_extracted(self):
        tree = _walk(_make_parser())
        assert set(tree["subcommands"].keys()) == {"chat", "gateway", "sessions", "profile", "version"}


    def test_aliases_not_duplicated(self):
        """'foreground' is an alias of 'run' — must not appear as separate entry."""
        tree = _walk(_make_parser())
        gw_subs = tree["subcommands"]["gateway"]["subcommands"]
        assert "foreground" not in gw_subs


# ---------------------------------------------------------------------------
# 2. Bash output
# ---------------------------------------------------------------------------

class TestGenerateBash:
    def test_contains_completion_function_and_register(self):
        out = generate_bash(_make_parser())
        assert "_hermes_completion()" in out
        assert "complete -F _hermes_completion hermes" in out


    def test_valid_bash_syntax(self):
        """Script must pass `bash -n` syntax check."""
        out = generate_bash(_make_parser())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bash", delete=False) as f:
            f.write(out)
            path = f.name
        try:
            result = subprocess.run(["bash", "-n", path], capture_output=True)
            assert result.returncode == 0, result.stderr.decode()
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 3. Zsh output
# ---------------------------------------------------------------------------

class TestGenerateZsh:


    def test_preserves_valid_zsh_arguments_alias_syntax(self):
        out = generate_zsh(_make_parser())
        assert "'(-)'{-h,--help}'[Show help and exit]'" in out
        assert "'(-)'{-V,--version}'[Show version and exit]'" in out
        assert "'(-)'{-p,--profile}'[Profile name]:profile:_hermes_profiles'" in out
        assert "'(-h --help){-h,--help}[Show help and exit]'" not in out
        assert '"(-h --help)"{-h,--help}"[Show help and exit]"' not in out

    def test_valid_zsh_syntax(self):
        if not shutil.which("zsh"):
            pytest.skip("zsh not installed")
        out = generate_zsh(_make_parser())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".zsh", delete=False) as f:
            f.write(out)
            path = f.name
        try:
            result = subprocess.run(["zsh", "-n", path], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 4. Fish output
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. Subcommand drift prevention
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. Profile completion (regression prevention)
# ---------------------------------------------------------------------------

class TestProfileCompletion:
    """Ensure profile name completion is present in all shell outputs."""




    def test_bash_profile_actions_complete_profile_names(self):
        """After 'hermes profile use', complete with profile names."""
        out = generate_bash(_make_parser())
        # The profile case should have _hermes_profiles for name-taking actions
        lines = out.split("\n")
        in_profile_case = False
        has_profiles_in_action = False
        for line in lines:
            if "profile)" in line:
                in_profile_case = True
            if in_profile_case and "_hermes_profiles" in line:
                has_profiles_in_action = True
                break
        assert has_profiles_in_action, "profile actions should complete with _hermes_profiles"


    def test_fish_profile_actions_complete_names(self):
        out = generate_fish(_make_parser())
        # Should have profile name completion for actions like use, delete, etc.
        assert "__hermes_profiles" in out
        count = out.count("(__hermes_profiles)")
        # At least the -p flag + the profile action completions
        assert count >= 2, f"Expected >=2 profile completion entries, got {count}"


# ---------------------------------------------------------------------------
# 7. The script binds the command it was generated for
# ---------------------------------------------------------------------------

class TestProgBinding:
    """The emitted script must register itself for ``parser.prog``.

    Every name in the generated script used to be hardcoded to ``hermes``, so
    ``luna completion bash`` produced a script bound to ``hermes``: installing it looked like it
    worked and then never completed anything, because the command it completed was not the one
    being typed. Nothing caught this -- the syntax checks passed, the profile assertions passed,
    and the tests all built ``prog="hermes"`` so they were asserting the hardcoded value.
    """

    def test_bash_binds_the_parser_prog(self):
        out = generate_bash(_make_parser(prog="luna"))
        assert "complete -F _luna_completion luna" in out
        assert "_hermes_completion" not in out

    def test_zsh_binds_the_parser_prog(self):
        out = generate_zsh(_make_parser(prog="luna"))
        assert "#compdef luna" in out
        assert "compdef _luna luna" in out
        assert "_hermes" not in out

    def test_fish_binds_the_parser_prog(self):
        out = generate_fish(_make_parser(prog="luna"))
        assert "complete -c luna -f" in out
        assert "complete -c hermes" not in out

    def test_bash_still_binds_hermes_when_that_is_the_prog(self):
        """Derived, not replaced: an engine-side caller keeps working."""
        out = generate_bash(_make_parser(prog="hermes"))
        assert "complete -F _hermes_completion hermes" in out

    def test_prog_path_is_reduced_to_a_bare_command_name(self):
        """A ``prog`` carrying a directory must not leak it into `complete`."""
        out = generate_bash(_make_parser(prog="/opt/luna/bin/luna"))
        assert "complete -F _luna_completion luna" in out
        assert "/opt/luna" not in out


class TestProfileHomeResolution:
    """The profile dir follows the environment, not one baked-in install layout.

    Mirrors ``luna_cli.main.luna_home()``: ``$LUNA_HOME`` -> ``$HERMES_HOME`` -> ``~/.luna``.
    The script previously hardcoded ``$HOME/.hermes/profiles``, so on a Luna install the -p flag
    completed no profile names at all -- silently, since completing nothing is not an error.
    """

    @pytest.mark.parametrize("generate", [generate_bash, generate_zsh, generate_fish])
    def test_every_shell_resolves_the_profile_dir_through_luna_home(self, generate):
        out = generate(_make_parser(prog="luna"))
        assert "${LUNA_HOME:-${HERMES_HOME:-$HOME/.luna}}" in out

    @pytest.mark.parametrize("generate", [generate_bash, generate_zsh, generate_fish])
    def test_no_shell_references_the_engine_home(self, generate):
        out = generate(_make_parser(prog="luna"))
        assert "$HOME/.hermes" not in out

    def test_zsh_profile_glob_uses_the_resolved_home(self):
        out = generate_zsh(_make_parser(prog="luna"))
        assert "local profiles_dir=\"${LUNA_HOME:-${HERMES_HOME:-$HOME/.luna}}\"/profiles" in out
        assert "profiles+=($profiles_dir/*(N/:t))" in out
        assert "profiles+=($HOME/.luna/profiles/" not in out
