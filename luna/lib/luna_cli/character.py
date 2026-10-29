"""Structured persona + voice shaping (PRODUCT_PLAN P4).

The Character page edits the persona as **sections** (the shipped SOUL's structure), keeps the
hard limits in config (``luna.output.*``), and previews the shaping pipeline live. Everything is
importable without FastAPI (same rule as :mod:`luna_cli.api_models`).

Files touched:

- ``$HERMES_HOME/SOUL.md`` — the persona (structured sections read/written whole).
- ``$HERMES_HOME/config.yaml`` — shaping knobs via :mod:`luna_core.configedit` (comments survive).
- ``$HERMES_HOME/skins/*.yaml`` + ``skills.auto_load`` — skin picker and skill toggles.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from luna_core import configedit, settings
from luna_cli import tune

# The shipped SOUL's section structure — the editor shows these in order, then any extras.
SECTION_ORDER = (
    "Who I am", "Voice", "Rhythm", "Energy", "Personality",
    "Carrying the conversation", "Not a know-it-all", "Just a member",
    "Serious moments", "Independence", "Speaking up on my own", "Language",
    "Hard rules", "Style", "Banned", "TTS",
)


# ── SOUL.md structured I/O ───────────────────────────────────────────────────────────────────────


def soul_path() -> Path:
    return tune._home() / "SOUL.md"


def parse_soul(text: str) -> Dict[str, Any]:
    """``{title, intro, sections: [{title, body}], footer}`` from SOUL markdown."""
    text = text or ""
    title = ""
    body = text
    first_line, _, rest = text.partition("\n")
    if first_line.startswith("# "):
        title = first_line[2:].strip()
        body = rest

    footer = ""
    trailer = re.search(r"\n---\s*\n(?P<footer>[\s\S]*)$", body)
    if trailer:
        footer = trailer.group("footer").strip()
        body = body[: trailer.start()]

    chunks = re.split(r"\n(?=## )", body)
    intro = chunks[0].strip() if chunks else ""
    sections: List[Dict[str, str]] = []
    for chunk in chunks[1:]:
        heading, _, section_body = chunk.partition("\n")
        sections.append({"title": heading[2:].strip(), "body": section_body.strip()})
    return {"title": title, "intro": intro, "sections": sections, "footer": footer}

def render_soul(parsed: Dict[str, Any]) -> str:
    """Inverse of :func:`parse_soul` (stable round-trip for well-formed souls)."""
    parts: List[str] = []
    title = str(parsed.get("title") or "").strip() or "Companion"
    parts.append(f"# {title}\n")
    intro = str(parsed.get("intro") or "").strip()
    if intro:
        parts.append(f"\n{intro}\n")
    for section in parsed.get("sections") or []:
        parts.append(f"\n## {str(section.get('title') or '').strip()}\n")
        section_body = str(section.get("body") or "").strip()
        if section_body:
            parts.append(f"\n{section_body}\n")
    footer = str(parsed.get("footer") or "").strip()
    if footer:
        parts.append(f"\n---\n\n{footer}\n")
    return "".join(parts).rstrip() + "\n"


def named_soul(text, name):
    name = str(name or "").strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise configedit.ConfigEditError("Choose a companion name of 1–80 characters on one line")
    first, separator, rest = text.partition("\n")
    return f"# {name}\n" + (rest if first.startswith("# ") else text)


def read_soul() -> Dict[str, Any]:
    path = soul_path()
    raw = settings.read(path) if settings.exists(path) else ""
    parsed = parse_soul(raw)
    # Known sections first (shipped order), then any user-added ones in file order.
    known = {s["title"]: s for s in parsed["sections"]}
    ordered = [known.pop(t) for t in SECTION_ORDER if t in known]
    ordered.extend(known.values())
    parsed["sections"] = ordered
    parsed["exists"] = bool(raw.strip())
    parsed["path"] = str(path)
    parsed["raw"] = raw
    return parsed


@settings.transactional
def write_soul(*, title: Optional[str] = None, intro: Optional[str] = None,
               sections: Optional[List[Dict[str, str]]] = None,
               footer: Optional[str] = None) -> Dict[str, Any]:
    """Replace the persona (structured write; the whole file is regenerated from parts)."""
    current = read_soul()
    updated = {
        "title": str(title if title is not None else current.get("title") or "").strip() or "Companion",
        "intro": intro if intro is not None else current.get("intro") or "",
        "sections": sections if sections is not None else current.get("sections") or [],
        "footer": footer if footer is not None else current.get("footer") or "",
    }
    for section in updated["sections"]:
        if not str(section.get("title") or "").strip():
            raise configedit.ConfigEditError("every persona section needs a title")
    named_soul("", updated["title"])
    path = soul_path()
    settings.write(path, render_soul(updated))
    _write_character_name(updated["title"])
    return read_soul()


@settings.transactional
def write_soul_text(text: str) -> Dict[str, Any]:
    """Replace the persona from raw markdown (preset application)."""
    if not str(text or "").strip():
        raise configedit.ConfigEditError("persona text is empty")
    title = parse_soul(text).get("title")
    if title:
        named_soul("", title)
        _write_character_name(title)
    settings.write(soul_path(), text.rstrip() + "\n")
    return read_soul()


def _write_character_name(name):
    text = settings.read(tune.config_path())
    settings.write(tune.config_path(), configedit.write_config_value(text, ["luna", "character", "name"], str(name)))


# ── Persona presets ──────────────────────────────────────────────────────────────────────────────

def personas() -> List[Dict[str, Any]]:
    """Shared persona presets, with an existing custom character preserved as a choice."""
    from luna_core.personas import library

    path = tune._home() / "SOUL.md"
    current = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return library(current)


# ── Hard limits (luna.output.*) ──────────────────────────────────────────────────────────────────

_OUTPUT_DEFAULTS = {
    "emoji_filter": True,
    "strip_emoji": False,
    "allowed_emoji": [],
    "max_lines": 4,
    "max_chars": 1200,
    "language": "auto",
    "style_filter": False,
    "sentence_breaks": True,
}


def output_limits() -> Dict[str, Any]:
    """Current shaping knobs (fresh read — this is the editor's view, not the hot shaping path)."""
    from luna_core.config_read import with_defaults
    out = configedit.read_config_value(with_defaults(tune._load_yaml(tune.config_path())), ["luna", "output"]) or {}
    if not isinstance(out, dict):
        out = {}
    return {key: out.get(key, value) for key, value in _OUTPUT_DEFAULTS.items()}


@settings.transactional
def write_output_limits(values: Dict[str, Any]) -> Dict[str, Any]:
    """Surgical ``luna.output.*`` writes (comments in config.yaml survive)."""
    results: Dict[str, Any] = {}
    text = settings.read(tune.config_path())
    for key, value in values.items():
        if key not in _OUTPUT_DEFAULTS:
            results[key] = {"ok": False, "error": f"unknown output limit {key!r}"}
            continue
        if key == "language" and value not in {"auto", "english"}:
            results[key] = {"ok": False, "error": "language must be auto or english"}
            continue
        if key in {"emoji_filter", "strip_emoji", "style_filter", "sentence_breaks"} and not isinstance(value, bool):
            results[key] = {"ok": False, "error": "expects true/false"}
            continue
        if key == "max_chars":
            if type(value) is not int or not 80 <= value <= 3500:
                results[key] = {"ok": False, "error": "max_chars must be between 80 and 3500"}
                continue
        if key == "max_lines":
            try:
                value = int(value)
            except (TypeError, ValueError):
                results[key] = {"ok": False, "error": "max_lines expects an integer"}
                continue
            if value < 1 or value > 50:
                results[key] = {"ok": False, "error": "max_lines must be between 1 and 50"}
                continue
        try:
            text = configedit.write_config_value(text, ["luna", "output", key], value)
            results[key] = {"ok": True}
        except configedit.ConfigEditError as exc:
            results[key] = {"ok": False, "error": str(exc)}
    if any(not r.get("ok") for r in results.values()):
        for result in results.values():
            if result["ok"]:
                result.update(ok=False, error="No changes applied: another field is invalid")
    elif results:
        settings.write(tune.config_path(), text)
    return {"results": results, "limits": output_limits()}


# ── Shaping preview ──────────────────────────────────────────────────────────────────────────────


def preview_shaping(text: str, surface: str = "group") -> Dict[str, Any]:
    """Run the surface's shaping pipeline over sample text and report what it did."""
    from luna_core import text as shaping

    surface = surface if surface in ("group", "dm", "cli") else "group"
    shaped = shaping.shape_for_surface(text or "", surface)
    strip_all, allowed = shaping.emoji_policy()
    notes = []
    if surface == "group":
        notes.append(f"emoji: {'strip all' if strip_all else ('allowlist ' + repr(allowed) if allowed is not None else 'off')}")
        notes.append(f"line cap: {shaping.group_max_lines()}")
        notes.append(f"character cap: {output_limits()['max_chars']}")
        notes.append("markdown stripped, personal details redacted")
    else:
        notes.append("length and emoji kept")
    notes.append("style filtering enabled" if output_limits()["style_filter"] else "style filtering disabled")
    notes.append("sentence line breaks enabled" if output_limits()["style_filter"] and output_limits()["sentence_breaks"] else "sentence line breaks disabled")
    return {
        "surface": surface,
        "input": text or "",
        "output": shaped,
        "changed": shaped != (text or ""),
        "notes": notes,
        "limits": output_limits(),
    }


# ── Skins ────────────────────────────────────────────────────────────────────────────────────────


def list_skins() -> List[Dict[str, Any]]:
    """Skins from ``$HERMES_HOME/skins/*.yaml`` plus the built-in default."""
    skins: List[Dict[str, Any]] = [{"name": "default", "description": "Built-in default skin",
                                    "colors": {}, "builtin": True}]
    directory = tune._home() / "skins"
    for path in sorted(directory.glob("*.yaml")) if directory.exists() else []:
        try:
            data = yaml.safe_load(settings.read(path)) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or path.stem)
        colors = data.get("colors") if isinstance(data.get("colors"), dict) else {}
        skins.append({
            "name": name,
            "description": str(data.get("description") or ""),
            "colors": {str(k): str(v) for k, v in colors.items()},
            "builtin": False,
        })
    current = current_skin()
    for skin in skins:
        skin["active"] = skin["name"] == current
    return skins


