"""``GET /api/dashboard/themes`` — built-ins are ids only; ``presets.ts`` owns the labels.

The backend used to ship a label and a description alongside every built-in id. Those copies drifted
from the frontend's: the API said "Hermes Teal" while the picker said "Luna Teal", so the shipped
dashboard contradicted itself depending on which surface rendered the name. The response now carries
ids alone, and this module pins that contract from the backend side:

* the built-in entries have no ``label``/``description`` keys at all, and
* ``_BUILTIN_THEME_IDS`` is exactly the id set in ``web/src/themes/builtin-theme-ids.json``, which
  ``web/src/themes/presets.test.ts`` asserts equals ``BUILTIN_THEMES``. Neither language reads the
  other's source (web/AGENTS.md forbids Python tests asserting on ``.tsx``); the shared manifest makes
  the two id sets equal by transitivity.

This lives in the contract tier rather than ``tests/hermes_cli/`` on purpose: that tree needs the full
upstream runtime (``rich``, ``prompt_toolkit``, ``kawaii`` are absent from ``.venv``) so 118 of its
modules cannot even collect here, and ``scripts/test.sh`` skips it as upstream CI's business. A
contract nothing runs is not a contract.

User themes are deliberately different: their labels come from the user's own YAML, so the server
still serves them verbatim.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

REPO_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = REPO_ROOT / "web" / "src" / "themes" / "builtin-theme-ids.json"


def _manifest_ids() -> list[str]:
    return list(json.loads(_MANIFEST.read_text(encoding="utf-8"))["ids"])


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Point HERMES_HOME (and LUNA_HOME) at a scratch dir so theme discovery reads nothing real."""
    root = tmp_path / "luna-home"
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("LUNA_HOME", str(root))
    (root / "config.yaml").write_text("dashboard:\n  theme: default\n", encoding="utf-8")
    return root


def _get_themes() -> dict:
    from hermes_cli.web_routers.dashboard_ui import get_dashboard_themes

    return asyncio.run(get_dashboard_themes())


# --- the cross-language contract -------------------------------------------------


def test_builtin_theme_ids_match_the_shared_manifest():
    """The ids the backend reserves must be the ids the frontend ships — no more, no fewer.

    Transitive: ``presets.test.ts`` asserts ``Object.keys(BUILTIN_THEMES)`` equals this manifest, and
    this asserts the Python tuple equals it. A preset added to the frontend without recording its id
    fails the JS test; an id added here without a matching preset fails this one.
    """
    from hermes_cli.web_server_dashboard import _BUILTIN_THEME_IDS

    assert sorted(_BUILTIN_THEME_IDS) == sorted(_manifest_ids())


def test_builtin_theme_ids_have_no_duplicates():
    from hermes_cli.web_server_dashboard import _BUILTIN_THEME_IDS

    assert len(set(_BUILTIN_THEME_IDS)) == len(_BUILTIN_THEME_IDS)


