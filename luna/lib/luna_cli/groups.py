"""One dashboard read model for rooms, public notes and scoped people entries."""
from __future__ import annotations

import hashlib
import json

from luna_core import config_read, people
from luna_core.group_memory import GroupMemoryStore, directory, saved_groups, scope
from luna_core.runtime import home
from tools.memory_tool_store import MemoryStore, ENTRY_DELIMITER, _scan_memory_content


class Conflict(ValueError):
    pass


def _revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _catalog(conn):
    config = config_read.load_config()
    scopes = {}
    def add(platform, chat_id, thread_id="", name=""):
        if not chat_id:
            return
        group = scope(platform, chat_id, thread_id)
        key = directory(group).name
        scopes.setdefault(key, {"id": key, **group, "name": name or str(chat_id)})
        if name:
            scopes[key]["name"] = name
    for chat in (config.get("telegram") or {}).get("group_allowed_chats") or []:
        add("telegram", chat)
    configured = ((config.get("luna") or {}).get("room") or {}).get("chat_id")
    if configured:
        add("telegram", configured)
    for row in conn.execute("SELECT DISTINCT chat_id,thread_id FROM messages WHERE chat_id LIKE '-%'"):
        add("telegram", row[0], row[1])
    for row in conn.execute("SELECT DISTINCT platform,chat_id,thread_id FROM people_membership"):
        add(*row)
    for group in saved_groups():
        add(group["platform"], group["chat_id"], group["thread_id"])
    names = {}
    try:
        saved = json.loads((home() / "channel_directory.json").read_text())
        for platform, rows in (saved.get("platforms") or {}).items():
            for row in rows:
                if isinstance(row, dict) and row.get("id"):
                    names[(platform, str(row["id"]))] = row.get("name") or row.get("title")
    except (ValueError, OSError, TypeError):
        pass
    for group in scopes.values():
        group["name"] = names.get((group["platform"], group["chat_id"])) or group["name"]
        if group["thread_id"]:
            group["name"] += " · Topic " + group["thread_id"]
    return sorted(scopes.values(), key=lambda group: (group["name"].lower(), group["thread_id"]))


def _members(conn, group):
    ids = {str(row[0]) for row in conn.execute(
        "SELECT DISTINCT user_id FROM messages WHERE chat_id=? AND thread_id=? AND user_id IS NOT NULL",
        (group["chat_id"], group["thread_id"]))}
    ids.update(str(row[0]) for row in conn.execute(
        "SELECT user_id FROM people_membership WHERE platform=? AND chat_id=? AND thread_id=?",
        (group["platform"], group["chat_id"], group["thread_id"])))
    return ids


def _facts(registry, entries, ident, group=None):
    entry = dict(entries.get((ident.platform, ident.user_id), people._facts(ident)))
    override = {}
    if group:
        override = entries.get((ident.platform, ident.user_id, "group",
                                people.conversation_scope(group["chat_id"], group["thread_id"])), {})
    entry.update(override)
    return {"display_name": entry.get("display_name") or "", "aliases": entry.get("aliases") or [],
            "pronouns": entry.get("pronouns") or "", "role": entry.get("role") or "",
            "overridden": bool(override), "revision": _revision(entry)}


def _notes(group):
    path = directory({key: group[key] for key in ("platform", "chat_id", "thread_id")}) / "MEMORY.md"
    if path.is_symlink():
        raise ValueError("Group memory cannot be a linked file")
    if path.exists() and path.stat().st_size > 256_000:
        raise ValueError("Group memory is too large to open")
    raw = path.read_text() if path.exists() else ""
    entries = list(dict.fromkeys(MemoryStore._parse_entries(raw)))
    return {"entries": entries, "chars": len(ENTRY_DELIMITER.join(entries)), "revision": _revision(entries)}


