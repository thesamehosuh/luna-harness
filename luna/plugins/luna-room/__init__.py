"""luna-room — who's who, and what's being referred to, on a triggered group turn.

The problem this solves: sessions are per-user, so when member B replies to a message member A
sent, Luna sees B's message in B's isolated session. Telegram gives us the quoted *text* but not the
author, and A's original message lives only in A's session. This plugin reconstructs the thread from
the derived index and stages a bounded block via the ephemeral sidecar path (never the transcript,
never ``channel_prompt``).

It also enforces the group output-shaping hard limits (<=4 lines, no emoji/markdown) via
``transform_llm_output``, keyed by a session-id -> surface map recorded at dispatch time (the hook
does not receive ``chat_type``).

Config: ``luna.room.*`` in ``config.yaml`` (chat_id, max_lines, max_chars, max_age_minutes,
per_line_chars, thread_depth), with env overrides:

  LUNA_ROOM_ENABLED        "true"
  LUNA_CHAT_ID             "" (required)
  LUNA_INDEX_DB            "$HERMES_HOME/luna-state.db"
  LUNA_PEER_PREFIX         "telegram_"
  LUNA_ROOM_MAX_LINES      20
  LUNA_ROOM_MAX_CHARS      2000
  LUNA_ROOM_MAX_AGE_MIN    360
  LUNA_ROOM_LINE_CHARS     220
  LUNA_ROOM_THREAD_DEPTH   8
"""

from __future__ import annotations

from luna_core.runtime import home as runtime_home, getenv

import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Make the shared library importable whether or not install.sh wired it into site-packages.
_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from luna_core import config_read  # noqa: E402
from luna_core import db as luna_db  # noqa: E402
from luna_core.identity import IdentityRegistry, apply_overrides, normalize_platform  # noqa: E402
from luna_core.indexer import parse_observed_content  # noqa: E402
from luna_core.room import (  # noqa: E402
    build_room_block,
    fetch_message,
    record_inbound,
    record_luna_reply,
)
from luna_core.text import shape_dm_reply, shape_group_reply  # noqa: E402

log = logging.getLogger("luna-room")

_DEFAULT_CHAT_ID = ""
# RLock: pre_gateway_dispatch holds it across _inject, which itself takes it via _index_conn;
# the bounded hooks (post_llm_call / transform_llm_output) run on fresh worker threads and share
# the cached index connection with it — a plain Lock would deadlock and a bare connection would
# raise sqlite3.ProgrammingError (which used to swallow Luna-reply indexing silently).
_LOCK = threading.RLock()
_INDEX: Dict[str, Any] = {}
# session_id -> {"surface": "group"|"dm", "chat_id": ...}, recorded at dispatch so
# transform_llm_output / post_llm_call can shape and index only group replies. Bounded (oldest
# evicted): session ids accumulate for as long as the gateway lives.
_SESSION_SURFACE: Dict[str, Dict[str, Any]] = {}
_SESSION_SURFACE_CAP = 512
# Set the first time a gateway dispatch records a surface. Distinguishes "this process has no
# gateway turns at all" (CLI/TUI: no surface information exists, so do not guess) from "the map is
# populated but this session is absent" (gateway: a cold cache or an eviction, so fail closed).
_DISPATCH_SEEN = False


def _remember_surface(sid: str, surface: Dict[str, Any]) -> None:
    global _DISPATCH_SEEN
    _DISPATCH_SEEN = True
    _SESSION_SURFACE[str(sid)] = surface
    while len(_SESSION_SURFACE) > _SESSION_SURFACE_CAP:
        _SESSION_SURFACE.pop(next(iter(_SESSION_SURFACE)))


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def _flag(name: str, default: bool) -> bool:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _room_config() -> Dict[str, Any]:
    """The ``luna.room`` config block (env vars override these; see ``_num``)."""
    try:
        room = config_read.section("luna", "room", default={})
        return room if isinstance(room, dict) else {}
    except Exception:
        return {}


def _num(env_name: str, cfg_key: str, default: int) -> int:
    raw = str(getenv(env_name, "")).strip()
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    cfg = _room_config().get(cfg_key)
    try:
        return int(cfg) if cfg is not None else default
    except (TypeError, ValueError):
        return default


def _chat_id() -> str:
    configured = str(getenv("LUNA_CHAT_ID") or _DEFAULT_CHAT_ID or "").strip()
    if configured:
        return configured
    try:
        configured = str(config_read.section("luna", "room", "chat_id", default="") or "").strip()
        if configured:
            return configured
        allowed = config_read.section("telegram", "group_allowed_chats")
        if isinstance(allowed, list) and len(allowed) == 1:
            return str(allowed[0]).strip()
        return ""
    except Exception:
        return ""


