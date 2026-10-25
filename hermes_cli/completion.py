"""Shell completion script generation for the Luna CLI. Walks the live argparse parser tree, so
completion scripts never go stale; no extra dependencies.

Every command name in the generated script is derived from ``parser.prog``, not hardcoded. It used
to be hardcoded to ``hermes``, so ``luna completion bash`` emitted a script that registered itself
for ``hermes`` -- installing it appeared to work and then never completed anything, because the
command it completed was not the one being typed. Deriving from ``prog`` means the script binds
whatever the parser calls itself, and a test that builds ``prog="hermes"`` still gets ``hermes``.
"""

from __future__ import annotations

import argparse
import os
import re
from typing import Any


def _walk(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Recursively extract subcommands and flags from a parser."""
    flags: list[str] = []
    subcommands: dict[str, Any] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            # _choices_actions has one entry per canonical name (aliases omitted).
            for pseudo in action._choices_actions:
                name = pseudo.dest
                subparser = action.choices.get(name)
                if name in subcommands or subparser is None:
                    continue
                subcommands[name] = {**_walk(subparser), "help": _clean(pseudo.help or "")}
        elif action.option_strings:
            flags.extend(o for o in action.option_strings if o.startswith("-"))
    return {"flags": flags, "subcommands": subcommands}


def _sh_ident(prog: str) -> str:
    """``prog`` -> a shell-identifier-safe stem: ``/usr/bin/luna`` -> ``luna``.

    The generated scripts name a helper function after the command, so the stem has to survive
    being pasted into a shell as an identifier.
    """
    stem = re.sub(r"[^0-9A-Za-z]+", "_", os.path.basename(prog or "").strip()).strip("_")
    return stem or "luna"


def _cmd_name(prog: str) -> str:
    """The command word to bind completions to: a bare name, never a path."""
    return os.path.basename(prog or "").strip() or "luna"


# Profile directory resolution, emitted as a shell expression so it follows the environment at
# completion time rather than baking one install layout into a generated script. Mirrors
# ``luna_cli.main.luna_home()``: $LUNA_HOME -> $HERMES_HOME -> ~/.luna.
_HOME_EXPR = '"${LUNA_HOME:-${HERMES_HOME:-$HOME/.luna}}"'


def _clean(text: str, maxlen: int = 60) -> str:
    """Strip shell-unsafe characters and truncate."""
    return text.replace("'", "").replace('"', "").replace("\\", "")[:maxlen]


# Profile actions that take a profile name as their next argument.
_PROFILE_NAME_ACTIONS = ("use", "delete", "show", "alias", "rename", "export")


def _sorted_subcommands(parser: argparse.ArgumentParser) -> list[tuple[str, dict[str, Any]]]:
    return sorted(_walk(parser)["subcommands"].items())


def generate_bash(parser: argparse.ArgumentParser) -> str:
    ident, prog = _sh_ident(parser.prog), _cmd_name(parser.prog)
    subcommands = _sorted_subcommands(parser)
    top_cmds = " ".join(cmd for cmd, _ in subcommands)
    cases: list[str] = []
    for cmd, info in subcommands:
        if cmd == "profile" and info["subcommands"]:
            # Complete actions, then profile names for actions that accept a profile argument.
            subcmds = " ".join(sorted(info["subcommands"]))
            cases.append(
                f"        profile)\n"
                f"            case \"$prev\" in\n"
                f"                profile)\n"
                f"                    COMPREPLY=($(compgen -W \"{subcmds}\" -- \"$cur\"))\n"
                f"                    return\n"
                f"                    ;;\n"
                f"                {'|'.join(_PROFILE_NAME_ACTIONS)})\n"
                f"                    COMPREPLY=($(compgen -W \"$(_{ident}_profiles)\" -- \"$cur\"))\n"
                f"                    return\n"
                f"                    ;;\n"
                f"            esac\n"
                f"            ;;")
        elif info["subcommands"] or info["flags"]:
            words = " ".join(sorted(info["subcommands"]) if info["subcommands"] else info["flags"])
            cases.append(
                f"        {cmd})\n"
                f"            COMPREPLY=($(compgen -W \"{words}\" -- \"$cur\"))\n"
                f"            return\n"
                f"            ;;")
    cases_str = "\n".join(cases)
    return f"""# Luna Agent bash completion
# Add to ~/.bashrc:
#   eval "$({prog} completion bash)"

_{ident}_profiles() {{
    local profiles_dir={_HOME_EXPR}/profiles
    local profiles="default"
    if [ -d "$profiles_dir" ]; then
        for f in "$profiles_dir"/*/; do
            [ -d "$f" ] && profiles="$profiles $(basename "$f")"
        done
    fi
    echo "$profiles"
}}

_{ident}_completion() {{
    local cur prev
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    # Complete profile names after -p / --profile
    if [[ "$prev" == "-p" || "$prev" == "--profile" ]]; then
        COMPREPLY=($(compgen -W "$(_{ident}_profiles)" -- "$cur"))
        return
    fi

    if [[ $COMP_CWORD -ge 2 ]]; then
        case "${{COMP_WORDS[1]}}" in
{cases_str}
        esac
    fi

    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=($(compgen -W "{top_cmds}" -- "$cur"))
    fi
}}

complete -F _{ident}_completion {prog}
"""


def _zsh_describe_lines(subcommands: dict[str, Any], indent: str) -> str:
    """One ``'name:help'`` line per subcommand, sorted, at the given indent."""
    return "\n".join(
        f"{indent}'{sc}:{_clean(subcommands[sc].get('help', ''))}'" for sc in sorted(subcommands))


def generate_zsh(parser: argparse.ArgumentParser) -> str:
    ident, prog = _sh_ident(parser.prog), _cmd_name(parser.prog)
    subcommands = _sorted_subcommands(parser)
    top_cmds_str = _zsh_describe_lines(dict(subcommands), " " * 16)
    sub_cases: list[str] = []
    for cmd, info in subcommands:
        if not info["subcommands"]:
            continue
        if cmd == "profile":
            # Complete actions, then profile names for actions that accept a profile argument.
            sub_str = _zsh_describe_lines(info["subcommands"], " " * 24)
            sub_cases.append(
                f"                profile)\n"
                f"                    case ${{line[2]}} in\n"
                f"                        {'|'.join(_PROFILE_NAME_ACTIONS)})\n"
                f"                            _{ident}_profiles\n"
                f"                            ;;\n"
                f"                        *)\n"
                f"                            local -a profile_cmds\n"
                f"                            profile_cmds=(\n"
                f"{sub_str}\n"
                f"                            )\n"
                f"                            _describe 'profile command' profile_cmds\n"
                f"                            ;;\n"
                f"                    esac\n"
                f"                    ;;")
        else:
            sub_str = _zsh_describe_lines(info["subcommands"], " " * 20)
            safe = cmd.replace("-", "_")
            sub_cases.append(
                f"                {cmd})\n"
                f"                    local -a {safe}_cmds\n"
                f"                    {safe}_cmds=(\n"
                f"{sub_str}\n"
                f"                    )\n"
                f"                    _describe '{cmd} command' {safe}_cmds\n"
                f"                    ;;")
    sub_cases_str = "\n".join(sub_cases)
    return f"""#compdef {prog}
# Luna Agent zsh completion
# Add to ~/.zshrc:
#   eval "$({prog} completion zsh)"

_{ident}_profiles() {{
    local -a profiles
    local profiles_dir={_HOME_EXPR}/profiles
    profiles=(default)
    if [[ -d $profiles_dir ]]; then
        profiles+=($profiles_dir/*(N/:t))
    fi
    _describe 'profile' profiles
}}

_{ident}() {{
    local context state line
    typeset -A opt_args

    _arguments -C \\
        '(-)'{{-h,--help}}'[Show help and exit]' \\
        '(-)'{{-V,--version}}'[Show version and exit]' \\
        '(-)'{{-p,--profile}}'[Profile name]:profile:_{ident}_profiles' \\
        '1:command:->commands' \\
        '*::arg:->args'

    case $state in
        commands)
            local -a subcmds
            subcmds=(
{top_cmds_str}
            )
            _describe '{prog} command' subcmds
            ;;
        args)
            case ${{line[1]}} in
{sub_cases_str}
            esac
            ;;
    esac
}}

compdef _{ident} {prog}
"""


def generate_fish(parser: argparse.ArgumentParser) -> str:
    ident, prog = _sh_ident(parser.prog), _cmd_name(parser.prog)
    subcommands = _sorted_subcommands(parser)
    top_cmds_str = " ".join(cmd for cmd, _ in subcommands)
    lines: list[str] = [
        f"# {prog} fish completion",
        "# Add to your config:",
        f"#   {prog} completion fish | source",
        "",
        "# Helper: list available profiles",
        f"function __{ident}_profiles",
        "    echo default",
        f"    if test -d {_HOME_EXPR}/profiles",
        f"        for d in {_HOME_EXPR}/profiles/*/",
        "            basename $d",
        "        end",
        "    end",
        "end",
        "",
        "# Disable file completion by default",
        f"complete -c {prog} -f",
        "",
        "# Complete profile names after -p / --profile",
        f"complete -c {prog} -f -s p -l profile"
        f" -d 'Profile name' -xa '(__{ident}_profiles)'",
        "",
        "# Top-level subcommands"]
    for cmd, info in subcommands:
        lines.append(
            f"complete -c {prog} -f "
            f"-n 'not __fish_seen_subcommand_from {top_cmds_str}' "
            f"-a {cmd} -d '{_clean(info.get('help', ''))}'")
    lines += ["", "# Subcommand completions"]
    for cmd, info in subcommands:
        if not info["subcommands"]:
            continue
        lines.append(f"# {cmd}")
        for sc, sinfo in sorted(info["subcommands"].items()):
            lines.append(
                f"complete -c {prog} -f "
                f"-n '__fish_seen_subcommand_from {cmd}' "
                f"-a {sc} -d '{_clean(sinfo.get('help', ''))}'")
        if cmd == "profile":  # profile names for the actions that take one
            for action in sorted(_PROFILE_NAME_ACTIONS):
                lines.append(
                    f"complete -c {prog} -f "
                    f"-n '__fish_seen_subcommand_from {action}; "
                    f"and __fish_seen_subcommand_from profile' "
                    f"-a '(__{ident}_profiles)' -d 'Profile name'")
    lines.append("")
    return "\n".join(lines)