def test_backend_carries_no_theme_label_table():
    """Source-level: no *module-level* ``{name, label, …}`` table survives in the backend.

    The behavioural tests above would still pass if someone re-added a *matching* label — the drift
    only becomes visible on the next rename, which is exactly how the original bug survived. So check
    the structure too: the old built-in table was a module-level list of dicts carrying ``name`` and
    ``label``, and a re-vendor that restores it fails here rather than shipping two names for one
    theme.

    Scoped to module level and to ``ast`` on purpose. Inside a function, ``name`` + ``label`` is
    legitimate and necessary — ``_normalise_theme_definition()`` builds exactly that for a *user*
    theme, whose label comes from the user's own YAML. Only a module-level table would be a second
    authority. Parsing rather than grepping also means comments and docstrings (which quote the old
    labels to explain why they are gone) cannot trip it.
    """
    import ast

    for rel in ("hermes_cli/web_server_dashboard.py", "hermes_cli/web_routers/dashboard_ui.py"):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in tree.body:
            targets = [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
            if not targets:
                continue
            for literal in [n for n in ast.walk(node) if isinstance(n, ast.Dict)]:
                keys = {k.value for k in literal.keys if isinstance(k, ast.Constant)}
                if "name" in keys and ("label" in keys or "description" in keys):
                    raise AssertionError(
                        f"{rel}:{literal.lineno} assigns {targets[0]} to a table whose entries "
                        f"carry both 'name' and {sorted(keys & {'label', 'description'})}. That is "
                        f"the label-bearing built-in theme table. presets.ts is the single label "
                        f"authority — the backend serves built-in ids only. (Building a user "
                        f"theme's dict inside a function is fine; that is not a module-level table.)"
                    )


def test_builtin_id_tuple_is_ids_only():
    """Structural counterpart on the theme module: the built-in list is a tuple of plain strings.

    Catches the reintroduction in the other direction — a tuple of ``{"name": ...}`` dicts, which
    would look structurally fine to a caller but invite someone to add a label back.
    """
    import ast

    source = (REPO_ROOT / "hermes_cli" / "web_server_dashboard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = False
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "_BUILTIN_THEME_IDS" not in targets:
            continue
        found = True
        value = node.value
        assert isinstance(value, ast.Tuple), "_BUILTIN_THEME_IDS must be a tuple literal of ids"
        for element in value.elts:
            assert isinstance(element, ast.Constant) and isinstance(element.value, str), (
                "every entry must be a bare id string, not a dict or a computed value"
            )
    assert found, "_BUILTIN_THEME_IDS is missing from hermes_cli/web_server_dashboard.py"


def test_the_old_label_bearing_symbol_is_gone():
    """Name-level check, so a revert that re-adds the upstream symbol fails loudly and specifically."""
    for rel in ("hermes_cli/web_server_dashboard.py", "hermes_cli/web_routers/dashboard_ui.py"):
        assert "_BUILTIN_DASHBOARD_THEMES" not in (REPO_ROOT / rel).read_text(encoding="utf-8"), (
            f"{rel} references _BUILTIN_DASHBOARD_THEMES again. That symbol carried a second copy "
            f"of every theme label. Use _BUILTIN_THEME_IDS (ids only)."
        )


# --- the response shape ----------------------------------------------------------


def test_built_ins_are_served_as_ids_only(home):
    """No ``label``/``description`` key on a built-in — not even a matching one.

    The check is on *key presence*, not on value, because a matching value still leaves a second copy
    to drift on the next rename. Absence is the only state that cannot lie.
    """
    data = _get_themes()
    builtin_ids = set(_manifest_ids())
    builtins = [t for t in data["themes"] if t["name"] in builtin_ids]

    assert len(builtins) == len(builtin_ids), "every manifest id must appear in the response"
    for entry in builtins:
        assert set(entry) == {"name"}, f"built-in {entry['name']} shipped more than its id: {entry}"


def test_active_migrates_the_retired_default_without_writing(home):
    before = (home / "config.yaml").read_bytes()
    assert _get_themes()["active"] == "sakura-dusk"
    assert (home / "config.yaml").read_bytes() == before


def test_active_reads_the_persisted_theme(home):
    (home / "config.yaml").write_text("dashboard:\n  theme: sakura-day\n", encoding="utf-8")
    assert _get_themes()["active"] == "sakura-day"


# --- user themes keep their own labels -------------------------------------------


def _write_user_theme(home: Path, name: str, label: str, description: str) -> None:
    d = home / "dashboard-themes"
    d.mkdir(exist_ok=True)
    (d / f"{name}.yaml").write_text(
        f"name: {name}\n"
        f"label: {label}\n"
        f"description: {description}\n"
        "palette:\n"
        "  background: '#101010'\n"
        "  midground: '#e0e0e0'\n",
        encoding="utf-8",
    )


def test_user_theme_keeps_its_label_description_and_definition(home):
    _write_user_theme(home, "mine", "My Theme", "hand-rolled")
    entry = next(t for t in _get_themes()["themes"] if t["name"] == "mine")

    assert entry["label"] == "My Theme"
    assert entry["description"] == "hand-rolled"
    # The definition rides along so the client applies the theme without a second round-trip.
    assert entry["definition"]["palette"]["background"]["hex"] == "#101010"


def test_user_theme_cannot_shadow_a_built_in(home):
    """A YAML named after a built-in is dropped.

    The client resolves ``BUILTIN_THEMES`` first, so serving the shadowing entry would show a picker
    row that does nothing when clicked. Dropping it here keeps the list honest in one place rather
    than making the client filter.
    """
    _write_user_theme(home, "sakura-dusk", "Impostor", "should never be served")
    names = [t["name"] for t in _get_themes()["themes"]]

    assert names.count("sakura-dusk") == 1
    assert not any(t.get("label") == "Impostor" for t in _get_themes()["themes"])


def test_user_theme_ordering_does_not_disturb_the_builtins(home):
    _write_user_theme(home, "zzz", "Last", "sorted last")
    names = [t["name"] for t in _get_themes()["themes"]]

    assert names[: len(_manifest_ids())] == _manifest_ids()
    assert names[-1] == "zzz"


# --- the first-paint bootstrap ---------------------------------------------------


@pytest.mark.parametrize("name,canvas,accent", [("sakura-dusk", "#17132b", "#eeafce"),
                                               ("sakura-day", "#fbf0f8", "#a65370"),
                                               ("mono", "#0e0e0e", "#eaeaea")])
def test_bootstrap_css_preserves_the_configured_builtin_first_paint(home, name, canvas, accent):
    """A new desktop port has no browser cache; its first paint must match the profile."""
    from hermes_cli.web_server_dashboard import _render_active_theme_bootstrap_css
    (home / "config.yaml").write_text(f"dashboard:\n  theme: {name}\n", encoding="utf-8")
    css = _render_active_theme_bootstrap_css()
    assert f"--background-base:{canvas}" in css
    assert f"--color-primary:{accent}" in css


def test_bootstrap_css_renders_a_user_theme(home):
    """The shim is the only thing stopping a wrong first paint on a user theme — keep it working."""
    from hermes_cli.web_server_dashboard import _render_active_theme_bootstrap_css

    _write_user_theme(home, "mine", "My Theme", "hand-rolled")
    (home / "config.yaml").write_text("dashboard:\n  theme: mine\n", encoding="utf-8")

    css = _render_active_theme_bootstrap_css()
    assert "#101010" in css
    # Exactly one real closing tag, and no escaped one: a palette value carrying `</style>` is
    # escaped to `<\/style>`, so it neither opens a second tag nor leaks an unescaped sequence.
    assert css.count("</style>") == 1
    assert "<\\/style>" not in css


# --- Sakura preset migration and config defaults -----------------------------------


def test_dashboard_theme_config_defaults_and_schema_offer_only_current_presets():
    import yaml

    from hermes_cli.config_defaults import DEFAULT_CONFIG
    from hermes_cli.web_server_config import CONFIG_SCHEMA

    assert DEFAULT_CONFIG["dashboard"]["theme"] == "sakura-dusk"
    template = yaml.safe_load((REPO_ROOT / "luna/config/config.yaml.luna").read_text())
    assert template["dashboard"]["theme"] == DEFAULT_CONFIG["dashboard"]["theme"]
    assert CONFIG_SCHEMA["dashboard.theme"]["options"] == ["sakura-dusk", "sakura-day", "mono"]


def test_theme_list_defaults_to_sakura_dusk(monkeypatch):
    import hermes_cli.web_routers.dashboard_ui as dashboard_ui

    monkeypatch.setattr(dashboard_ui, "load_config", lambda: {})
    monkeypatch.setattr(dashboard_ui, "_discover_user_themes", lambda: [])

    result = asyncio.run(dashboard_ui.get_dashboard_themes())

    assert result["active"] == "sakura-dusk"
    assert [theme["name"] for theme in result["themes"]] == ["sakura-dusk", "sakura-day", "mono"]
    assert all(set(theme) == {"name"} for theme in result["themes"])


def test_theme_list_canonicalizes_legacy_preference_but_keeps_custom_collision(monkeypatch):
    import hermes_cli.web_routers.dashboard_ui as dashboard_ui

    monkeypatch.setattr(dashboard_ui, "load_config", lambda: {"dashboard": {"theme": "midnight"}})
    monkeypatch.setattr(dashboard_ui, "_discover_user_themes", lambda: [])
    assert asyncio.run(dashboard_ui.get_dashboard_themes())["active"] == "sakura-dusk"

    custom_rose = {"name": "rose", "label": "My Rosé", "description": "custom", "palette": {}}
    monkeypatch.setattr(dashboard_ui, "load_config", lambda: {"dashboard": {"theme": "rose"}})
    monkeypatch.setattr(dashboard_ui, "_discover_user_themes", lambda: [custom_rose])
    result = asyncio.run(dashboard_ui.get_dashboard_themes())
    assert result["active"] == "rose"
    assert next(theme for theme in result["themes"] if theme["name"] == "rose")["label"] == "My Rosé"


def test_legacy_theme_put_migrates_but_custom_legacy_name_wins(monkeypatch):
    import hermes_cli.web_routers.dashboard_ui as dashboard_ui
    from hermes_cli.web_models import ThemeSetBody

    persisted = []
    monkeypatch.setattr(dashboard_ui, "_set_dashboard_key", lambda key, value: persisted.append((key, value)))
    monkeypatch.setattr(dashboard_ui, "_discover_user_themes", lambda: [])
    result = asyncio.run(dashboard_ui.set_dashboard_theme(ThemeSetBody(name="default")))
    assert result == {"ok": True, "theme": "sakura-dusk"}
    assert persisted[-1] == ("theme", "sakura-dusk")

    monkeypatch.setattr(dashboard_ui, "_discover_user_themes", lambda: [{"name": "rose"}])
    result = asyncio.run(dashboard_ui.set_dashboard_theme(ThemeSetBody(name="rose")))
    assert result == {"ok": True, "theme": "rose"}
    assert persisted[-1] == ("theme", "rose")


def test_user_theme_color_scheme_is_normalized_and_bootstrapped(tmp_path, monkeypatch):
    from hermes_cli import web_server_dashboard as themes

    light = themes._normalise_theme_definition({"name": "paper", "colorScheme": "light"})
    invalid = themes._normalise_theme_definition({"name": "odd", "colorScheme": "neon"})
    absent = themes._normalise_theme_definition({"name": "plain"})
    assert light["colorScheme"] == "light"
    assert invalid["colorScheme"] == absent["colorScheme"] == "dark"

    (tmp_path / "dashboard-themes").mkdir()
    (tmp_path / "dashboard-themes" / "paper.yaml").write_text(
        "name: paper\ncolorScheme: light\npalette:\n  background: '#ffffff'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda: {"dashboard": {"theme": "paper"}})
    css = themes._render_active_theme_bootstrap_css()
    assert "color-scheme:light;" in css
    assert "--background-base:#ffffff;" in css


def test_legacy_builtin_bootstrap_resolves_to_sakura_without_hiding_custom_theme(tmp_path, monkeypatch):
    from hermes_cli import web_server_dashboard as themes
    from hermes_cli import config as config_module

    themes_dir = tmp_path / "dashboard-themes"
    themes_dir.mkdir()
    (themes_dir / "custom-rose.yaml").write_text("name: rose\ncolorScheme: light\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    monkeypatch.setattr(config_module, "load_config", lambda: {"dashboard": {"theme": "rose"}})
    assert "color-scheme:light;" in themes._render_active_theme_bootstrap_css()

    (themes_dir / "custom-rose.yaml").unlink()
    css = themes._render_active_theme_bootstrap_css()
    assert "--background-base:#17132b" in css and "color-scheme:dark" in css