def current_skin() -> str:
    data = tune._load_yaml(tune.config_path())
    from hermes_cli.product_runtime import enabled
    return str(configedit.read_config_value(data, ["display", "skin"]) or ("luna" if enabled() else "default"))


@settings.transactional
def set_skin(name: str) -> Dict[str, Any]:
    text = settings.read(tune.config_path())
    try:
        text = configedit.write_config_value(text, ["display", "skin"], str(name))
    except configedit.ConfigEditError as exc:
        return {"ok": False, "error": str(exc)}
    settings.write(tune.config_path(), text)
    return {"ok": True, "skin": current_skin()}


_SKIN_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|[A-Za-z]{3,24})$")


@settings.transactional
def write_skin(name: str, colors: Dict[str, Any], description: Optional[str] = None) -> Dict[str, Any]:
    """Save a skin's colors to ``$HERMES_HOME/skins/<name>.yaml``.

    Keys the editor does not know (fonts, glyphs) survive the write, since the file is read,
    updated, and dumped back. The built-in ``default`` has no file to edit; pointing at it is
    answered with a clear error instead of a silent copy.
    """
    name = str(name or "").strip()
    if not _SKIN_NAME_RE.match(name):
        return {"ok": False, "error": "skin name may use letters, digits, dash, underscore"}
    if name == "default":
        return {"ok": False, "error": "the built-in default skin cannot be edited; copy it to a new name first"}
    cleaned: Dict[str, str] = {}
    for key, value in colors.items():
        key = str(key).strip()
        text = str(value or "").strip()
        if not key:
            continue
        if not _COLOR_RE.match(text):
            return {"ok": False, "error": f"{key}: {text!r} is not a hex or named color"}
        cleaned[key] = text
    if not cleaned:
        return {"ok": False, "error": "no colors to save"}

    directory = tune._home() / "skins"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.yaml"
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(settings.read(path))
            if isinstance(loaded, dict):
                data = loaded
        except Exception as exc:
            return {"ok": False, "error": f"{path.name} is not readable YAML: {exc}"}
    data["name"] = name
    existing = data.get("colors") if isinstance(data.get("colors"), dict) else {}
    merged = {str(k): str(v) for k, v in existing.items()}
    merged.update(cleaned)
    data["colors"] = merged
    if description is not None:
        data["description"] = str(description).strip()

    header = (
        f"# {name} skin — edited from the dashboard.\n"
        "# Keys you do not set here are inherited from the built-in default skin.\n"
    )
    body = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    settings.write(path, header + body)
    return {"ok": True, "name": name, "colors": merged}


