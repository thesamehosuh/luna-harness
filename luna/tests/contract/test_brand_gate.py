"""The P0 brand gate: no user-visible engine copy in the dashboard's own surfaces.

The dashboard source, locale catalogs, routers and their copy-producing backend helpers must contain
only contract/comment hits, each with a reason. The helpers matter too: channel descriptions and
OAuth instructions render in React even though their copy lives outside the routers.

Three kinds of hit are legitimately exempt, and each has to say so:

* **A symbol or wire contract.** ``HermesConsoleEngine`` is the name the vendored
  ``hermes_cli.console_engine`` exports and the dashboard dispatches into; renaming it would fork a
  vendored API for no user-visible gain. ``X-Hermes-Session-Token`` is a header name the SPA and the
  server both spell.
* **A named third-party product.** "Hermes Cloud" is someone else's product, not ours to rename.
* **An explanatory comment.** Comments that quote the old copy to say why it is gone, or that record
  a decision, are the point of a comment.

What is *not* exempt is anything a user reads: headers, error messages, HTML pages, prompts, and
platform labels all shipped saying "Hermes" while the product is Luna.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Keep in step with the expanded P0 scope recorded in POLISH_PLAN.
GATE_PATHS = (
    "web/src", "locales", "hermes_cli/web_routers",
    "hermes_cli/web_server_messaging.py",
    "hermes_cli/web_server_oauth.py",
    "hermes_cli/web_server_config.py",
    "hermes_cli/web_server_dashboard.py",
    "hermes_cli/web_server_lifecycle.py",
)

# `Hermes` as a word, bounded on Latin characters so it does not swallow a longer identifier.
BRAND = re.compile(r"\bHermes(?![A-Za-z0-9_])")

# Phrases that are contracts or third-party proper nouns, with the reason each one is exempt.
# A hit matching one of these is allowed; everything else must carry a stated reason nearby.
EXEMPT_PHRASES: dict[str, str] = {
    "HermesConsoleEngine": "vendored engine class name in hermes_cli.console_engine",
    "X-Hermes-Session-Token": "wire contract: the SPA and the server both spell this header",
    "delete-from-Hermes": "names the engine's own local-models store, not product copy",
    # Quoted only to explain the fix: the backend's old label, and the label a *test* feeds the merge
    # to prove the client ignores a server-supplied one. Never rendered -- the client asserts
    # `not.toBe("Hermes Teal")`, which is the whole point of the fixture.
    "Hermes Teal": "quoted history: the removed backend label, and the fixture proving it is ignored",
    "Hermes Relay": "third-party connector product name, not Luna's product identity",
    # Exact old updater phrases are inputs to a translation table, never rendered unchanged.
    "Hermes Agent runs as a published image": "legacy engine updater copy translated to Luna",
    "Update Hermes through": "legacy engine updater copy translated to Luna",
    "this Hermes installation": "legacy engine updater copy translated to Luna",
    "managed by Hermes": "legacy engine updater copy translated to Luna",
    "reinstall Hermes": "legacy engine updater copy translated to Luna",
}

# A comment line that names the engine in order to explain the decision. Recognised structurally so
# the exemption cannot be used to smuggle user-visible copy past the gate.
REASON_MARKERS = (
    "deliberate",
    "contract",
    "engine",
    "vendored",
    "third-party",
    "not rebranded",
    "the point of a comment",
    "what let the backend",
)


def _gate_files() -> list[Path]:
    files: list[Path] = []
    for rel in GATE_PATHS:
        root = REPO_ROOT / rel
        if root.is_dir():
            files += [p for p in root.rglob("*") if p.suffix in {".py", ".ts", ".tsx", ".yaml", ".css", ".json", ".html", ".svg"}]
        elif root.is_file():
            files.append(root)
    # `locales` is matched as a glob of *.yaml by the gate command, not as a recursive dir walk.
    files = [p for p in files if p.is_file()]
    assert files, "gate scope resolved to no files -- the paths above are wrong"
    return sorted(files)


def _looks_like_comment_or_docstring(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(("#", "*", '"""', "'''", "//", "/*"))


def _stated_reason(line: str, context: str) -> bool:
    """Does this line, or its immediate docstring/comment block, say why the name stays?"""
    haystack = f"{line}\n{context}".lower()
    return any(marker in haystack for marker in REASON_MARKERS)


def test_no_unexempt_hermes_brand_in_the_gate_scope():
    """Every remaining hit is a contract, a third-party name, or a comment that says why."""
    unexempt: list[str] = []
    for path in _gate_files():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            if not BRAND.search(line):
                continue
            if any(phrase in line for phrase in EXEMPT_PHRASES):
                continue
            rel = path.relative_to(REPO_ROOT)
            # A hit inside a string literal that the reader sees is never exempt, whatever the
            # surrounding comment says -- so require it to be comment-shaped first.
            if _looks_like_comment_or_docstring(line) and _stated_reason(
                line, "\n".join(lines[max(0, lineno - 6) : lineno + 2])
            ):
                continue
            unexempt.append(f"{rel}:{lineno}: {line.strip()}")

    assert not unexempt, (
        "unexplained engine brand in the P0 gate scope. Either rebrand it, or -- if it is a "
        "contract, a third-party name, or a comment recording why the old copy is gone -- say so "
        "at the mention:\n" + "\n".join(unexempt)
    )


def test_the_exemptions_are_all_still_referenced():
    """If a name in EXEMPT_PHRASES stops appearing, delete it instead of letting it rot.

    An exemption list that only grows is how a gate quietly stops meaning anything: the name is
    renamed, the exemption stays, and the next genuine leak is waved through under a rule written
    for something that no longer exists.
    """
    haystack = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in _gate_files()
        if p.is_file()
    )
    stale = [
        phrase for phrase in EXEMPT_PHRASES if phrase not in haystack
        # X-Hermes-Session-Token lives in web_server.py, outside the gate scope, so it is checked
        # directly rather than through the scope walk.
        and phrase not in (REPO_ROOT / "hermes_cli" / "web_server.py").read_text(encoding="utf-8")
    ]
    assert not stale, f"EXEMPT_PHRASES entries no longer referenced anywhere: {stale}"


def test_gate_scope_resolves_to_the_expected_files():
    """Guard the guard: if these paths stop existing, the other tests pass on nothing."""
    files = _gate_files()
    rels = [str(p.relative_to(REPO_ROOT)) for p in files]
    prefixes = {"/".join(r.split("/")[:2]) if r.startswith(("web/", "hermes_cli/")) else r.split("/")[0]
                for r in rels}
    assert prefixes == set(GATE_PATHS), f"gate scope resolved to {sorted(prefixes)}"
    assert len([r for r in rels if r.startswith("locales/")]) == 17, "expected all 17 locale catalogs"
    assert any(r.startswith("web/src/") for r in rels), "web/src contributed no files"
