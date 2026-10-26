"""Portable character/settings files. Runtime state and credentials never enter this format.

Imports build a fresh, private profile in a hidden sibling and publish it once complete.
They never replace an existing profile, install executable extensions or start services.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

import yaml

MAX_BYTES = 2 * 1024 * 1024
FORMAT = "luna-profile"
VERSION = 1
ROOTS = frozenset({
    "model", "fallback_providers", "providers", "agent", "context", "compression",
    "display", "dashboard", "tts", "stt", "memory", "honcho", "skills", "privacy",
    "luna", "auxiliary", "smart_model_routing", "platform_toolsets", "toolsets",
    "group_sessions_per_user", "thread_sessions_per_user",
})
LUNA_SECTIONS = frozenset({"character", "output", "room", "memory", "memory_stack", "ambient", "conversation", "data", "logs", "opencode"})
BOOLEAN_ROOTS = frozenset({"group_sessions_per_user", "thread_sessions_per_user"})
REASONING_FIELDS = frozenset({"reasoning_effort", "reasoning_source", "provider", "base_url", "model", "api_key_env"})
SECRET = re.compile(r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|bot[_-]?token|password|secret|authorization|credential|private[_-]?key)", re.I)
REFERENCE = re.compile(r"\$\{[A-Z][A-Z0-9_]*\}")
LOCAL_FIELDS = frozenset({
    "workspace", "baseUrl", "userPeerAliases", "peerName", "aiPeer", "headers",
    "host", "chat_id", "operator_chat", "overrides_file", "state_db", "index_db",
    "command", "args", "env", "cwd", "files", "path", "directory",
})
INACTIVE = {
    "memory": {"memory_enabled": False, "user_profile_enabled": False},
    "luna": {"setup": {"memory": "pending", "jev": "pending", "telegram": "pending"},
             "ambient": {"enabled": False, "dry_run": True}},
}


def _merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _bounded(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Profile must contain finite JSON values") from exc
    if len(encoded) > MAX_BYTES:
        raise ValueError("Profile file exceeds the 2 MiB limit")


def portable_config(config):
    """Apply the same policy on export AND import, including files edited outside Luna."""
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    omitted = set()

    def clean(value, path=()):
        if len(path) > 16:
            raise ValueError("Profile settings are nested too deeply")
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("Setting names must be strings")
                branch = (*path, key)
                drop = (not path and key not in ROOTS) or (path == ("luna",) and key not in LUNA_SECTIONS)
                drop = drop or path == ("luna", "memory_stack") and key not in REASONING_FIELDS
                drop = drop or branch == ("luna", "opencode", "memory_budget_mib")
                drop = drop or key in LOCAL_FIELDS or key.endswith(("_path", "_file", "_dir", "_command", "_args"))
                # Token budgets and env-variable NAMES are settings; literal credentials aren't.
                if key.endswith(("_env", "Env")):
                    drop = drop or not isinstance(item, str) or bool(item and not re.fullmatch(r"[A-Z][A-Z0-9_]*", item))
                elif SECRET.search(key) or key.lower() in {"key", "token", "bearer"} or key.lower().endswith(("_token", "-token")):
                    drop = drop or not isinstance(item, str) or not bool(REFERENCE.fullmatch(item))
                if drop:
                    omitted.add(".".join(branch))
                    continue
                out[key] = clean(item, branch)
            return out
        if isinstance(value, list):
            return [clean(item, (*path, str(index))) for index, item in enumerate(value)]
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            parsed = urlsplit(value)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                omitted.add(".".join(path))
                return ""
            if parsed.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}:
                omitted.add(".".join(path))
                return ""
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError("Unsupported setting value")
        return value

    return clean(config), sorted(omitted)


def _skin_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise ValueError("Invalid skin name")
    return name


def validate_bundle(bundle):
    _bounded(bundle)
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        raise ValueError("Choose a Luna profile JSON file; use Character to import SOUL.md")
    if type(bundle.get("version")) is not int or bundle["version"] != VERSION:
        raise ValueError("Unsupported profile format version; update Luna before importing")
    soul = bundle.get("soul")
    if not isinstance(soul, str) or not soul.strip() or len(soul.encode("utf-8")) > 256 * 1024:
        raise ValueError("Profile must contain a nonempty persona under 256 KiB")
    config, omitted = portable_config(bundle.get("config", {}))
    if isinstance(config.get("model"), dict):
        for field in ("provider", "default", "base_url", "api_mode"):
            if field in config["model"] and not isinstance(config["model"][field], str):
                raise ValueError(f"model.{field} must be text")
    for root in ROOTS:
        if root in config and root not in {"fallback_providers", "toolsets", *BOOLEAN_ROOTS} and not isinstance(config[root], dict):
            raise ValueError(f"{root} must be an object")
    for root in BOOLEAN_ROOTS:
        if root in config and type(config[root]) is not bool:
            raise ValueError(f"{root} must be true/false")
    for root in ("fallback_providers", "toolsets"):
        if root in config and not isinstance(config[root], list):
            raise ValueError(f"{root} must be a list")
    # Check known leaf types/ranges through the dashboard's schema.
    from hermes_cli.web_server_config import CONFIG_SCHEMA
    def check(node, prefix=""):
        for key, value in node.items():
            dotted = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict) and dotted in CONFIG_SCHEMA and dotted != "model":
                raise ValueError(f"Invalid object value for {dotted}")
            if isinstance(value, dict):
                check(value, dotted)
            elif dotted in CONFIG_SCHEMA and value is not None:
                field = CONFIG_SCHEMA[dotted]
                kind = field["type"]
                valid = (kind == "boolean" and type(value) is bool
                         or kind == "number" and type(value) in (int, float)
                         or kind in {"string", "select"} and isinstance(value, str)
                         or kind == "list" and isinstance(value, list)
                         or kind == "object" and isinstance(value, dict))
                # Engine templates historically serialize max_turns as a number string.
                if kind == "number" and isinstance(value, str):
                    valid = value.isdigit()
                if not valid:
                    raise ValueError(f"Invalid value type for {dotted}")
                if kind == "number" and any(value is not None and (
                    bound in field and compare(float(value), field[bound]))
                    for bound, compare in (("min", lambda a, b: a < b), ("max", lambda a, b: a > b))):
                    raise ValueError(f"Value out of range for {dotted}")
    check(config)
    skins = bundle.get("skins", {})
    if not isinstance(skins, dict) or len(skins) > 1:
        raise ValueError("A profile may contain only its selected skin")
    selected = (config.get("display") or {}).get("skin", "luna")
    for name, data in skins.items():
        _skin_name(name)
        if name != selected or not isinstance(data, dict):
            raise ValueError("Skin must match the profile's selected skin")
        # Skin files are pure data, serialized by Luna, never extracted from an archive.
        _bounded(data)
    from hermes_cli.skin_engine import _BUILTIN_SKINS
    if selected not in {"luna", *_BUILTIN_SKINS} and selected not in skins:
        raise ValueError("The selected custom skin is missing from this profile file")
    description = bundle.get("description", "")
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError("Description must be text under 2000 characters")
    return {"format": FORMAT, "version": VERSION, "soul": soul,
            "config": config, "skins": skins, "description": description}, omitted


def export_profile(name):
    from hermes_cli.web_server_profiles import _resolve_profile_dir
    from hermes_cli.config import read_user_config_raw
    from hermes_cli.config_lock import settings_lock
    path = _resolve_profile_dir(name)
    with settings_lock(path):
        config, omitted = portable_config(read_user_config_raw(path / "config.yaml"))
        soul = path / "SOUL.md"
        if not soul.is_file():
            from hermes_cli.product_runtime import default_soul
            text = default_soul()
        else:
            text = soul.read_text(encoding="utf-8")
        skins = {}
        selected = (config.get("display") or {}).get("skin", "luna")
        skin = path / "skins" / f"{_skin_name(selected)}.yaml"
        if skin.is_file() and not skin.is_symlink():
            skins[selected] = yaml.safe_load(skin.read_text(encoding="utf-8"))
        from hermes_cli.profiles import read_profile_meta
        description = read_profile_meta(path).get("description", "")
        bundle, _ = validate_bundle({"format": FORMAT, "version": VERSION, "soul": text,
                                    "config": config, "skins": skins, "description": description})
        bundle["omitted"] = omitted
        return bundle


def preview(bundle):
    cleaned, omitted = validate_bundle(bundle)
    from luna_cli.character import parse_soul
    from hermes_cli.product_runtime import ROOT
    skills = (cleaned["config"].get("skills") or {}).get("auto_load") or []
    if not isinstance(skills, list) or any(not isinstance(s, str) for s in skills):
        raise ValueError("skills.auto_load must be a list of skill names")
    available = {p.parent.name for p in (ROOT / "luna/skills").rglob("SKILL.md")}
    return {"title": parse_soul(cleaned["soul"])["title"], "description": cleaned["description"],
            "sections": sorted(cleaned["config"]), "omitted": omitted,
            "missing_skills": sorted(set(skills) - available),
            "memory_enabled": False, "ambient_enabled": False}


def import_profile(name, bundle):
    cleaned, _ = validate_bundle(bundle)
    summary = preview(cleaned)
    from hermes_cli import profiles
    from hermes_cli.config_lock import settings_lock
    from hermes_cli.product_runtime import seed_home, product_defaults
    canon = profiles._canon_valid(name)
    if canon == "default":
        raise ValueError("Import into a new profile name; the default profile is never replaced")
    target = profiles.get_profile_dir(canon)
    root = target.parent.parent
    with settings_lock(root):
        if target.exists() or target.is_symlink():
            raise FileExistsError("A profile with that name already exists; choose another name")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = Path(tempfile.mkdtemp(prefix=f".{canon}.import-", dir=target.parent))
        try:
            seed_home(staging)
            config = _merge(product_defaults({}), cleaned["config"])
            _merge(config, INACTIVE)
            # Client identity/connection belongs to the destination's freshly seeded home.
            config["honcho"].pop("workspace", None)
            config["honcho"]["baseUrl"] = "http://localhost:8000"
            (staging / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
            (staging / "SOUL.md").write_text(cleaned["soul"], encoding="utf-8")
            (staging / ".env").write_text("# Add connections in Luna's dashboard.\n", encoding="utf-8")
            for skin, data in cleaned["skins"].items():
                folder = staging / "skins"
                folder.mkdir(exist_ok=True)
                (folder / f"{skin}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
            if cleaned["description"]:
                profiles.write_profile_meta(staging, description=cleaned["description"], description_auto=False)
            for path in staging.rglob("*"):
                os.chmod(path, 0o700 if path.is_dir() else 0o600)
            os.rename(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return {"ok": True, "name": canon, "summary": summary}
