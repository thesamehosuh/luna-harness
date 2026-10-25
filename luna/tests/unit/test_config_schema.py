"""Schema contributions for the companion knobs (PRODUCT_PLAN P2).

Contract: every scalar companion key in the shipped config template is a first-class schema
field — "a key that only exists in raw YAML is not done" (AGENTS.md §6).
"""

from __future__ import annotations

from pathlib import Path


from luna_cli import config_schema

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = REPO_ROOT / "luna" / "config" / "config.yaml.luna"

# Dynamic map keys (per-provider blocks) are not fixed schema fields; the Behaviour page
# edits the route list and the raw YAML covers the rest until P4's route editor lands.
_DYNAMIC_PREFIXES = ("luna.ambient.jev.providers.",)

COVERED_ROOTS = ("luna.", "honcho.", "display.platforms.telegram_group.", "telegram.")


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for key, sub in value.items():
            out.update(_flatten(sub, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: value}


def _template_leaf_keys():
    import yaml

    doc = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    leaves = _flatten(doc)
    return {
        key for key in leaves
        if key.startswith(COVERED_ROOTS) and not key.startswith(_DYNAMIC_PREFIXES)
    }


def test_every_template_companion_key_has_a_schema_field():
    fields = config_schema.LUNA_SCHEMA_FIELDS
    missing = sorted(k for k in _template_leaf_keys() if k not in fields)
    assert not missing, (
        "companion config keys with no dashboard schema field (raw-YAML only): "
        f"{missing}"
    )


def test_fields_are_wellformed():
    for key, entry in config_schema.LUNA_SCHEMA_FIELDS.items():
        assert entry.get("type"), key
        assert entry.get("description"), key
        assert entry.get("category"), key
        if entry["type"] == "number":
            assert entry.get("min") is not None and entry.get("max") is not None, key
            assert entry["min"] < entry["max"], key
        if entry["type"] == "select":
            assert entry.get("options"), key


def test_threshold_fields_track_cascade_defaults():
    from luna_core.cascade import CascadeConfig

    entry = config_schema.LUNA_SCHEMA_FIELDS["luna.ambient.thresholds.message_min_value"]
    assert entry["default"] == CascadeConfig().message_min_value
    generated = [k for k in config_schema.LUNA_SCHEMA_FIELDS if k.startswith("luna.ambient.thresholds.")]
    assert len(generated) >= 25


def test_categories_are_tabs_the_dashboard_can_render():
    categories = {e["category"] for e in config_schema.LUNA_SCHEMA_FIELDS.values()}
    assert categories <= {"companion", "memory", "display"}
    assert "companion" in config_schema.LUNA_CATEGORY_ORDER


def test_schema_survives_without_luna_core(monkeypatch):
    """A missing overlay lib must degrade to static fields, not crash the config schema."""
    import sys

    monkeypatch.setitem(sys.modules, "luna_core.cascade", None)
    assert config_schema._threshold_fields() == {}
    assert "luna.ambient.enabled" in config_schema._STATIC


def test_observe_unmentioned_group_messages_has_a_schema_field():
    """The observe switch ships ON and is the widest thing Luna stores, so it must be visible and
    changeable in the dashboard.

    Pinned individually rather than by widening ``COVERED_ROOTS`` to ``telegram.``: that root also
    contains ten further template keys with no schema field (``allow_admin_from``,
    ``group_allowed_chats``, ``require_mention``, ...), which is a real AGENTS.md §6 gap but a
    separate piece of work — widening the root here would turn a passing contract red for
    unrelated reasons.
    """
    from luna_cli.config_schema import LUNA_SCHEMA_FIELDS

    field = LUNA_SCHEMA_FIELDS.get("telegram.observe_unmentioned_group_messages")
    assert field is not None, "the observe switch is raw-YAML only"
    assert field["type"] == "boolean"
    # The description must state the cost of turning it off, not just what it does.
    assert "chime" in field["description"].lower()
