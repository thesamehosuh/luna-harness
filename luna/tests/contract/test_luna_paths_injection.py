"""The SPA's Luna paths are injected server-side, and no JSX literal competes with them.

`web/src/lib/luna-paths.ts` exists so the dashboard can never name a Luna path from a hard-coded
string: `EnvPage` used to render `~/.hermes/.env` while the backend was serving the real path two
requests away, so the page pointed at the engine's home on a Luna install. The helper reads
`window.__LUNA_BRAND__`, which `mount_spa` injects into index.html using the *same* resolver the
`luna` CLI uses for its own home — so the dashboard and the terminal cannot disagree.

Server-injected rather than fetched on purpose: these strings render on first paint, and a fetch
would mean showing a fallback and then correcting it — the same wrong-first-paint problem
``_render_active_theme_bootstrap_css`` exists to solve.

Two failure modes are pinned here:

* the injection stops happening or stops escaping ``</``, and
* a caller goes back to typing a path literal in JSX, which re-creates the original drift.
"""

from __future__ import annotations

import json
import re

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_SRC = REPO_ROOT / "web" / "src"



# --- the injection ---------------------------------------------------------------


def _brand_js() -> str:
    from hermes_cli.web_server_dashboard import _render_brand_js

    return _render_brand_js()


def test_brand_js_assigns_the_global_the_helper_reads():
    js = _brand_js()
    assert js.startswith("window.__LUNA_BRAND__=")
    assert js.endswith(";")


def test_brand_payload_round_trips():
    """Extract the JSON literal and check it is valid JSON with the keys the helper needs."""
    js = _brand_js()
    payload = js[len("window.__LUNA_BRAND__=") : -1]
    data = json.loads(payload)
    assert set(data) == {
        "home",
        "bin",
        "consolePrompt",
        "updateCommand",
        "dashboardCommand",
        "docsUrl",
    }
    assert data["bin"] == "luna"
    assert data["consolePrompt"] == "luna> "


def test_brand_home_matches_the_cli_resolver(monkeypatch, tmp_path):
    """The dashboard and the `luna` CLI must resolve the same directory.

    This is the actual invariant behind the helper: if these two ever disagree, the dashboard names
    a directory the terminal does not read, which is the bug the helper was introduced to stop.
    """
    from hermes_cli.web_server_dashboard import _luna_home
    from luna_cli.main import luna_home

    # Checked under an override as well as by default, because the two can only be compared
    # meaningfully once the env actually decides the answer.
    for env in (None, str(tmp_path / "profile")):
        if env is None:
            monkeypatch.delenv("LUNA_HOME", raising=False)
        else:
            monkeypatch.setenv("LUNA_HOME", env)
        assert _luna_home() == luna_home(), (
            "the dashboard and the CLI resolve the Luna home differently, so the dashboard can "
            "name a directory the terminal does not read"
        )


def test_brand_home_follows_the_env_var_chain(monkeypatch, tmp_path):
    from hermes_cli.web_server_dashboard import _luna_home

    target = tmp_path / "elsewhere"
    monkeypatch.setenv("LUNA_HOME", str(target))
    assert _luna_home() == str(target)


def test_brand_js_escapes_a_script_tag_breakout(monkeypatch):
    """A home path containing ``</`` must not be able to close the surrounding script tag.

    The same escaping the session-token and initial-profile injections use. ``LUNA_HOME`` is
    operator-supplied, so it is untrusted input to this template — and the payload is written into
    the HTML the dashboard serves from.
    """
    monkeypatch.setenv("LUNA_HOME", "/tmp/x</script><img src=x onerror=alert(1)>")
    js = _brand_js()
    payload = js[len("window.__LUNA_BRAND__=") : -1]

    # The breakout is neutralised: no raw `</` survives to close the tag...
    assert "</" not in payload
    # ...and it is still a valid JSON string, so the value is not silently mangled either.
    data = json.loads(payload)
    assert "</script>" in data["home"]


def test_spa_index_injection_carries_the_brand():
    """``mount_spa`` must actually include it in the bootstrap script it injects before </head>."""
    source = (REPO_ROOT / "hermes_cli" / "web_server_dashboard.py").read_text(encoding="utf-8")
    assert "_render_brand_js()" in source, (
        "mount_spa no longer injects the brand; the SPA would fall back to its hard-coded defaults"
    )


# --- no JSX literal competes with the helper -------------------------------------


def _tsx_files() -> list[Path]:
    """Product surface only.

    Test fixtures are excluded deliberately: several of them *accurately* echo backend strings that
    still say `hermes` (e.g. `gateway_start_command`, `cli_command`). Fixing a fixture before the
    router that produces the value would make the test lie, so those are audited where the strings
    actually originate — the backend router copy, P0 item 6 — not here.
    """
    return sorted(
        p
        for p in WEB_SRC.rglob("*.tsx")
        if not p.name.endswith((".test.tsx", ".spec.tsx"))
    )


