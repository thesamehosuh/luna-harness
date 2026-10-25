"""Hard rarity budget for self-wakes — independent of jev.

Even a confident jev decision is suppressed by these caps. Message and reaction tiers have separate
counters and cooldowns.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from .db import dumps

MESSAGE = "message"
REACTION = "reaction"
DIRECTED = "directed"


@dataclass
class WakePolicy:
    """Optional hard ceilings. **Disabled by default** — jev decides frequency via its
    fit/value/freshness judgments. Set any of these to enforce a code-level cap (loop protection).
    """

    message_cooldown_minutes: int = 0
    message_max_per_day: Optional[int] = None
    message_max_per_week: Optional[int] = None
    reaction_cooldown_minutes: int = 0
    reaction_max_per_day: Optional[int] = None
    reaction_max_per_week: Optional[int] = None
    directed_cooldown_minutes: int = 0
    directed_max_per_day: Optional[int] = None
    directed_max_per_week: Optional[int] = None

    emergency_max_per_hour: int = 12

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WakeBudget:
    def __init__(self, conn: sqlite3.Connection, policy: Optional[WakePolicy] = None):
        self.conn = conn
        self.policy = policy or WakePolicy()

    # -- reads ---------------------------------------------------------------
    def last_wake_at(self, kind: str) -> Optional[datetime]:
        row = self.conn.execute(
            "SELECT created_at FROM wakes WHERE kind = ? ORDER BY created_at DESC LIMIT 1",
            (kind,),
        ).fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row["created_at"])
        except ValueError:
            return None

    def count_since(self, kind: str, since: datetime) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM wakes WHERE kind = ? AND created_at >= ?",
            (kind, since.isoformat()),
        ).fetchone()
        return int(row["n"]) if row else 0

    def woken_for(self, message_id: str, chat_id: Optional[str] = None) -> bool:
        """True if Luna already acted on this message. Prevents re-acting on the same message
        every poll (dedup, not a frequency cap). ``chat_id`` scopes the check — Telegram message
        ids repeat across chats."""
        if not message_id:
            return False
        if chat_id is not None:
            row = self.conn.execute(
                "SELECT 1 FROM wakes WHERE trigger_message_id = ? AND chat_id = ? LIMIT 1",
                (str(message_id), str(chat_id)),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT 1 FROM wakes WHERE trigger_message_id = ? LIMIT 1", (str(message_id),)
            ).fetchone()
        return row is not None

    def can_wake(self, kind: str, now: Optional[datetime] = None) -> Tuple[bool, str]:
        now = now or datetime.now(timezone.utc)
        if kind == MESSAGE:
            cooldown = timedelta(minutes=self.policy.message_cooldown_minutes)
            day_cap = self.policy.message_max_per_day
            week_cap = self.policy.message_max_per_week
        elif kind == DIRECTED:
            cooldown = timedelta(minutes=self.policy.directed_cooldown_minutes)
            day_cap = self.policy.directed_max_per_day
            week_cap = self.policy.directed_max_per_week
        else:
            cooldown = timedelta(minutes=self.policy.reaction_cooldown_minutes)
            day_cap = self.policy.reaction_max_per_day
            week_cap = self.policy.reaction_max_per_week

        total = self.conn.execute("SELECT COUNT(*) FROM wakes WHERE created_at >= ?", ((now - timedelta(hours=1)).isoformat(),)).fetchone()[0]
        if total >= self.policy.emergency_max_per_hour:
            return False, "emergency hourly guard"
        last = self.last_wake_at(kind)
        if last is not None and now - last < cooldown:
            remaining = cooldown - (now - last)
            return False, f"cooldown ({int(remaining.total_seconds() // 60)}m left)"
        if day_cap is not None and self.count_since(kind, now - timedelta(days=1)) >= day_cap:
            return False, "daily cap"
        if week_cap is not None and self.count_since(kind, now - timedelta(days=7)) >= week_cap:
            return False, "weekly cap"
        return True, "ok"

    # -- writes --------------------------------------------------------------
    def record(
        self,
        kind: str,
        chat_id: str,
        *,
        trigger_message_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> None:
        now = now or datetime.now(timezone.utc)
        self.conn.execute(
            "INSERT INTO wakes(kind, chat_id, trigger_message_id, created_at, detail) "
            "VALUES (?,?,?,?,?)",
            (kind, str(chat_id), trigger_message_id, now.isoformat(), dumps(detail) if detail else None),
        )
        self.conn.commit()

    def recent(self, kind: Optional[str] = None, limit: int = 50):
        if kind:
            return self.conn.execute(
                "SELECT * FROM wakes WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM wakes ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
