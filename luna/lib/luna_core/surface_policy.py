"""Transport-derived capability and memory visibility policy."""
SAFE_GROUP_TOOLSETS = frozenset({"web", "people"})


def toolsets(config, source, requested):
    policy = (config.get("luna") or {}).get("access") or {}
    surface = str(getattr(source, "chat_type", "") or "").lower()
    if surface in {"group", "supergroup", "channel", "forum"}:
        if policy.get("group_host_access") is True:
            return requested
        allowed = policy.get("group_toolsets", ["web", "people"])
        return sorted(set(allowed) & SAFE_GROUP_TOOLSETS & set(requested))
    # Ordinary DM access is not owner access. Match only configured transport ids.
    owners = (config.get("telegram") or {}).get("allow_admin_from") or []
    uid = str(getattr(source, "user_id", "") or "")
    if uid and uid in {str(value) for value in owners}:
        return requested
    return sorted(SAFE_GROUP_TOOLSETS & set(requested))


def room_surface(chat_type):
    return str(chat_type or "").lower() in {"group", "supergroup", "channel", "forum"}


def private_memory_allowed(config, chat_type, user_id):
    if room_surface(chat_type):
        return False
    if not chat_type:  # local authenticated operator surfaces
        return True
    owners = (config.get("telegram") or {}).get("allow_admin_from") or []
    return str(user_id or "") in {str(value) for value in owners}
