"""Transport-derived capability and memory visibility policy."""
SAFE_GROUP_TOOLSETS = frozenset({"web", "people", "memory"})
SAFE_DM_TOOLSETS = frozenset({"web", "people"})


def toolsets(config, source, requested):
    policy = (config.get("luna") or {}).get("access") or {}
    surface = str(getattr(source, "chat_type", "") or "").lower()
    if surface in {"group", "supergroup", "channel", "forum"}:
        if policy.get("group_host_access") is True:
            return [name for name in requested if name != "luna_settings"]
        allowed = policy.get("group_toolsets", ["web", "people", "memory"])
        return sorted(set(allowed) & SAFE_GROUP_TOOLSETS & set(requested))
    # Ordinary DM access is not owner access. Match only configured transport ids.
    owners = (config.get("telegram") or {}).get("allow_admin_from") or []
    uid = str(getattr(source, "user_id", "") or "")
    if uid and uid in {str(value) for value in owners}:
        platform = getattr(source, "platform", None)
        platform = getattr(platform, "value", platform)
        chat_id = str(getattr(source, "chat_id", "") or "")
        if platform == "telegram" and surface == "dm" and uid.isdecimal() and chat_id == uid:
            return sorted(set(requested) | {"luna_settings"})
        return requested
    return sorted(SAFE_DM_TOOLSETS & set(requested))


def room_surface(chat_type):
    return str(chat_type or "").lower() in {"group", "supergroup", "channel", "forum"}


def private_memory_allowed(config, chat_type, user_id, *, platform=None, chat_id=None):
    if room_surface(chat_type):
        return False
    if not chat_type:  # local authenticated operator surfaces
        return True
    if platform is not None or chat_id is not None:
        from luna_core.group_memory import owner_dm
        return owner_dm(config, platform, chat_type, chat_id, user_id)
    owners = (config.get("telegram") or {}).get("allow_admin_from") or []
    return str(user_id or "") in {str(value) for value in owners}


def agent_scope_kwargs(config, source):
    """Bind detached compression agents to the same transport/privacy scope."""
    if source is None or not isinstance(config.get("luna"), dict):
        return {}
    from luna_core.identity import normalize_platform
    platform = normalize_platform(getattr(source, "platform", ""))
    fields = {key: getattr(source, key, None) for key in
              ("chat_type", "chat_id", "thread_id", "user_id", "user_id_alt", "user_name", "chat_name")}
    return {**fields, "platform": platform, "load_soul_identity": True,
            "skip_context_files": not private_memory_allowed(config, fields["chat_type"], fields["user_id"],
                                                             platform=platform, chat_id=fields["chat_id"])}
