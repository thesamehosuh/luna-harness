"""Comment-preserving config.yaml editing (PRODUCT_PLAN P4).

The dashboard writes shaping knobs (``luna.output.*``, ``display.skin``, ``skills.auto_load``,
``luna.ambient.*``) as surgical key/block replacements so the template's commentary survives —
the same contract the threshold writer has. Reads use plain ``yaml.safe_load``;
writes operate on the raw text lines: locate the key's span by indentation, replace only that
span, then validate the whole document before touching the file.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

import yaml


class ConfigEditError(ValueError):
    """A write was refused (missing block, invalid result, bad value)."""


_KEY_LINE = re.compile(r"^(?P<indent>[ ]*)(?P<key>[A-Za-z0-9_.-]+):(?P<rest>.*)$")


def _line_key(line: str) -> Optional[Tuple[int, str, str]]:
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    match = _KEY_LINE.match(line.rstrip("\n"))
    if not match:
        return None
    return len(match.group("indent")), match.group("key"), match.group("rest")


def _block_end(lines: Sequence[str], start: int, indent: int) -> int:
    """Index just past the block that starts at ``start`` (the key line at ``indent``)."""
    end = start + 1
    while end < len(lines):
        line = lines[end]
        parsed = _line_key(line)
        if line.strip() and not line.lstrip().startswith("#"):
            current = len(line) - len(line.lstrip())
            if current <= indent:
                break
        del parsed
        end += 1
    return end


def _find_key_span(lines: Sequence[str], key: str, span: Tuple[int, int], indent: int) -> Optional[Tuple[int, int]]:
    """The ``(key_line, block_end)`` of ``key`` inside ``span`` at the expected indent."""
    start, end = span
    for index in range(start, end):
        parsed = _line_key(lines[index])
        if parsed is None:
            continue
        current_indent, name, _rest = parsed
        if name == key and current_indent == indent:
            return index, _block_end(lines, index, current_indent)
    return None


def _render_value(key: str, value: Any, indent: int) -> List[str]:
    """Render ``key: value`` lines at ``indent`` (block style for nested dicts)."""
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{key}: {{}}\n"]
        body = yaml.dump(value, default_flow_style=False, sort_keys=False, allow_unicode=True)
        lines = [f"{pad}{key}:\n"]
        for chunk in body.splitlines():
            lines.append(f"{pad}  {chunk}\n")
        return lines
    if isinstance(value, list):
        rendered = yaml.dump(value, default_flow_style=True, sort_keys=False, allow_unicode=True).strip()
        return [f"{pad}{key}: {rendered}\n"]
    if isinstance(value, bool):
        return [f"{pad}{key}: {'true' if value else 'false'}\n"]
    if value is None:
        return [f"{pad}{key}: null\n"]
    if isinstance(value, (int, float)):
        return [f"{pad}{key}: {value}\n"]
    if not isinstance(value, str):
        raise ConfigEditError(f"unrepresentable value for {key}: {type(value).__name__}")
    # A standalone scalar dump can append YAML's unindented `...` terminator
    # (e.g. for http:// URLs), which corrupts a nested config block. Dump the
    # mapping instead; this also preserves strings such as "off" and "001".
    rendered = yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False, width=100000)
    return [pad + line + "\n" for line in rendered.splitlines()]


def write_config_value(text: str, path: Sequence[str], value: Any) -> str:
    """Replace (or create) the value at ``path`` in the YAML ``text``; comments elsewhere survive.

    ``value=None`` deletes the key. Raises :class:`ConfigEditError` if a parent block is missing
    or the result would be invalid YAML.
    """
    if not path:
        raise ConfigEditError("empty config path")
    lines = text.splitlines(keepends=True)
    # Locate each parent block from the root (top-level keys are at indent 0); missing parents
    # are created as empty blocks so a partial config can still be edited.
    span: Tuple[int, int] = (0, len(lines))
    indent = 0
    for key in path[:-1]:
        found = _find_key_span(lines, key, span, indent)
        if found is None:
            pad = " " * indent
            insert_at = span[1]
            lines[insert_at:insert_at] = [f"{pad}{key}:\n"]
            found = (insert_at, insert_at + 1)
        span = (found[0], found[1])
        indent = indent + 2
        # The key line itself may carry an inline value (e.g. ``luna: {x: 1}``) — refuse those.
        _, _, rest = _line_key(lines[found[0]])  # type: ignore[misc]
        if rest.strip() and not rest.strip().startswith("#"):
            raise ConfigEditError(f"inline value at {'.'.join(path[:-1])} is not editable here")

    leaf = path[-1]
    found = _find_key_span(lines, leaf, span, indent)
    if value is None:
        if found is None:
            raise ConfigEditError(f"{leaf} is not set (nothing to remove)")
        del lines[found[0]: found[1]]
    else:
        try:
            rendered = _render_value(leaf, value, indent)
        except Exception as exc:  # yaml.representer.RepresenterError and friends
            raise ConfigEditError(f"refusing to write unrepresentable value for {leaf}: {exc}") from exc
        if found is None:
            insert_at = span[1]
            lines[insert_at:insert_at] = rendered
        else:
            lines[found[0]: found[1]] = rendered

    result = "".join(lines)
    try:
        yaml.safe_load(result)
    except yaml.YAMLError as exc:
        raise ConfigEditError(f"refusing to write invalid YAML: {exc}") from exc
    return result


def read_config_value(data: Any, path: Sequence[str]) -> Any:
    """Plain dict walk (for values already loaded with ``yaml.safe_load``)."""
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node