def _is_comment(line: str) -> bool:
    """Comment lines may name the old paths deliberately, to explain what changed and why."""
    stripped = line.strip()
    return stripped.startswith(("*", "//", "/*"))


# `~/.hermes` anywhere — including bare JSX text (`<code>~/.hermes/.env</code>`), which is how
# EnvPage actually carried it. A quoted-literal-only pattern misses that entirely, and a guard that
# cannot see the real case is worse than no guard.
_HERMES_PATH = re.compile(r"~/\.hermes")

# A quoted string that *starts* with the `hermes` binary: `"hermes> "`, `"hermes update"`,
# `` `hermes dashboard` ``. Anchoring on the opening quote keeps engine identifiers out of scope
# (`can_update_hermes`, `hermes_version`, `hermes_cli.web_server_dashboard`).
_HERMES_COMMAND = re.compile(r"""["'`]hermes(?=>|\s)""")

# Known-safe quoted strings: the session-token header name (a wire contract with the engine),
# localStorage keys, and internal DOM ids. These never render as a path or a command.
_ALLOWED = (
    "hermes-console-title",
    "hermes-dashboard-theme",
    "hermes-dashboard-font",
    "X-Hermes-Session-Token",
)


def test_no_tsx_types_a_hermes_path_or_command_literal():
    """The guard that keeps `luna-paths.ts` the single source.

    Deliberately narrow about *what counts*: a `.tsx` source may still contain `hermes` in a comment
    explaining the history, in the engine's session-token header (a wire contract), in a
    localStorage key, or in an internal DOM id. None of those render, and banning them would make the
    guard cry wolf until someone disabled it.
    """
    offenders: list[str] = []
    for path in _tsx_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _is_comment(line):
                continue
            if any(allowed in line for allowed in _ALLOWED):
                continue
            if _HERMES_PATH.search(line) or _HERMES_COMMAND.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "hard-coded engine path/command in JSX; use lunaHomePath()/lunaCommand() from "
        "@/lib/luna-paths:\n" + "\n".join(offenders)
    )


# --- luna.docs.url ------------------------------------------------------------------


def _docs_home(monkeypatch, value):
    """Point HERMES_HOME at a scratch config.yaml holding ``luna.docs.url: <value>``."""
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp())
    rendered = "" if value is None else (
        '"%s"' % value if isinstance(value, str) and "\n" in value else value
    )
    (root / "config.yaml").write_text(f"luna:\n  docs:\n    url: {rendered}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))
    return root


def test_docs_url_defaults_to_empty(monkeypatch):
    """The default is empty, so the Docs page falls back to the in-dashboard /help.

    The old default pointed the whole Docs surface at a third-party site, which rendered as though
    that site documented Luna. Empty is the honest default; an operator opts in.
    """
    _docs_home(monkeypatch, "")
    from hermes_cli.web_server_dashboard import _luna_docs_url

    assert _luna_docs_url() == ""


def test_docs_url_is_served_when_set(monkeypatch):
    _docs_home(monkeypatch, "https://example.invalid/docs")
    from hermes_cli.web_server_dashboard import _luna_docs_url, _render_brand_js

    assert _luna_docs_url() == "https://example.invalid/docs"
    assert json.loads(_render_brand_js().split("=", 1)[1][:-1])["docsUrl"] == "https://example.invalid/docs"


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",       # would execute as an iframe src
        "data:text/html,<script>",  # same, other scheme
        "file:///etc/passwd",        # not a web URL at all
        "   ",                      # whitespace is not a URL
    ],
)
def test_non_http_docs_urls_are_refused(monkeypatch, value):
    """Only http(s) is honoured, because the value lands in an iframe ``src``.

    The key is operator-facing config, which is not a place to assume inert: an iframe whose src is
    ``javascript:`` is a script-injection vector in the dashboard's own origin.
    """
    _docs_home(monkeypatch, value)
    from hermes_cli.web_server_dashboard import _luna_docs_url

    assert _luna_docs_url() == ""


def test_non_string_docs_url_is_refused(monkeypatch):
    """A stray YAML scalar (a bool, a dict) must not become a string on the way to the page."""
    _docs_home(monkeypatch, "true")
    from hermes_cli.web_server_dashboard import _luna_docs_url

    assert _luna_docs_url() == ""


def test_docs_url_is_escaped_in_the_brand_payload(monkeypatch):
    """Even though only http(s) is honoured, the payload is still ``</``-escaped.

    Defence in depth rather than belt-and-braces: the escaping is applied to the whole payload, so
    relaxing this later cannot silently reintroduce the breakout for a value that is only validated
    at the wrong layer.
    """
    _docs_home(monkeypatch, "https://example.invalid/</script><img src=x>")
    from hermes_cli.web_server_dashboard import _render_brand_js

    js = _render_brand_js()
    payload = js[len("window.__LUNA_BRAND__=") : -1]
    assert "</" not in payload
    assert "</script>" in json.loads(payload)["docsUrl"]