# ── Skills auto-load ─────────────────────────────────────────────────────────────────────────────


def list_skills() -> List[Dict[str, Any]]:
    """Skills on disk (runtime + shipped), each with whether it auto-loads into the prompt."""
    auto = set(auto_load_names())
    found: Dict[str, Dict[str, Any]] = {}
    for root in (tune._home() / "skills", Path(__file__).resolve().parents[2] / "skills"):
        if not root.exists():
            continue
        for path in sorted(root.glob("*/*/")):
            name = path.name
            if name in found:
                continue
            found[name] = {
                "name": name,
                "category": path.parent.name,
                "auto_loaded": name in auto,
                "has_instructions": (path / "SKILL.md").exists() or (path / "skill.md").exists(),
            }
    return sorted(found.values(), key=lambda s: (s["category"], s["name"]))


def auto_load_names() -> List[str]:
    data = tune._load_yaml(tune.config_path())
    raw = configedit.read_config_value(data, ["skills", "auto_load"])
    return [str(x) for x in raw] if isinstance(raw, list) else []


@settings.transactional
def set_auto_load(names: List[str]) -> Dict[str, Any]:
    cleaned = [str(n).strip() for n in names if str(n).strip()]
    text = settings.read(tune.config_path())
    try:
        text = configedit.write_config_value(text, ["skills", "auto_load"], cleaned)
    except configedit.ConfigEditError as exc:
        return {"ok": False, "error": str(exc)}
    settings.write(tune.config_path(), text)
    return {"ok": True, "auto_load": auto_load_names()}


# ── Page bundle ──────────────────────────────────────────────────────────────────────────────────


@settings.transactional
def character_bundle() -> Dict[str, Any]:
    return {
        "revision": settings.revision(),
        "soul": read_soul(),
        "output": output_limits(),
        "skins": list_skins(),
        "current_skin": current_skin(),
        "skills": list_skills(),
        "auto_load": auto_load_names(),
        "presets": personas(),
    }
