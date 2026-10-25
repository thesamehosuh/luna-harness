"""Read the gateway's bounded conversation metadata from another dashboard process."""
from contextlib import closing
import sqlite3
import time

from luna_core.runtime import home


def report():
    path = home() / "luna-state.db"
    empty = {"active": [], "waiting": [], "recent": []}
    if not path.exists():
        return empty
    import psutil
    from luna_core import db
    try:
        with closing(db.connect(path, read_only=True)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(conversation_intents)")}
            anchor = "COALESCE(anchor_message_id,message_id)" if "anchor_message_id" in cols else "message_id"
            rows = conn.execute(f"SELECT platform,chat_id,thread_id,user_id,{anchor} AS message_id,state,reason,at,expires,pid,process_start FROM conversation_intents ORDER BY at DESC LIMIT 100").fetchall()
    except sqlite3.OperationalError:
        return empty
    now = time.time()
    live = {}
    seen = set()
    for row in rows:
        value = dict(row)
        identity = tuple(value[k] for k in ("platform", "chat_id", "thread_id", "message_id"))
        if identity in seen:
            continue
        seen.add(identity)
        pid = value.pop("pid")
        started = value.pop("process_start")
        key = pid, started
        if key not in live:
            try:
                live[key] = abs(psutil.Process(pid).create_time() - started) < 0.01
            except (psutil.Error, TypeError, ValueError):
                live[key] = False
        if value["state"] in {"active", "waiting"} and (not live[key] or value["expires"] <= now):
            value.update(state="skipped", reason="expired" if live[key] else "gateway_stopped")
        if value["state"] == "active":
            empty["active"].append(value)
        elif value["state"] == "waiting":
            empty["waiting"].append(value)
        empty["recent"].append(value)
    return empty
