"""A/B two jev question wordings against real room messages.

Asking jev the right question matters more than any threshold: rewording `reaction_would_fit` moved
"Beep" from 0.84 to 0.06 while a real joke stayed at 0.73. This tool makes that kind of comparison
repeatable instead of ad-hoc.

Two wordings are asked in ONE request per message (jev answers questions independently), so a
comparison costs one call per message rather than two.

    python -m luna.tools.jev_ab --db ~/.luna/luna-state.db --limit 20 \\
        --old "Would a reaction be a fitting response to `candidate.text`?" \\
        --new "Does `candidate.text` carry enough content for a reaction to say something?"
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "lib"))

from luna_core import db as luna_db  # noqa: E402
from luna_core.cascade import LUNA_BLURB, Candidate, is_media_only  # noqa: E402
from luna_core.env import load_luna_env  # noqa: E402
from luna_core.jev import FallbackJevClient, JevClient, noul  # noqa: E402
from luna_core.timefmt import fmt_clock  # noqa: E402

CRITERIA = {"true": "yes", "false": "no"}


def _configured_fallbacks():
    """Read luna.ambient.jev.fallbacks from the live config (single source of truth)."""
    home = Path(os.getenv("HERMES_HOME") or Path.home() / ".luna")
    try:
        import yaml
    except ImportError:
        print(f"note: PyYAML unavailable, so jev fallbacks from {home}/config.yaml are not used.\n"
              f"      Run with the Luna venv ({home}/venv/bin/python) to include them.",
              file=sys.stderr)
        return []
    try:
        from luna_core import config_read

        return config_read.section("luna", "ambient", "jev", "fallbacks", default=[]) or []
    except Exception as exc:
        print(f"note: could not read {home}/config.yaml ({exc}); no fallbacks used.", file=sys.stderr)
        return []


def _busiest_chat(db_path: str) -> str | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT chat_id FROM messages WHERE is_bot = 0 GROUP BY chat_id "
            "ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    return str(row[0]) if row else None


def _load_messages(db_path: str, chat_id: str, limit: int, recent: int):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT message_id, user_name, content, timestamp FROM messages "
            "WHERE chat_id = ? AND is_bot = 0 ORDER BY timestamp DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in reversed(rows):
        text = (row["content"] or "").strip()
        if not text or is_media_only(text):
            continue
        out.append(row)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=os.path.expanduser("~/.luna/luna-state.db"))
    parser.add_argument("--chat-id", default=os.getenv("LUNA_CHAT_ID") or None,
                        help="defaults to the busiest chat in the index")
    parser.add_argument("--old", required=True, help="current wording")
    parser.add_argument("--new", required=True, help="candidate wording")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--recent", type=int, default=8)
    parser.add_argument("--model", default=os.getenv("LUNA_JEV_MODEL", "jev-1.13-free"))
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args(argv)

    load_luna_env()
    key = os.getenv("OPENCODE_ZEN_API_KEY", "")
    if not key:
        print("OPENCODE_ZEN_API_KEY is not set", file=sys.stderr)
        return 1
    primary = JevClient(base_url="https://opencode.ai/zen/v1", model=args.model,
                        api_key=key, timeout=30)
    # Use the same fallback chain as the live poller, so tuning survives a primary outage.
    fallbacks = _configured_fallbacks()
    client = FallbackJevClient(primary, fallbacks,
                               api_key_resolver=lambda env: os.getenv(env, "")) if fallbacks else primary

    chat_id = args.chat_id or _busiest_chat(args.db)
    if not chat_id:
        print("could not determine a chat id; pass --chat-id", file=sys.stderr)
        return 1
    messages = _load_messages(args.db, chat_id, args.limit, args.recent)
    if not messages:
        print("no candidate messages found")
        return 1

    print(f"model={args.model}  messages={len(messages)}  (1 jev call each)\n")
    print(f"{'time':<18} {'OLD':>6} {'NEW':>6} {'delta':>7}  message")
    print("-" * 100)
    deltas = []
    for row in messages:
        candidate = Candidate(chat_id=chat_id, message_id=str(row["message_id"]),
                              text=(row["content"] or "").strip(), user_id=None,
                              user_name=row["user_name"])
        state = {
            "luna": LUNA_BLURB,
            "room": {"chat_id": chat_id, "kind": "private friend group"},
            "recent_messages": [],
            "candidate": {"from": row["user_name"] or "someone", "text": candidate.text},
        }
        try:
            answers = client.ask(state, [
                noul("ab_old", args.old, CRITERIA),
                noul("ab_new", args.new, CRITERIA),
            ])
        except Exception as exc:
            print(f"\nstopped: {exc}", file=sys.stderr)
            break
        route = getattr(client, "served_by", "") or "primary"
        old, new = answers["ab_old"].value, answers["ab_new"].value
        deltas.append(new - old)
        print(f"{fmt_clock(row['timestamp']):<18} {old:6.2f} {new:6.2f} {new - old:+7.2f}  "
              f"[{route[:18]:18}] {candidate.text[:36]!r}")
        if args.sleep:
            time.sleep(args.sleep)

    if deltas:
        bigger = sum(1 for d in deltas if d > 0.05)
        smaller = sum(1 for d in deltas if d < -0.05)
        print("-" * 100)
        print(f"NEW scores higher on {bigger}, lower on {smaller}, unchanged on "
              f"{len(deltas) - bigger - smaller} of {len(deltas)}")
        print(f"mean delta {sum(deltas) / len(deltas):+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
