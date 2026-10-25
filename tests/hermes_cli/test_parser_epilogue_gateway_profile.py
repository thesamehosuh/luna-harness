"""The ``--help`` epilogue must cover the profile-scoped gateway lifecycle.

``-p/--profile`` is consumed before argparse (``main._apply_profile_override``), so it never
appears among the parser's option rows — the epilogue examples are the only place ``--help``
can teach the ``<prog> -p <profile> gateway <action>`` form that generated service units and
user-facing copy already rely on. Contract, not snapshot: assert the verbs and the profile flag
are named in the RENDERED help (the wiring, not just the constant), not the exact wording.

Asserted against ``parser.prog`` rather than a literal brand. The examples used to say ``hermes``
while the usage line said ``luna``, so `luna --help` advertised commands under a name that did not
exist -- and this test passed anyway, because it was asserting the stale half of the drift. Pinning
to ``prog`` makes it fail on the next disagreement instead.
"""

from hermes_cli._parser import PRE_ARGPARSE_INHERITED_FLAGS, build_top_level_parser


def _rendered_help() -> tuple[str, str]:
    """(help text, prog) so assertions can name the command without hardcoding a brand."""
    parser = build_top_level_parser()[0]
    return parser.format_help(), parser.prog


def test_rendered_help_documents_the_profile_scoped_command_form():
    help_text, prog = _rendered_help()
    assert f"{prog} -p <profile>" in help_text
    assert "--profile" in help_text
    assert f"{prog} -p coder gateway stop" in help_text
    # The flag stays pre-argparse: documented in the epilogue, never registered as an option.
    assert ("-p", True) in PRE_ARGPARSE_INHERITED_FLAGS
    assert "-p PROFILE" not in help_text and "--profile PROFILE" not in help_text


def test_rendered_help_documents_the_gateway_service_verbs():
    help_text, prog = _rendered_help()
    for verb in ("install", "start", "stop", "status"):
        assert f"{prog} gateway {verb}" in help_text, verb


def test_epilogue_agrees_with_the_usage_line():
    """The examples must name the same command as the usage line above them.

    The failure this exists to catch is subtle: a stale literal still renders, still lists every
    subcommand, and still satisfies every behavioural assertion in this file. Only comparing the
    two against each other catches it.
    """
    help_text, prog = _rendered_help()
    assert f"usage: {prog}" in help_text
    for line in help_text.split("Examples:")[1].splitlines():
        stripped = line.strip()
        if not stripped.startswith(prog):
            continue
        # A profile label is user data, not a command: `luna -s hermes-agent-dev` is correct.
        assert stripped.split()[0] == prog
