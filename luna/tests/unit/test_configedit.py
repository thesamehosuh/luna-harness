"""Comment-preserving config editing (PRODUCT_PLAN P4): surgical key/block writes keep the
document's commentary and structure intact."""

from __future__ import annotations

import pytest

from luna_core.configedit import ConfigEditError, read_config_value, write_config_value

DOC = """\
# top comment
luna:
  # ambient block comment
  ambient:
    enabled: true
    dry_run: false
    jev:
      timeout_seconds: 20   # inline stays
      route: [zen-free]
      providers:
        zen-free:
          base_url: https://opencode.ai/zen/v1
          model: jev-1.13-free
  output:
    emoji_filter: true
    allowed_emoji: ["👍"]
display:
  skin: luna
skills:
  auto_load:
    - humanizer
"""


def test_scalar_replace_keeps_comments_and_structure():
    out = write_config_value(DOC, ["luna", "ambient", "dry_run"], True)
    assert "dry_run: true" in out
    assert "# top comment" in out and "# ambient block comment" in out
    assert "enabled: true" in out
    assert "timeout_seconds: 20   # inline stays" in out


def test_list_replace_renders_flow():
    out = write_config_value(DOC, ["luna", "output", "allowed_emoji"], ["👍", "😭"])
    assert 'allowed_emoji: ["👍", "😭"]' in out or "allowed_emoji: [👍, 😭]" in out or 'allowed_emoji: ["👍",' in out
    assert "# top comment" in out


def test_dict_block_replace_and_delete():
    out = write_config_value(DOC, ["luna", "ambient", "jev"], {
        "timeout_seconds": 30,
        "route": ["local"],
        "providers": {"local": {"base_url": "http://127.0.0.1:8700/v1", "model": "clm"}},
    })
    assert "timeout_seconds: 30" in out
    assert "zen-free" not in out  # old provider replaced wholesale
    assert "# top comment" in out and "# ambient block comment" in out

    removed = write_config_value(out, ["display", "skin"], None)
    assert "skin:" not in removed.split("display:")[-1]
    assert "display:" in removed


def test_creates_missing_leaf_inside_existing_block():
    out = write_config_value(DOC, ["luna", "output", "max_lines"], 6)
    assert "max_lines: 6" in out
    assert "emoji_filter: true" in out


def test_replaces_indentless_sequence_without_leaving_old_items():
    source = """\
telegram:
  allow_admin_from:
  - '1001'
  - '1002'
  group_allowed_chats:
  - '-1009'
"""
    out = write_config_value(source, ["telegram", "allow_admin_from"], ["2001"])
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["telegram"]["allow_admin_from"] == ["2001"]
    assert parsed["telegram"]["group_allowed_chats"] == ["-1009"]
    assert "1001" not in out and "1002" not in out


def test_deletes_indentless_sequence_without_consuming_sibling():
    source = """\
telegram:
  allow_admin_from:
  - '1001'
  group_allowed_chats:
  - '-1009'
"""
    out = write_config_value(source, ["telegram", "allow_admin_from"], None)
    import yaml
    parsed = yaml.safe_load(out)
    assert "allow_admin_from" not in parsed["telegram"]
    assert parsed["telegram"]["group_allowed_chats"] == ["-1009"]


def test_missing_parent_is_created_and_inline_refused():
    # missing parents are created as blocks now; an inline parent value is still refused
    out = write_config_value(DOC, ["luna", "brand", "new_key"], 1)
    assert "brand:" in out and "new_key: 1" in out
    with pytest.raises(ConfigEditError):
        write_config_value("luna: {x: 1}\n", ["luna", "y"], 1)


def test_invalid_result_is_refused(tmp_path):
    with pytest.raises(ConfigEditError):
        write_config_value(DOC, ["skills", "auto_load"], {1, 2})  # not YAML-representable
    try:
        write_config_value(DOC, ["skills", "auto_load"], {1, 2})
    except ConfigEditError as exc:
        assert "refusing" in str(exc)


def test_read_config_value_walks_nested():
    import yaml
    data = yaml.safe_load(DOC)
    assert read_config_value(data, ["luna", "ambient", "dry_run"]) is False
    assert read_config_value(data, ["luna", "missing", "x"]) is None
