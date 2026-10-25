"""luna-memory — per-identity, budget-bounded memory.

Status (the dashboard Help page's Memory section covers the design from the operator's side):

- **Implemented here:** the deterministic identity layer. Turns are attributed to the author's peer
  from the transport id (never from text); peer aliases + cards are materialized for Honcho; recall
  is hard-bounded and relevance-ranked; room history is written per-author.
- **Bridged:** when the bundled Honcho provider is importable it is used as the recall backend
  behind our budget and identity layer. Vendoring it into this plugin (so no bundled internals are
  imported live) is the next step; until then the import is guarded and degrades to no recall.

Room context is **owned by luna-room** (single rendition per turn). This provider never injects
room chatter: a second, differently-trimmed copy of the same room under the "authoritative
reference" memory fence is how a model blends two windows into a false composite — and it leaked
group chatter into DM/CLI turns.

Config: reads the ``honcho:`` block and ``luna.memory`` from config.yaml, plus env overrides
(``LUNA_MEMORY_RECALL_MAX_CHARS`` wins over ``luna.memory.recall_max_chars``).
"""

from __future__ import annotations

from luna_core.runtime import home as runtime_home, getenv

import logging
import os
import re
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from luna_core import config_read  # noqa: E402
from luna_core import db as luna_db  # noqa: E402
from luna_core.budget import rank_sections  # noqa: E402
from luna_core.identity import IdentityRegistry, apply_overrides, normalize_platform  # noqa: E402
from luna_core.peers import update_honcho_aliases  # noqa: E402

log = logging.getLogger("luna-memory")

VERSION = "0.2.0"
_LOCK = threading.Lock()


def _home() -> Path:
    return runtime_home()


def _index_db_path() -> Path:
    raw = str(getenv("LUNA_INDEX_DB") or "").strip()
    return Path(os.path.expandvars(raw)).expanduser() if raw else _home() / "luna-state.db"


def _chat_id() -> str:
    configured = str(getenv("LUNA_CHAT_ID") or "").strip()
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


def _honcho_json_path() -> Path:
    raw = str(getenv("LUNA_HONCHO_JSON") or "").strip()
    return Path(os.path.expandvars(raw)).expanduser() if raw else _home() / "honcho.json"


def _refresh_alias_map(registry) -> int:
    """Best-effort alias-map refresh so a newly learned member is one Honcho peer, not two."""
    try:
        return update_honcho_aliases(_honcho_json_path(), registry)
    except Exception:
        log.debug("[luna-memory] alias map refresh failed", exc_info=True)
        return 0


def _memory_config() -> Dict[str, Any]:
    try:
        mem = config_read.section("luna", "memory", default={})
        return mem if isinstance(mem, dict) else {}
    except Exception:
        return {}


def _recall_max_chars() -> int:
    raw = str(getenv("LUNA_MEMORY_RECALL_MAX_CHARS", "")).strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            return 2000
    cfg = _memory_config().get("recall_max_chars")
    try:
        return int(cfg) if cfg is not None else 2000
    except (TypeError, ValueError):
        return 2000


_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def _score_sections(sections: List[str], query: str) -> List[Tuple[float, str]]:
    """Deterministic relevance: query-token overlap, ties keep source order.

    Not magic — just enough signal that a long recall keeps the parts about the current ask
    instead of whatever happened to be first.
    """
    tokens = set(_TOKEN_RE.findall((query or "").lower()))
    scored: List[Tuple[float, str]] = []
    for idx, text in enumerate(sections):
        body = (text or "").lower()
        score = float(sum(1 for t in tokens if t in body))
        # Stable tiebreak toward the more recent section (backends return newest first).
        scored.append((score - idx * 1e-6, text))
    return scored


# hermes enforces isinstance(provider, MemoryProvider) at registration, so inherit the real ABC at
# runtime; fall back to a stub so the module imports in dev/test environments without hermes.
try:
    from agent.memory_provider import MemoryProvider as _MemoryProviderBase
