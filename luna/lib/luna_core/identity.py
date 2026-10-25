"""Deterministic identity registry — code-level certainty for peer attribution.

Golden rule #3: peers are derived **only** from transport ids. Nothing in this module ever inspects
message text, display names, or model output to decide *who* someone is. Display names are stored as
metadata only; the peer id is a pure function of ``(platform, user_id)`` plus an explicit,
auditable collision digest.

Manual overrides (``luna/config/identity_overrides.*``) always win over auto-learned rows.
"""

from __future__ import annotations

from luna_core.runtime import home as runtime_home, getenv

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_PEER_PREFIX = "telegram_"
_UNSAFE = re.compile(r"[^a-z0-9_]+")
_COLLAPSE = re.compile(r"_+")
# ``str()`` of an Enum member (``Platform.TELEGRAM``) — not a valid platform key.
_ENUM_STR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z0-9_]+)$")


def normalize_platform(value: Any) -> str:
    """Canonical lowercase platform key. Funnel **every** platform through here.

    ``SessionSource.platform`` is a ``Platform`` enum member and ``str(Platform.TELEGRAM)`` is
    ``"Platform.TELEGRAM"``, not ``"telegram"`` — using the former as a registry key silently forks
    the identity table (duplicate rows, missed manual overrides). Accepts enum members (via
    ``.value``), plain strings, and the already-stringified enum form (healed, so databases written
    before this normalization still resolve). Returns ``""`` for ``None``/blank.
    """
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    text = str(raw).strip()
    if not text:
        return ""
    healed = _ENUM_STR_RE.match(text)
    if healed:
        text = healed.group(1)
    return text.lower()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def heal_identity_platform_keys(conn: sqlite3.Connection) -> int:
    """Merge identity rows written under a non-canonical platform key into the canonical one.

    Production wrote ``"Platform.TELEGRAM"`` (``str()`` of the enum) from the room hook while the
    indexer wrote ``"telegram"`` — one human, two registry rows, and manual overrides silently
    bypassed. This heals existing data once per ``init_db``. A manual row always wins a conflict;
    the loser backfills only fields the winner is missing.
    """
    moved = 0
    platforms = [r[0] for r in conn.execute("SELECT DISTINCT platform FROM identity").fetchall()]
    for plat in platforms:
        canon = normalize_platform(plat)
        if not canon or canon == plat:
            continue
        for row in conn.execute(
            "SELECT * FROM identity WHERE platform = ?", (plat,)
        ).fetchall():
            twin = conn.execute(
                "SELECT * FROM identity WHERE platform = ? AND user_id = ?",
                (canon, row["user_id"]),
            ).fetchone()
            if twin is None:
                conn.execute(
                    "UPDATE identity SET platform = ? WHERE platform = ? AND user_id = ?",
                    (canon, plat, row["user_id"]),
                )
                moved += 1
                continue
            keep, drop = (
                (row, twin) if (row["is_manual"] and not twin["is_manual"]) else (twin, row)
            )
            if keep is row:
                conn.execute("DELETE FROM identity WHERE platform = ? AND user_id = ?",
                             (canon, row["user_id"]))
                conn.execute(
                    "UPDATE identity SET platform = ? WHERE platform = ? AND user_id = ?",
                    (canon, plat, row["user_id"]),
                )
            else:
                conn.execute(
                    "UPDATE identity SET display_name = COALESCE(display_name, ?), "
                    "pronouns = COALESCE(pronouns, ?), aliases = COALESCE(aliases, ?), "
                    "role = COALESCE(role, ?), user_id_alt = COALESCE(user_id_alt, ?) "
                    "WHERE platform = ? AND user_id = ?",
                    (drop["display_name"], drop["pronouns"], drop["aliases"], drop["role"],
                     drop["user_id_alt"], canon, row["user_id"]),
                )
                conn.execute("DELETE FROM identity WHERE platform = ? AND user_id = ?",
                             (plat, row["user_id"]))
            moved += 1
    if moved:
        conn.commit()
    return moved


def sanitize_peer_id(user_id: str, prefix: str = DEFAULT_PEER_PREFIX) -> str:
    """``(prefix, user_id) -> stable peer id``.

    Lowercases, replaces anything outside ``[a-z0-9_]`` with ``_``, collapses runs, and strips
    edges. Empty input becomes ``unknown``. No hashing here — the digest is only added on collision.
    """
    raw = str(user_id or "").strip().lower()
    cleaned = _COLLAPSE.sub("_", _UNSAFE.sub("_", raw)).strip("_")
    return f"{prefix}{cleaned or 'unknown'}"