def _peer_prefix() -> str:
    return str(getenv("LUNA_PEER_PREFIX") or "telegram_").strip()


def _index_db_path() -> Path:
    raw = str(getenv("LUNA_INDEX_DB") or "").strip()
    if raw:
        return Path(os.path.expandvars(raw)).expanduser()
    home = str(runtime_home())
    return Path(home) / "luna-state.db"


def _index_conn():
    path = _index_db_path()
    key = str(path)
    with _LOCK:
        conn = _INDEX.get(key)
        if conn is None:
            # check_same_thread=False: the bounded hooks run on fresh worker threads per
            # invocation. Access stays serialized under _LOCK.
            conn = luna_db.connect(path, check_same_thread=False)
            luna_db.init_db(conn)
            _INDEX[key] = conn
        return conn


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _looks_like_command(event: Any) -> bool:
    if str(getattr(event, "message_type", "") or "").lower().endswith("command"):
        return True
    return str(getattr(event, "text", "") or "").lstrip().startswith("/")


def _reply_to_message_id(event: Any) -> Optional[str]:
    """Prefer the raw transport object; fall back to the event field."""
    raw = getattr(event, "raw_message", None)
    rtm = getattr(raw, "reply_to_message", None) if raw is not None else None
    if rtm is not None:
        mid = getattr(rtm, "message_id", None)
        if mid is not None:
            return str(mid)
    mid = getattr(event, "reply_to_message_id", None)
    return str(mid) if mid is not None else None


def _reply_to_author_id(event: Any) -> Optional[str]:
    raw = getattr(event, "raw_message", None)
    rtm = getattr(raw, "reply_to_message", None) if raw is not None else None
    from_user = getattr(rtm, "from_user", None) if rtm is not None else None
    uid = getattr(from_user, "id", None) if from_user is not None else None
    if uid is not None:
        return str(uid)
    # Populated by the telegram reply-author engine edit (0002).
    ra = getattr(event, "reply_to_author_id", None)
    return str(ra) if ra is not None else None


def _bot_user_id(gateway: Any, source: Any) -> Optional[str]:
    """This bot's own transport user id, from the adapter. ``None`` when not resolvable."""
    try:
        adapters = getattr(gateway, "adapters", None) or {}
        adapter = adapters.get(getattr(source, "platform", None))
    except Exception:
        adapter = None
    for path in ("_bot.id", "bot.id", "_bot_user_id", "_bot_id"):
        obj: Any = adapter
        for attr in path.split("."):
            obj = getattr(obj, attr, None) if obj is not None else None
        if obj is not None:
            return str(obj)
    return str(getenv("LUNA_BOT_USER_ID") or "").strip() or None


def _reply_target_is_luna(event: Any, bot_user_id: Optional[str]) -> bool:
    """True when the replied-to message was authored by *this* bot.

    ``from_user.is_bot`` is true for every bot in the chat (GroupAnonymousBot, third-party bots) —
    minting a "Luna" stand-in for those puts another speaker's words in her mouth and marks their
    message as "Luna spoke" for the wake timing gates. Identity is transport ids: require the
    author id to be our own bot id; when that is not resolvable the check fails closed.
    """
    raw = getattr(event, "raw_message", None)
    rtm = getattr(raw, "reply_to_message", None) if raw is not None else None
    from_user = getattr(rtm, "from_user", None) if rtm is not None else None
    if from_user is None or not getattr(from_user, "is_bot", False):
        return False
    if not bot_user_id:
        return False
    return str(getattr(from_user, "id", "")) == str(bot_user_id)