def bundle(group_id=None):
    from luna_cli.api_models import _registry
    conn, registry = _registry()
    try:
        config = config_read.load_config()
        groups = _catalog(conn)
        for group in groups:
            group["members"] = len(_members(conn, group))
            group["note_chars"] = _notes(group)["chars"]
        memory = config.get("memory") or {}
        background = (config.get("auxiliary") or {}).get("background_review") or {}
        owners = [str(value) for value in (config.get("telegram") or {}).get("allow_admin_from") or [] if str(value).isdecimal() and str(value) != "0"]
        policy = {"notes_enabled": memory.get("memory_enabled", True),
                  "people_enabled": memory.get("user_profile_enabled", True),
                  "write_approval": memory.get("write_approval", False),
                  "review_interval": memory.get("nudge_interval", 10), "reviews_enabled": background.get("enabled", True),
                  "note_limit": memory.get("memory_char_limit", 2200), "owner_configured": bool(owners),
                  "private_group_reads": "owner_dm_approval", "owner_dm_reads": "approval_free"}
        result = {"groups": groups, "policy": policy}
        if group_id is not None:
            group = next((item for item in groups if item["id"] == group_id), None)
            if group is None:
                raise ValueError("This group has not been observed or configured")
            entries = people.refresh(registry)
            members, seen = [], set()
            for uid in _members(conn, group):
                ident = registry.get_any(group["platform"], uid)
                if ident is None or ident.peer_id in seen:
                    continue
                seen.add(ident.peer_id)
                members.append({"platform": ident.platform, "user_id": ident.user_id,
                                **_facts(registry, entries, ident, group)})
            result["group"] = {**group, "notes": _notes(group),
                               "people": sorted(members, key=lambda member: member["display_name"].lower())}
        return result
    finally:
        conn.close()


def update_notes(group_id, entries, expected_revision):
    group = bundle(group_id)["group"]
    if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries) or len(entries) > 1000:
        raise ValueError("Use a list of short group notes")
    entries = list(dict.fromkeys(entry.strip() for entry in entries if entry.strip()))
    for entry in entries:
        if problem := _scan_memory_content(entry):
            raise ValueError(problem)
    store = GroupMemoryStore({key: group[key] for key in ("platform", "chat_id", "thread_id")})
    def replace(current, limit):
        if _revision(current) != expected_revision:
            raise Conflict("The companion updated these notes. Reload before saving your changes.")
        if len(ENTRY_DELIMITER.join(entries)) > limit:
            raise ValueError(f"Keep this group's notes within {limit} characters")
        return entries, "Group notes saved."
    result = store._mutate("memory", replace)
    if not result.get("success"):
        raise ValueError(result.get("error") or "Group notes could not be saved")
    return bundle(group_id)


def update_person(group_id, user_id, values, expected_revision=None, inherit=False):
    from luna_cli.api_models import _registry
    from hermes_cli.config_lock import settings_lock
    group = bundle(group_id)["group"]
    conn, registry = _registry()
    try:
        ident = registry.get_any(group["platform"], str(user_id))
        if ident is None or ident.user_id not in {registry.get_any(group["platform"], uid).user_id
                for uid in _members(conn, group) if registry.get_any(group["platform"], uid) is not None}:
            raise ValueError("Choose an observed member of this group")
        for field, value in values.items():
            if field == "aliases":
                if not isinstance(value, list) or len(value) > 4 or any(not isinstance(alias, str) or len(alias) > 40 or "\n" in alias or "\r" in alias for alias in value):
                    raise ValueError("Use at most four short aliases")
            elif field not in people.LIMITS or not isinstance(value, str) or len(value) > people.LIMITS[field] or "\n" in value or "\r" in value:
                raise ValueError("Keep names, pronouns and roles to their short field limits")
        with settings_lock(home()):
            entries = people.refresh(registry)
            if expected_revision and _facts(registry, entries, ident, group)["revision"] != expected_revision:
                raise Conflict("This person's group entry changed. Reload before saving.")
            key = (ident.platform, ident.user_id, "group", people.conversation_scope(group["chat_id"], group["thread_id"]))
            if inherit:
                entries.pop(key, None)
            else:
                entries.setdefault(key, {}).update(values)
            people._write(entries)
        return bundle(group_id)
    finally:
        conn.close()


def people_bundle():
    from luna_cli.api_models import _registry
    conn, registry = _registry()
    try:
        entries = people.refresh(registry)
        groups = _catalog(conn)
        memberships = {}
        for group in groups:
            seen = set()
            for uid in _members(conn, group):
                ident = registry.get_any(group["platform"], uid)
                if ident is not None and ident.peer_id not in seen:
                    seen.add(ident.peer_id)
                    memberships.setdefault(ident.peer_id, []).append(group)
        rows = []
        for row in registry.conn.execute("SELECT DISTINCT platform FROM identity"):
            for ident in registry.all_for_platform(row[0]):
                rooms = memberships.get(ident.peer_id, [])
                rows.append({"platform": ident.platform, "user_id": ident.user_id,
                             "shared": _facts(registry, entries, ident),
                             "groups": [{**group, "entry": _facts(registry, entries, ident, group)} for group in rooms]})
        return {"people": rows, "groups": groups}
    finally:
        conn.close()