except Exception:  # pragma: no cover - dev/test without hermes
    class _MemoryProviderBase:  # type: ignore[no-redef]
        """Stub base so the provider imports without hermes (tests)."""


class LunaMemoryProvider(_MemoryProviderBase):
    """MemoryProvider implementation. Inherits the real ABC at runtime so hermes accepts it."""

    def __init__(self) -> None:
        self._home = runtime_home()
        self._room_chat = None
        self._room_thread = ""
        self._session_id = ""
        self._platform = getenv("LUNA_PLATFORM", "telegram")
        self._peer_prefix = getenv("LUNA_PEER_PREFIX", "telegram_")
        self._conn: Optional[sqlite3.Connection] = None
        self._backend = None  # optional bridged honcho provider
        self._recall_pending = None
        self._recall_degraded = False
        self._last_recall: Dict[str, Any] = {
            "chars": 0, "truncated": False, "dropped": 0, "sections": 0, "backend": "none",
        }

    # -- ABC surface --------------------------------------------------------
    @property
    def name(self) -> str:
        # Must match the plugin directory name (memory.provider: luna-memory).
        return "luna-memory"

    def is_available(self) -> bool:
        from luna_core import config_read
        if config_read.section("luna", "setup", "memory", default="enabled") != "enabled":
            return False
        try:
            self._ensure_conn()
            return True
        except Exception:
            return False

    def unavailable_reason(self) -> str:
        return "luna-state.db not writable"

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        from luna_core.managed_memory import restore
        restore()
        from luna_core.surface_policy import room_surface
        self._room_chat = str(kwargs.get("chat_id") or "") if room_surface(kwargs.get("chat_type")) else None
        from gateway.session_context import get_session_env
        from luna_core.room_dispatch import current_target
        target = current_target()
        self._room_thread = str(kwargs.get("thread_id") or (target.thread_id if target else get_session_env("HERMES_SESSION_THREAD_ID", "")) or "")
        self._session_id = str(session_id or "")
        self._ensure_conn()
        # Learn identity from the transport, deterministically. Manual overrides always win.
        user_id = kwargs.get("user_id")
        if user_id:
            registry = IdentityRegistry(self._conn, prefix=self._peer_prefix)
            apply_overrides(registry)
            platform = normalize_platform(kwargs.get("platform") or self._platform)
            is_new = registry.get_any(platform, str(user_id)) is None
            registry.upsert_auto(
                platform,
                str(user_id),
                display_name=kwargs.get("user_name"),
                user_id_alt=kwargs.get("user_id_alt"),
            )
            if is_new:
                # A member we had never seen: refresh honcho.json's alias map now, so the
                # bundled provider resolves them to the registry peer instead of generating its
                # own (differently-suffixed) id — one human must not become two Honcho peers.
                _refresh_alias_map(registry)
        # Best-effort bridge to the bundled honcho provider for recall/dialectic.
        self._backend = self._load_bundled_honcho() if self._room_chat is None else None
        if self._backend is not None and hasattr(self._backend, "initialize"):
            try:
                self._backend.initialize(session_id, **kwargs)
            except Exception:
                log.warning("[luna-memory] bundled backend initialize failed", exc_info=True)

    def system_prompt_block(self) -> str:
        # Identity facts belong in peer cards, not the system prompt (cache-safe).
        return ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Hard-bounded, relevance-ranked recall. Never exceeds the configured ceiling.

        Only the bridged recall backend feeds this — room context belongs to luna-room (one
        rendition per turn, group surface only).
        """
        raw = ""
        if self._room_chat is not None:
            from luna_core.room_dispatch import current_target
            target = current_target()
            excluded = target.excluded_message_ids if target is not None else ()
            rows = self._ensure_conn().execute("SELECT message_id,content FROM messages WHERE chat_id=? AND thread_id=? ORDER BY timestamp DESC LIMIT 40", (self._room_chat, self._room_thread)).fetchall()
            raw = "\n\n".join(str(row[1] or "") for row in rows if str(row[0]) not in excluded)
        if self._backend is not None and hasattr(self._backend, "prefetch"):
            try:
                raw = self._bounded_prefetch(query, session_id=session_id) or ""
            except Exception:
                log.warning("[luna-memory] bridged prefetch failed", exc_info=True)

        sections = [s for s in re.split(r"\n\s*\n", raw) if s.strip()] if raw.strip() else []
        budget = rank_sections(
            _score_sections(sections, query), max_chars=_recall_max_chars()
        ) if sections else None
        text = budget.text if budget is not None else ""
        self._last_recall = {
            "degraded": self._recall_degraded,
            "chars": budget.chars if budget else 0,
            "truncated": bool(budget.truncated) if budget else False,
            "dropped": budget.dropped if budget else 0,
            "sections": len(sections),
            "backend": "room-public" if self._room_chat is not None else ("honcho" if self._backend is not None else "none"),
        }
        return text

    def _bounded_prefetch(self, query, *, session_id=""):
        from concurrent.futures import Future, TimeoutError
        from agent.memory_provider import spawn_context_thread
        key = (query, session_id)
        pending = self._recall_pending
        if pending is not None and pending[0] != key:
            if not pending[1].done():
                self._recall_degraded = True
                return ""
            pending = None
        if pending is None:
            future = Future()
            backend = self._backend
            def recall():
                try:
                    future.set_result(backend.prefetch(query, session_id=session_id) or "")
                except BaseException as exc:
                    future.set_exception(exc)
            self._recall_pending = pending = (key, future)
            spawn_context_thread(recall, name="luna-recall").start()
        try:
            timeout = max(0.01, min(10, float(_memory_config().get("recall_timeout_seconds", 2))))
            result = pending[1].result(timeout=timeout)
            self._recall_pending = None
            self._recall_degraded = False
            return result
        except TimeoutError:
            self._recall_degraded = True
            return ""
        except Exception:
            self._recall_pending = None
            self._recall_degraded = True
            raise

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "",
                  turn_author: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        """Record the turn under the author's peer (from the transport, never from text)."""
        if self._backend is not None and hasattr(self._backend, "sync_turn"):
            try:
                # Only pass what the backend's signature accepts; the manager may add kwargs.
                self._backend.sync_turn(user_content, assistant_content, session_id=session_id,
                                        turn_author=turn_author)
            except Exception:
                log.warning("[luna-memory] bridged sync_turn failed", exc_info=True)
        try:
            conn = self._ensure_conn()
            registry = IdentityRegistry(conn, prefix=self._peer_prefix)
            apply_overrides(registry)
            author = turn_author or {}
            uid = author.get("id") or author.get("user_id")
            peer_id = None
            if uid:
                platform = normalize_platform(
                    kwargs.get("platform") or author.get("platform") or self._platform
                )
                is_new = registry.get_any(platform, str(uid)) is None
                peer_id = registry.upsert_auto(
                    platform, str(uid), display_name=author.get("name")
                ).peer_id
                if is_new:
                    _refresh_alias_map(registry)
            # We only need the author mapping here; message content persistence is owned by the
            # indexer (single writer to the room log).
            _ = peer_id
        except Exception:
            log.debug("[luna-memory] sync_turn identity skipped", exc_info=True)

    def _forward(self, method, *args, **kwargs):
        callback = getattr(self._backend, method, None)
        if callback is not None:
            return callback(*args, **kwargs)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        self._forward("queue_prefetch", query, session_id=session_id)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs: Any) -> str:
        return ""

    def identity_signature(self) -> Dict[str, Any]:
        return {"provider": "luna-memory", "version": VERSION, "home": str(self._home), "backend": self._forward("identity_signature") or {}, "visibility": "room-public" if self._room_chat is not None else "private-dm"}

    def shutdown(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
        if self._backend is not None and hasattr(self._backend, "shutdown"):
            try:
                self._backend.shutdown()
            except Exception:
                pass

    # -- lifecycle no-ops (the manager calls these; a duck-typed provider must define them) -----
    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        self._forward("on_turn_start", turn_number, message, **kwargs)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        self._forward("on_session_end", messages)

    def on_session_switch(self, *args: Any, **kwargs: Any) -> None:
        self._forward("on_session_switch", *args, **kwargs)

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        return self._forward("on_pre_compress", messages) or ""

    def on_delegation(self, task: str, result: str, *, child_session_id: str = "", **kwargs: Any) -> None:
        self._forward("on_delegation", task, result, child_session_id=child_session_id, **kwargs)

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: Optional[Dict[str, Any]] = None) -> None:
        self._forward("on_memory_write", action, target, content, metadata=metadata)

    def recall_status(self) -> Optional[Dict[str, Any]]:
        """Budget outcome of the last prefetch — nothing downstream may lose context silently."""
        return dict(self._last_recall)

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return []

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        return None

    def backup_paths(self) -> List[str]:
        return []

    # -- internals ----------------------------------------------------------
    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            with _LOCK:
                if self._conn is None:
                    # The memory manager may call us from several threads; keep the connection
                    # usable across them.
                    conn = luna_db.connect(self._home / "luna-state.db" if not getenv("LUNA_INDEX_DB") else _index_db_path(), check_same_thread=False)
                    luna_db.init_db(conn)
                    self._conn = conn
        return self._conn

    def _load_bundled_honcho(self):
        try:
            from plugins.memory.honcho import HonchoMemoryProvider  # type: ignore

            return HonchoMemoryProvider()
        except Exception:
            log.info("[luna-memory] bundled honcho backend unavailable; local recall only")
            return None