def _quoted_reply_timestamp(event: Any) -> Optional[str]:
    """ISO timestamp of the quoted message (``reply_to_message.date``), so the stand-in row does
    not masquerade as "Luna just spoke"."""
    raw = getattr(event, "raw_message", None)
    rtm = getattr(raw, "reply_to_message", None) if raw is not None else None
    date = getattr(rtm, "date", None) if rtm is not None else None
    try:
        return datetime.fromtimestamp(float(date), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _quoted_reply_text(event: Any) -> str:
    raw = getattr(event, "raw_message", None)
    rtm = getattr(raw, "reply_to_message", None) if raw is not None else None
    return str(getattr(rtm, "text", "") or getattr(rtm, "caption", "") or "")


def _sender_author_id(event: Any) -> Optional[str]:
    """Transport-authoritative sender id: never parsed from message text."""
    raw = getattr(event, "raw_message", None)
    from_user = getattr(raw, "from_user", None) if raw is not None else None
    uid = getattr(from_user, "id", None) if from_user is not None else None
    if uid is not None:
        return str(uid)
    uid = getattr(getattr(event, "source", None), "user_id", None)
    return str(uid) if uid is not None else None


def _session_entry(session_store: Any, source: Any) -> Any:
    try:
        return session_store.get_or_create_session(source)
    except Exception:
        return None


def _session_id(session_store: Any, source: Any) -> str:
    entry = _session_entry(session_store, source)
    return str(getattr(entry, "session_id", "") or "")


def _install_append_staging(gateway: Any) -> None:
    """Make the sidecar-note slot *append* instead of replace.

    ``run_turn`` stages its own per-turn notes (first-contact, auto-reset) through the same
    one-shot setter — after us. A replacing setter silently dropped the room block exactly on a
    new member's first turn. Composing consume+set gives append semantics without touching
    upstream code (private-API surface: ``_set_pending_turn_sidecar_notes`` /
    ``_consume_pending_turn_sidecar_notes``, both contract-tested).
    """
    if getattr(gateway, "_luna_sidecar_append", False):
        return
    setter = getattr(gateway, "_set_pending_turn_sidecar_notes", None)
    consumer = getattr(gateway, "_consume_pending_turn_sidecar_notes", None)
    if not callable(setter) or not callable(consumer):
        return

    def _append(session_key: str, notes: Any) -> None:
        if not session_key or not notes:
            return
        existing = consumer(session_key) or []
        setter(session_key, list(existing) + list(notes))

    try:
        gateway._set_pending_turn_sidecar_notes = _append
        gateway._luna_sidecar_append = True
    except Exception:  # pragma: no cover - exotic gateway objects
        log.debug("[luna-room] append-staging install failed", exc_info=True)


def _stage_turn_note(gateway: Any, session_key: str, block: str) -> bool:
    stage = getattr(gateway, "_set_pending_turn_sidecar_notes", None)
    if not callable(stage) or not session_key:
        return False
    try:
        stage(session_key, [block])
        return True
    except Exception:
        log.warning("[luna-room] sidecar staging failed", exc_info=True)
        return False


def _session_key(gateway: Any, source: Any, session_store: Any = None) -> str:
    """The exact key the turn runner consumes notes under: the session entry's own key."""
    entry = _session_entry(session_store, source) if session_store is not None else None
    key = str(getattr(entry, "session_key", "") or "")
    if key:
        return key
    try:
        adapter = (getattr(gateway, "adapters", None) or {}).get(getattr(source, "platform", None))
        if adapter is not None:
            return str(adapter._source_session_key(source) or "")
    except Exception:
        log.debug("[luna-room] adapter session key failed", exc_info=True)
    try:
        from gateway.session import build_session_key

        return str(build_session_key(source) or "")
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# hook: room context injection
# --------------------------------------------------------------------------- #
def _inject(event: Any, gateway: Any, session_store: Any) -> None:
    if getattr(event, "_luna_room_injected", False):
        return
    # Plugin-injected turns (engine edit 0005 reuses the *trigger's* message_id on the injected event):
    # indexing one would overwrite the trigger message's content in the room log with the wake
    # brief. The brief is self-contained (0008 keeps observed rows from replaying) and Luna's
    # reply is indexed by record_luna_reply — nothing here belongs in the room log.
    metadata = getattr(event, "metadata", None) or {}
    if getattr(event, "internal", False) or metadata.get("hermes_plugin_injection"):
        return
    source = getattr(event, "source", None)
    if source is None:
        return
    from luna_core.surface_policy import room_surface
    if not room_surface(getattr(source, "chat_type", "")):
        # Non-group turns still get output shaping (de-AI + chat rhythm) — record the surface so
        # transform_llm_output knows. Internal/wake turns never reach here (guarded above), so
        # luna-ambient keeps sole ownership of those.
        sid = _session_id(session_store, source)
        if sid:
            _remember_surface(sid, {"surface": "dm", "chat_id": str(getattr(source, "chat_id", "") or "")})
        # This local directory is available even when memory was skipped or Honcho is down.
        # Only transport ids authorize visibility; an ordinary DM sees its own entry.
        if not _looks_like_command(event):
            from luna_core import people, config_read
            registry = IdentityRegistry(_index_conn(), prefix=_peer_prefix())
            platform = normalize_platform(getattr(source, "platform", "telegram") or "telegram")
            uid = _sender_author_id(event)
            if uid:
                registry.upsert_auto(platform, str(uid), display_name=getattr(source, "user_name", None))
            allowed = people.allowed_ids(registry, platform=platform,
                chat_type=str(getattr(source, "chat_type", "") or ""),
                chat_id=str(getattr(source, "chat_id", "") or ""), user_id=uid,
                thread_id=str(getattr(source, "thread_id", "") or ""),
                config=config_read.load_config())
            directory = people.context(registry, platform, allowed, chat_type=str(getattr(source, "chat_type", "") or ""), chat_id=str(getattr(source, "chat_id", "") or ""), thread_id=str(getattr(source, "thread_id", "") or ""))
            if directory:
                _install_append_staging(gateway)
                _stage_turn_note(gateway, _session_key(gateway, source, session_store), directory)
        return
    chat_id = str(getattr(source, "chat_id", "") or "")
    topic = str(getattr(source, "thread_id", "") or "")
    # Basic identities cover every admitted group, independently of the room-log
    # configuration and Honcho. Only actual transport ingress establishes membership.
    from luna_core import people, config_read
    conn = _index_conn()
    registry = IdentityRegistry(conn, prefix=_peer_prefix())
    apply_overrides(registry)
    platform = normalize_platform(getattr(source, "platform", "telegram") or "telegram")
    from luna_core.room_dispatch import current_target
    target = current_target()
    observed_uid = _sender_author_id(event)
    if observed_uid:
        registry.upsert_auto(platform, str(observed_uid), display_name=getattr(source, "user_name", None))
        people.observe_member(registry, platform, chat_id, str(observed_uid), thread_id=topic)
    sid = _session_id(session_store, source)
    if sid:
        _remember_surface(sid, {"surface": "group", "chat_id": chat_id, "thread_id": topic})
    if _looks_like_command(event):
        # Commands keep their own source/text (engine edit 0001) and get no room block — but they are
        # messages the room saw (so index them), their *output* must obey the group hard limits,
        # and they must be marked triggered like any other message that reached the gateway.
        sid = _session_id(session_store, source)
        if sid:
            _remember_surface(sid, {"surface": "group", "chat_id": chat_id, "thread_id": topic})
        mid = str(getattr(event, "message_id", "") or "")
        if mid:
            try:
                conn = _index_conn()
                record_inbound(
                    conn,
                    message_id=mid,
                    chat_id=chat_id,
                    thread_id=topic,
                    user_id=str(_sender_author_id(event) or "") or None,
                    user_name=getattr(source, "user_name", None),
                    content=str(getattr(event, "text", "") or ""),
                    reply_to_message_id=_reply_to_message_id(event),
                )
                luna_db.mark_triggered(conn, mid, chat_id)
            except Exception:
                log.debug("[luna-room] command indexing skipped", exc_info=True)
        return

    conn = _index_conn()
    registry = IdentityRegistry(conn, prefix=_peer_prefix())
    apply_overrides(registry)

    platform = normalize_platform(getattr(source, "platform", "telegram") or "telegram")
    text = str(getattr(event, "text", "") or "")
    # Identity is code-level certainty: the transport id wins, always. Triggered observe turns
    # strip ``source.user_id`` and re-encode it in-band as ``[name|id]``, so the parsed prefix is
    # used only when it is the sole source — and only when it *agrees* with the transport id when
    # one exists (anything else is user text pretending to be attribution).
    transport_uid = _sender_author_id(event)
    transport_name = getattr(source, "user_name", None)
    parsed = parse_observed_content(text)
    if parsed.user_id and (transport_uid is None or parsed.user_id == transport_uid):
        user_id: Optional[str] = parsed.user_id
        # The transport display name wins when present: the in-band name is message text, and a
        # member can otherwise rename themselves by sending ``[Sam|<own uid>]``.
        user_name = transport_name or parsed.display_name
        text = parsed.text
    else:
        user_id = transport_uid
        user_name = transport_name
    peer_id = None
    if user_id:
        peer_id = registry.upsert_auto(
            platform, str(user_id), display_name=str(user_name) if user_name else None
        ).peer_id

    message_id = str(getattr(event, "message_id", "") or "")
    reply_to = _reply_to_message_id(event)
    if message_id:
        # A reply to Luna's own message: her turns are not in the observe transcript, so without a
        # stand-in row the chain breaks and the model invents what it was replying to. Only for
        # *this* bot — never for other bots in the chat.
        if reply_to and fetch_message(conn, reply_to, chat_id=chat_id) is None and _reply_target_is_luna(
            event, _bot_user_id(gateway, source)
        ):
            from luna_core.cascade import character_identity
            record_inbound(
                conn,
                message_id=reply_to,
                chat_id=chat_id,
                thread_id=topic,
                user_id=None,
                user_name=character_identity()[0],
                content=_quoted_reply_text(event),
                peer_id="luna",
                is_bot=True,
                timestamp=_quoted_reply_timestamp(event),
                observed=False,
                source="stand-in",
            )
        record_inbound(
            conn,
            message_id=message_id,
            chat_id=chat_id,
            thread_id=topic,
            user_id=str(user_id) if user_id else None,
            user_name=str(user_name) if user_name else None,
            content=text,
            reply_to_message_id=reply_to,
            peer_id=peer_id,
        )
        # This message reached the gateway (a formal mention / reply-to-Luna): mark it so the
        # ambient layer never double-answers it. The semantic "directed" path covers the rest.
        luna_db.mark_triggered(conn, message_id, chat_id)

    block = build_room_block(
        conn,
        chat_id,
        current_message_id=message_id or None,
        registry=registry,
        platform=platform,
        max_lines=_num("LUNA_ROOM_MAX_LINES", "max_lines", 20),
        max_chars=_num("LUNA_ROOM_MAX_CHARS", "max_chars", 2000),
        max_age_minutes=_num("LUNA_ROOM_MAX_AGE_MIN", "max_age_minutes", 360),
        per_line_chars=_num("LUNA_ROOM_LINE_CHARS", "per_line_chars", 220),
        thread_depth=_num("LUNA_ROOM_THREAD_DEPTH", "thread_depth", 8),
        excluded_message_ids=target.excluded_message_ids if target is not None else (),
        thread_id=topic,
    )

    # Record the surface so transform_llm_output shapes group replies and post_llm_call can index
    # Luna's own replies into the room log.
    sid = _session_id(session_store, source)
    if sid:
        _remember_surface(sid, {"surface": "group", "chat_id": chat_id, "thread_id": topic})

    if not block.text.strip():
        return

    # The room block is untrusted group chatter. It may only ever ride the ephemeral sidecar
    # (AGENTS.md §3 invariant 1: never the system prompt or channel_prompt — those enter the
    # cached-agent signature). Previously, if the private sidecar seam was unavailable the block
    # was concatenated into ``channel_prompt``, which fails *toward* the highest-trust slot with
    # attacker-controlled text. Fail closed instead: no staging seam, no room context this turn.
    _install_append_staging(gateway)
    if not _stage_turn_note(gateway, _session_key(gateway, source, session_store), block.text):
        log.warning(
            "[luna-room] sidecar staging unavailable; dropping room context for this turn "
            "(chat=%s lines=%d) rather than injecting it into channel_prompt",
            chat_id, block.lines,
        )
        setattr(event, "_luna_room_injected", False)
        return

    setattr(event, "_luna_room_injected", True)
    log.info(
        "[luna-room] injected room context via sidecar-note: chat=%s lines=%d chars=%d truncated=%s",
        chat_id, block.lines, block.chars, block.truncated,
    )


def _on_pre_gateway_dispatch(event: Any = None, gateway: Any = None, session_store: Any = None,
                             **kwargs: Any) -> None:
    if event is None or not _flag("LUNA_ROOM_ENABLED", True):
        return None
    try:
        with _LOCK:
            _inject(event, gateway, session_store)
    except Exception:
        log.warning("[luna-room] injection skipped", exc_info=True)
    return None


# --------------------------------------------------------------------------- #
# hook: group output shaping (hard limits) + Luna's own replies in the room log
# --------------------------------------------------------------------------- #
def _on_transform_llm_output(response_text: str = "", session_id: str = "", platform: str = "",
                             **kwargs: Any) -> Optional[str]:
    # A payload we cannot shape gets no opinion at all. Coercing instead would both raise inside
    # the helpers and (once the pipeline is degraded) inject ``str(payload)`` as the reply text.
    # Returning None tells the engine to keep what it had.
    if not isinstance(response_text, str):
        return None
    raw = response_text
    from gateway.response_filters import is_intentional_silence_response
    if is_intentional_silence_response(raw):
        return raw
    try:
        info = _SESSION_SURFACE.get(str(session_id))
        surface = info.get("surface") if isinstance(info, dict) else info
        if surface == "dm":
            # Every message, not just the room: mechanical de-AI + chat rhythm everywhere.
            shaped = shape_dm_reply(raw)
        elif surface == "group" or _DISPATCH_SEEN:
            # A known group session, OR an unknown session in a process where gateway dispatch has
            # run. The surface map is bounded and FIFO-evicted, so inside the gateway an unrecorded
            # session is a cold cache or an eviction — not evidence of a DM. Under-shaping a group
            # leaks other people's details past redaction and the line cap, which is the one
            # direction this hook must never fail, so fail closed there.
            shaped = shape_group_reply(raw)
        else:
            # No gateway dispatch has EVER run in this process, so we have no surface information
            # at all: this is a CLI/TUI/query turn, where the operator asked for the full assistant
            # (AGENTS.md §1). Group-shaping these would cap every answer at 4 lines, strip emoji and
            # delete non-English text. Unknown means unknown, not group.
            return None
        return shaped if shaped != raw else None
    except Exception:
        log.warning("[luna-room] shaping skipped", exc_info=True)
        # Fail safe, never fail open: a broken pipeline must still redact and cap before anything
        # reaches a group. Nested in its own try with a final ``return None`` so no raise can escape
        # this hook — an escaping exception is discarded by the dispatcher, which ships the raw
        # reply, i.e. exactly the fail-open this path exists to prevent.
        try:
            from luna_core.text import shape_group_reply_minimal

            return shape_group_reply_minimal(raw) or None
        except Exception:
            log.warning("[luna-room] minimal fallback failed too", exc_info=True)
            return None


def _on_post_llm_call(user_message: Any = "", assistant_response: Any = "", session_id: str = "",
                      turn_id: str = "", **kwargs: Any) -> None:
    """Index Luna's own group replies into the room log.

    Without them reply chains through Luna break and the wake-frequency gates never see her
    speak. Only the *shaped* final response is recorded — that is what the room actually saw.
    """
    try:
        response = str(assistant_response or "").strip()
        if not response:
            return None
        from gateway.response_filters import is_intentional_silence_response
        if is_intentional_silence_response(response):
            return None
        info = _SESSION_SURFACE.get(str(session_id))
        if not isinstance(info, dict) or info.get("surface") != "group":
            return None
        chat_id = str(info.get("chat_id") or "")
        if not chat_id:
            return None
        with _LOCK:
            record_luna_reply(
                _index_conn(),
                message_id=f"luna:{session_id}:{turn_id or '0'}",
                chat_id=chat_id,
                content=response,
                thread_id=str(info.get("thread_id") or ""),
            )
    except Exception:
        log.warning("[luna-room] luna reply indexing skipped", exc_info=True)
    return None


def _on_pre_llm_call(platform="", **kwargs):
    """Local dashboard/TUI/CLI turns get the same bounded reference, in the user sidecar."""
    from luna_core.room_dispatch import current_target
    target = current_target()
    if target is not None:
        return {"context": target.note()}
    from gateway.session_context import get_session_env
    local = {"", "cli", "tui", "desktop", "local"}
    if str(platform or "") not in local or get_session_env("HERMES_SESSION_PLATFORM", "") not in local:
        return None
    from luna_cli.api_models import _registry
    from luna_core import people
    conn, registry = _registry()
    try:
        ids = [ident.user_id for ident in registry.all_for_platform("telegram")]
        block = people.context(registry, "telegram", ids)
        return {"context": block} if block else None
    finally:
        conn.close()


def register(ctx) -> None:
    from luna_core.group_memory import TOOL_SCHEMA as group_schema, tool_handler as group_handler
    from luna_core.private_memory import TOOL_SCHEMA as private_schema, tool_handler as private_handler
    ctx.register_tool(name="group_memory", toolset="memory", schema=group_schema, handler=group_handler)
    ctx.register_tool(name="private_memory", toolset="memory", schema=private_schema, handler=private_handler)
    from luna_core.people import TOOL_SCHEMA, tool_handler
    ctx.register_tool(name="people", toolset="people", schema=TOOL_SCHEMA, handler=tool_handler)
    from luna_core.assistant_settings import TOOL_SCHEMA as settings_schema, tool_handler as settings_handler
    ctx.register_tool(name="luna_settings", toolset="luna_settings", schema=settings_schema, handler=settings_handler)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    ctx.register_hook("post_llm_call", _on_post_llm_call)