def collision_digest(user_id: str, length: int = 8) -> str:
    """Short stable digest appended when two ids sanitize to the same string."""
    return hashlib.sha1(str(user_id).encode("utf-8")).hexdigest()[:length]


@dataclass
class Identity:
    platform: str
    user_id: str
    peer_id: str
    display_name: Optional[str] = None
    pronouns: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    role: Optional[str] = None
    user_id_alt: Optional[str] = None
    is_manual: bool = False
    first_seen: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Identity":
        return cls(
            platform=row["platform"],
            user_id=row["user_id"],
            peer_id=row["peer_id"],
            display_name=row["display_name"],
            pronouns=row["pronouns"],
            aliases=json.loads(row["aliases"]) if row["aliases"] else [],
            role=row["role"],
            user_id_alt=row["user_id_alt"],
            is_manual=bool(row["is_manual"]),
            first_seen=row["first_seen"],
            updated_at=row["updated_at"],
        )


class IdentityRegistry:
    """CRUD + resolution over the ``identity`` table."""

    def __init__(self, conn: sqlite3.Connection, *, prefix: str = DEFAULT_PEER_PREFIX):
        self.conn = conn
        self.prefix = prefix

    # -- reads ---------------------------------------------------------------
    def get(self, platform: str, user_id: str) -> Optional[Identity]:
        row = self.conn.execute(
            "SELECT * FROM identity WHERE platform = ? AND user_id = ?",
            (normalize_platform(platform), str(user_id)),
        ).fetchone()
        return Identity.from_row(row) if row else None

    def resolve(self, platform: str, user_id: str) -> Optional[str]:
        ident = self.get(platform, user_id)
        return ident.peer_id if ident else None

    def resolve_any(self, platform: str, user_id: str) -> Optional[str]:
        """Resolve a peer id by primary **or** alt runtime id (one human, two accounts)."""
        ident = self.get_any(platform, user_id)
        return ident.peer_id if ident else None

    def get_any(self, platform: str, user_id: str) -> Optional[Identity]:
        row = self.conn.execute(
            "SELECT * FROM identity WHERE platform = ? AND (user_id = ? OR user_id_alt = ?) "
            "ORDER BY is_manual DESC, updated_at DESC LIMIT 1",
            (normalize_platform(platform), str(user_id), str(user_id)),
        ).fetchone()
        return Identity.from_row(row) if row else None

    def all_for_platform(self, platform: str) -> List[Identity]:
        rows = self.conn.execute(
            "SELECT * FROM identity WHERE platform = ? ORDER BY display_name, user_id",
            (normalize_platform(platform),),
        ).fetchall()
        return [Identity.from_row(r) for r in rows]

    def alias_map(self, platform: Optional[str] = None) -> Dict[str, str]:
        """``{runtime_user_id: peer_id}`` for the Honcho ``userPeerAliases`` config.

        Alt ids are mapped too — without them the same human splits into two Honcho peers and
        facts about them scatter.
        """
        if platform is None:
            rows = self.conn.execute(
                "SELECT user_id, user_id_alt, peer_id, is_manual FROM identity "
                "ORDER BY is_manual ASC, updated_at ASC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT user_id, user_id_alt, peer_id, is_manual FROM identity "
                "WHERE platform = ? ORDER BY is_manual ASC, updated_at ASC",
                (normalize_platform(platform),),
            ).fetchall()
        out: Dict[str, str] = {}
        for r in rows:
            out[r["user_id"]] = r["peer_id"]
            if r["user_id_alt"]:
                out[str(r["user_id_alt"])] = r["peer_id"]
        return out

    # -- writes --------------------------------------------------------------
    def _peer_id_for_new(self, platform: str, user_id: str) -> str:
        platform = normalize_platform(platform)
        base = sanitize_peer_id(user_id, self.prefix)
        clash = self.conn.execute(
            "SELECT user_id FROM identity WHERE platform = ? AND peer_id = ? AND user_id != ?",
            (platform, base, str(user_id)),
        ).fetchone()
        if clash:
            return f"{base}_{collision_digest(user_id)}"
        return base

    def upsert_auto(
        self,
        platform: str,
        user_id: str,
        *,
        display_name: Optional[str] = None,
        user_id_alt: Optional[str] = None,
        now: Optional[str] = None,
    ) -> Identity:
        """Learn a member from transport metadata. Never overrides a manual row, never changes an
        existing peer id (stability matters more than prettiness)."""
        platform = normalize_platform(platform)
        user_id = str(user_id)
        existing = self.get(platform, user_id)
        ts = now or now_iso()
        if existing is None:
            peer_id = self._peer_id_for_new(platform, user_id)
            self.conn.execute(
                "INSERT INTO identity(platform, user_id, user_id_alt, peer_id, display_name, "
                "pronouns, aliases, role, is_manual, first_seen, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                (platform, user_id, user_id_alt, peer_id, display_name, None, None, None, ts, ts),
            )
            self.conn.commit()
            return self.get(platform, user_id)  # type: ignore[return-value]
        if existing.is_manual:
            return existing
        # Refresh mutable metadata only.
        self.conn.execute(
            "UPDATE identity SET display_name = COALESCE(?, display_name), "
            "user_id_alt = COALESCE(?, user_id_alt), updated_at = ? "
            "WHERE platform = ? AND user_id = ?",
            (display_name, user_id_alt, ts, platform, user_id),
        )
        self.conn.commit()
        return self.get(platform, user_id)  # type: ignore[return-value]

    def set_manual(
        self,
        platform: str,
        user_id: str,
        *,
        peer_id: Optional[str] = None,
        display_name: Optional[str] = None,
        pronouns: Optional[str] = None,
        aliases: Optional[Iterable[str]] = None,
        role: Optional[str] = None,
        user_id_alt: Optional[str] = None,
        now: Optional[str] = None,
        clear_fields: Iterable[str] = (),
    ) -> Identity:
        """Explicit override; always wins and is marked ``is_manual``."""
        clear_fields = set(clear_fields)
        if clear_fields - {"display_name", "pronouns", "aliases", "role", "user_id_alt"}:
            raise ValueError("Unsupported identity field to clear")
        platform = normalize_platform(platform)
        user_id = str(user_id)
        ts = now or now_iso()
        existing = self.get(platform, user_id)
        resolved_peer = peer_id or (existing.peer_id if existing else None) or sanitize_peer_id(
            user_id, self.prefix
        )
        aliases_json = json.dumps(list(aliases)) if aliases is not None else None
        if existing is None:
            self.conn.execute(
                "INSERT INTO identity(platform, user_id, user_id_alt, peer_id, display_name, "
                "pronouns, aliases, role, is_manual, first_seen, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,1,?,?)",
                (platform, user_id, user_id_alt, resolved_peer, display_name, pronouns,
                 aliases_json, role, ts, ts),
            )
        else:
            self.conn.execute(
                "UPDATE identity SET peer_id = ?, display_name = COALESCE(?, display_name), "
                "pronouns = COALESCE(?, pronouns), aliases = COALESCE(?, aliases), "
                "role = COALESCE(?, role), user_id_alt = COALESCE(?, user_id_alt), "
                "is_manual = 1, updated_at = ? "
                "WHERE platform = ? AND user_id = ?",
                (resolved_peer, display_name, pronouns, aliases_json, role, user_id_alt, ts,
                 platform, user_id),
            )
        for field in clear_fields:
            if field not in {"display_name", "pronouns", "aliases", "role", "user_id_alt"}:
                raise ValueError(f"Cannot clear identity field {field!r}")
            self.conn.execute(f"UPDATE identity SET {field} = NULL WHERE platform = ? AND user_id = ?", (platform, user_id))
        self.conn.commit()
        return self.get(platform, user_id)  # type: ignore[return-value]

    def load_overrides(self, path: str | Path) -> int:
        """Apply a manual override file.

        Format (JSON, or YAML if PyYAML is importable)::

            {"platform": "telegram",
             "members": [
               {"user_id": "1000000001", "peer_id": "sam", "display_name": "Sam",
                "pronouns": "he/him", "role": "owner", "aliases": ["sam"]}
             ]}
        """
        path = Path(path)
        data = _read_structured(path)
        platform = data.get("platform", "telegram")
        count = 0
        for member in data.get("members", []):
            uid = str(member["user_id"])
            self.set_manual(
                platform,
                uid,
                peer_id=member.get("peer_id"),
                display_name=member.get("display_name"),
                pronouns=member.get("pronouns"),
                aliases=member.get("aliases"),
                role=member.get("role"),
                user_id_alt=member.get("user_id_alt"),
            )
            count += 1
        return count

    # -- audit ---------------------------------------------------------------
    def audit(self) -> Dict[str, Any]:
        """Report attribution problems: unmapped members, colliding peers, orphan identities.

        ``unmapped`` — non-bot senders seen in ``messages`` with no registry row.
        ``colliding`` — one peer id mapped from more than one runtime id.
        ``orphans`` — registry rows with no message history (usually fine; reported for visibility).
        """
        unmapped = [
            dict(r)
            for r in self.conn.execute(
                "SELECT chat_id, user_id, user_name, COUNT(*) AS n FROM messages "
                "WHERE is_bot = 0 AND user_id IS NOT NULL "
                "AND user_id NOT IN (SELECT user_id FROM identity) "
                "GROUP BY chat_id, user_id ORDER BY n DESC"
            ).fetchall()
        ]
        colliding = [
            dict(r)
            for r in self.conn.execute(
                "SELECT peer_id, COUNT(DISTINCT user_id) AS n, "
                "GROUP_CONCAT(user_id) AS user_ids FROM identity "
                "GROUP BY peer_id HAVING n > 1"
            ).fetchall()
        ]
        orphans = [
            dict(r)
            for r in self.conn.execute(
                "SELECT i.platform, i.user_id, i.peer_id FROM identity i "
                "WHERE NOT EXISTS (SELECT 1 FROM messages m "
                "  WHERE m.user_id = i.user_id AND m.is_bot = 0)"
            ).fetchall()
        ]
        return {
            "unmapped": unmapped,
            "colliding": colliding,
            "orphans": orphans,
            "ok": not unmapped and not colliding,
        }

    def merge(self, platform: str, primary_user_id: str, alt_user_id: str) -> Optional["Identity"]:
        """Unify one human's two runtime ids under the primary's peer (alt account).

        The alt becomes the primary's ``user_id_alt`` so ``resolve_any`` and the Honcho alias map
        cover both. An existing alt row is absorbed (manual flags and missing metadata preserved)
        and deleted. A primary that already carries a *different* alt is refused — three ids for
        one human needs an explicit un-merge first, never a silent overwrite.
        """
        platform = normalize_platform(platform)
        primary_user_id, alt_user_id = str(primary_user_id), str(alt_user_id)
        if primary_user_id == alt_user_id:
            return None
        primary = self.get_any(platform, primary_user_id)
        alt = self.get_any(platform, alt_user_id)
        if primary is None and alt is None:
            return None
        if primary is None:
            # Only the alt has a row: merge onto it, swapping the labels.
            primary, alt = alt, None
            primary_user_id, alt_user_id = alt_user_id, primary_user_id
        if primary.user_id_alt and primary.user_id_alt != alt_user_id:
            raise ValueError(
                f"{primary_user_id} already has alt {primary.user_id_alt}; "
                "un-merge first before assigning a third id"
            )
        is_manual = bool(primary.is_manual or (alt is not None and alt.is_manual))
        display_name = primary.display_name or (alt.display_name if alt else None)
        pronouns = primary.pronouns or (alt.pronouns if alt else None)
        role = primary.role or (alt.role if alt else None)
        aliases = list(primary.aliases or [])
        for extra in ((alt.aliases if alt else None) or []):
            if extra not in aliases:
                aliases.append(extra)
        self.conn.execute(
            "UPDATE identity SET user_id_alt = ?, display_name = ?, pronouns = ?, role = ?, "
            "aliases = ?, is_manual = ? WHERE platform = ? AND user_id = ?",
            (alt_user_id, display_name, pronouns, role, json.dumps(aliases) if aliases else None,
             1 if is_manual else 0, platform, primary_user_id),
        )
        if alt is not None:
            self.conn.execute(
                "DELETE FROM identity WHERE platform = ? AND user_id = ?",
                (platform, alt_user_id),
            )
        self.conn.commit()
        return self.get(platform, primary_user_id)


