"""Peer identity materialization for Honcho.

Turns the ``luna_identity`` registry into the two things Honcho needs to reason about people
correctly: the ``userPeerAliases`` map (so no member is an opaque ``telegram_<id>``) and per-peer
cards (name / pronouns / role) so the deriver and dialectic use real identities.

Also the shared registry operations behind the dashboard People page
(:func:`audit_identities`, :func:`merge_identities`, :func:`sync_identities`) — the plugin CLI
and the API are thin callers so the two surfaces cannot drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .identity import IdentityRegistry, apply_overrides


def generate_alias_map(registry: IdentityRegistry, platform: Optional[str] = None) -> Dict[str, str]:
    """``{runtime_user_id: peer_id}`` for every registered member."""
    return registry.alias_map(platform)


def peer_cards(registry: IdentityRegistry, platform: Optional[str] = None) -> List[Dict[str, Any]]:
    """One card per member, for seeding Honcho peer profiles."""
    cards: List[Dict[str, Any]] = []
    platforms = [platform] if platform else sorted(
        {i.platform for i in _all_identities(registry)}
    )
    for plat in platforms:
        for ident in registry.all_for_platform(plat):
            facts = []
            if ident.display_name:
                facts.append(f"name: {ident.display_name}")
            if ident.pronouns:
                facts.append(f"pronouns: {ident.pronouns}")
            if ident.role:
                facts.append(f"role: {ident.role}")
            if ident.aliases:
                facts.append("also known as: " + ", ".join(ident.aliases))
            cards.append({
                "platform": ident.platform,
                "user_id": ident.user_id,
                "peer_id": ident.peer_id,
                "card": facts,
            })
    return cards


def _all_identities(registry: IdentityRegistry):
    rows = registry.conn.execute("SELECT DISTINCT platform FROM identity").fetchall()
    for row in rows:
        yield from registry.all_for_platform(row["platform"])


def update_honcho_aliases(
    honcho_path: str | Path,
    registry: IdentityRegistry,
    *,
    host: str = "hermes",
    platform: Optional[str] = None,
) -> int:
    """Write the generated alias map into ``honcho.json`` under ``hosts.<host>.userPeerAliases``.

    Returns the number of aliases written. Preserves all other config. A no-op write is skipped
    (mtime unchanged) so upstream's mtime-keyed config cache does not churn.

    This map is the bridge that keeps upstream Honcho's peer derivation aligned with the
    ``luna_identity`` registry: ``session_peers`` consults ``userPeerAliases`` before generating
    its own (differently-suffixed) peer id, so a complete, fresh map means one human, one peer.
    """
    path = Path(honcho_path)
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            data = {}
    hosts = data.setdefault("hosts", {})
    entry = hosts.setdefault(host, {})
    aliases = generate_alias_map(registry, platform)
    if entry.get("userPeerAliases") == aliases and path.exists():
        return len(aliases)
    entry["userPeerAliases"] = aliases
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return len(aliases)


# ── Registry operations (shared by the People page and its tests) ──────────────────────────────

def audit_identities(registry: IdentityRegistry) -> Dict[str, Any]:
    """Attribution report: unmapped members, colliding peers, orphan identities."""
    return registry.audit()


def merge_identities(
    registry: IdentityRegistry,
    *,
    primary_user_id: str,
    alt_user_id: str,
    platform: Optional[str] = None,
    honcho_json_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Unify one human's two runtime ids, then refresh the Honcho alias map.

    Returns the merged identity summary, or ``{"error": ...}`` when the pair is not mergeable.
    """
    apply_overrides(registry)
    try:
        ident = registry.merge(platform or "telegram", primary_user_id, alt_user_id)
    except ValueError as exc:
        return {"error": str(exc)}
    if ident is None:
        return {"error": f"no identity for {primary_user_id!r} or {alt_user_id!r}"}
    written = 0
    if honcho_json_path is not None:
        # Best-effort: a failed alias refresh must not undo the merge.
        try:
            written = update_honcho_aliases(honcho_json_path, registry)
        except Exception:
            written = 0
    return {
        "peer_id": ident.peer_id,
        "user_id": ident.user_id,
        "user_id_alt": ident.user_id_alt,
        "aliases_written": written,
    }


def sync_identities(
    registry: IdentityRegistry,
    *,
    platform: Optional[str] = None,
    honcho_json_path: Optional[str | Path] = None,
    honcho_store: Any = None,
    room_session: str = "",
) -> Dict[str, Any]:
    """Materialize peer aliases + cards locally, then ensure the Honcho room session/peers.

    The Honcho step is best-effort: a missing store/room or a down server is reported under
    ``room``, never raised.
    """
    from .honcho import sync_room_peers

    apply_overrides(registry)
    written = 0
    if honcho_json_path is not None:
        written = update_honcho_aliases(honcho_json_path, registry, platform=platform)
    cards = peer_cards(registry, platform=platform)
    room: Dict[str, Any]
    if honcho_store is None:
        room = {"error": "honcho store not configured"}
    elif not room_session:
        room = {"error": "LUNA_CHAT_ID or LUNA_ROOM_SESSION_KEY is required"}
    else:
        try:
            result = sync_room_peers(
                store=honcho_store, registry=registry,
                platform=platform or "telegram", room_session=room_session,
            )
            room = {"session": result.session, "peers": result.peers, "cards": result.cards,
                    "errors": result.errors}
        except Exception as exc:  # pragma: no cover - network
            room = {"error": str(exc)}
    return {"aliases_written": written, "cards": cards, "room": room}
