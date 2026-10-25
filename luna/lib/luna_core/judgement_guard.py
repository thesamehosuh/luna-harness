"""Durable attempt and reported-cost limits, independent of conversational wake timing."""
import json
from datetime import timedelta


def reserve(conn, now, *, calls_per_hour=60, cost_per_day=1.0):
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='judgement_attempts'").fetchone()
        recent = [float(value) for value in json.loads(row[0] if row else '[]') if float(value) > now.timestamp() - 3600]
        spent = conn.execute('SELECT COALESCE(SUM(cost_usd),0) FROM jev_usage WHERE created_at>=?', ((now - timedelta(days=1)).isoformat(),)).fetchone()[0]
        if len(recent) >= max(1, calls_per_hour) or spent >= max(0.0, cost_per_day):
            conn.rollback()
            return False
        recent.append(now.timestamp())
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('judgement_attempts',?)", (json.dumps(recent),))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