def _read_structured(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "PyYAML is required for YAML override files; use JSON instead"
            ) from exc
        return yaml.safe_load(text) or {}
    return json.loads(text)


# Manual overrides always win — but only if they are actually loaded. The loader used to have no
# production caller, which silently turned every "manual identity" claim in the docs into a lie.
_OVERRIDES_CACHE: Dict[str, tuple] = {}


def overrides_path(explicit: Optional[str | Path] = None) -> Optional[Path]:
    """Resolve the override file: explicit arg > ``LUNA_IDENTITY_OVERRIDES`` > ``$HERMES_HOME/identity_overrides.json``."""
    import os

    if explicit:
        return Path(os.path.expandvars(str(explicit))).expanduser()
    raw = str(getenv("LUNA_IDENTITY_OVERRIDES") or "").strip()
    if raw:
        return Path(os.path.expandvars(raw)).expanduser()
    home = str(runtime_home())
    return Path(home) / "identity_overrides.json"


def apply_overrides(
    registry: IdentityRegistry, explicit: Optional[str | Path] = None
) -> int:
    """Load the manual override file into ``registry`` (idempotent, mtime-cached).

    Returns the number of members applied (0 when no file exists or nothing changed).
    """
    path = overrides_path(explicit)
    if path is None or not path.is_file():
        return 0
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0
    key = str(path)
    cached = _OVERRIDES_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    count = registry.load_overrides(path)
    _OVERRIDES_CACHE[key] = (mtime, count)
    return count