def _room_session() -> str:
    raw = str(getenv("LUNA_ROOM_SESSION_KEY") or "").strip()
    if raw:
        return raw
    chat = _chat_id()
    return f"agent:main:telegram:group:{chat}" if chat else ""


def _honcho_store():
    from luna_core.honcho import HonchoStore

    from luna_core.honcho import connection_settings
    return HonchoStore(**connection_settings())


def sync_peers(platform: Optional[str] = None) -> Dict[str, Any]:
    """Materialize peer aliases + cards locally, then ensure the Honcho room session/peers.

    The Honcho step is best-effort: if the server is down it is reported, not raised.
    """
    from luna_core import peers as luna_peers

    conn = luna_db.connect(_index_db_path())
    luna_db.init_db(conn)
    try:
        registry = IdentityRegistry(conn, prefix=getenv("LUNA_PEER_PREFIX", "telegram_"))
        return luna_peers.sync_identities(
            registry,
            platform=platform,
            honcho_json_path=_honcho_json_path(),
            honcho_store=_honcho_store(),
            room_session=_room_session(),
        )
    finally:
        conn.close()


def audit_peers() -> Dict[str, Any]:
    from luna_core import peers as luna_peers

    conn = luna_db.connect(_index_db_path())
    luna_db.init_db(conn)
    try:
        registry = IdentityRegistry(conn, prefix=getenv("LUNA_PEER_PREFIX", "telegram_"))
        return luna_peers.audit_identities(registry)
    finally:
        conn.close()


def merge_peers(primary: str, alt: str, platform: Optional[str] = None) -> Dict[str, Any]:
    """Unify one human's two runtime ids, then refresh the Honcho alias map."""
    from luna_core import peers as luna_peers

    conn = luna_db.connect(_index_db_path())
    luna_db.init_db(conn)
    try:
        registry = IdentityRegistry(conn, prefix=getenv("LUNA_PEER_PREFIX", "telegram_"))
        return luna_peers.merge_identities(
            registry,
            primary_user_id=primary,
            alt_user_id=alt,
            platform=platform,
            honcho_json_path=_honcho_json_path(),
        )
    finally:
        conn.close()


def register(ctx) -> None:
    provider = LunaMemoryProvider()
    ctx.register_memory_provider(provider)
    # The `luna peers` CLI is retired (P5 — the dashboard People page owns identity work);
    # sync/audit/merge remain as functions for the API and tests.
