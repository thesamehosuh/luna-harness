from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from typing import Any
from luna_core.runtime import home as runtime_home, getenv

DEFAULT_RETENTION_DAYS = 1
DEFAULT_BATCH_SIZE = 1000


def _home(explicit: str | None = None) -> Path:
    return Path(explicit).expanduser() if explicit else runtime_home()




def _value(data: dict[str, Any], key: str, default: Any) -> Any:
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _int_value(data: dict[str, Any], key: str, default: int, env_name: str) -> int:
    raw = getenv(env_name)
    try:
        return int(raw) if raw is not None and raw.strip() else int(_value(data, key, default))
    except (TypeError, ValueError):
        return default


def _bool_value(data: dict[str, Any], key: str, default: bool, env_name: str) -> bool:
    raw = getenv(env_name)
    if raw is None or not raw.strip():
        return bool(_value(data, key, default))
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# The SQLite pruning logic now lives in ``luna_core.retention`` so the gateway can enforce
# retention on its indexer loop (see that module's docstring). Re-exported here because the
# operator CLI is the documented entry point and its tests target these names.
from luna_core.retention import (  # noqa: E402
    _config as _retention_config,
    cutoff_iso,
    observe_watermark as _observe_watermark,
    prune_gateway_db,
    prune_luna_db,
)

# One implementation: retention._config honours the `home` argument. The previous local copy read
# the *ambient* config regardless, so `prune_all(other_home)` pruned with this home's window.
_config = _retention_config


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def honcho_prune_sql(*, workspace: str, cutoff: str, batch_size: int) -> str:
    workspace_sql = _literal(workspace)
    cutoff_sql = _literal(cutoff)
    return f"""
BEGIN;
CREATE TEMP TABLE _luna_prune_candidates ON COMMIT DROP AS
SELECT m.id, m.session_name
FROM messages m
WHERE m.workspace_name = {workspace_sql}
  AND m.created_at < TIMESTAMPTZ {cutoff_sql}
  AND EXISTS (
      SELECT 1
      FROM documents d
      CROSS JOIN LATERAL jsonb_array_elements_text(
          CASE
              WHEN jsonb_typeof(d.internal_metadata->'message_ids') = 'array'
                  THEN d.internal_metadata->'message_ids'
              ELSE '[]'::jsonb
          END
      ) AS refs(message_id)
      WHERE d.workspace_name = m.workspace_name
        AND d.deleted_at IS NULL
        AND refs.message_id = m.id::text
  )
  AND NOT EXISTS (
      SELECT 1
      FROM queue q
      WHERE q.message_id = m.id
        AND (q.processed = false OR q.error IS NOT NULL)
  )
ORDER BY m.created_at
FOR UPDATE SKIP LOCKED
LIMIT {int(batch_size)};
CREATE TEMP TABLE _luna_prune_queue_ids ON COMMIT DROP AS
SELECT q.id
FROM queue q
JOIN _luna_prune_candidates c ON c.id = q.message_id;
DELETE FROM queue q USING _luna_prune_candidates c WHERE q.message_id = c.id;
CREATE TEMP TABLE _luna_prune_message_ids ON COMMIT DROP AS
SELECT m.id
FROM messages m
JOIN _luna_prune_candidates c ON c.id = m.id;
DELETE FROM messages m USING _luna_prune_message_ids i WHERE m.id = i.id;
SELECT json_build_object(
    'candidates', (SELECT count(*) FROM _luna_prune_candidates),
    'queue_rows', (SELECT count(*) FROM _luna_prune_queue_ids),
    'messages', (SELECT count(*) FROM _luna_prune_message_ids),
    'sessions', COALESCE(
        (SELECT json_agg(DISTINCT session_name) FROM _luna_prune_candidates),
        '[]'::json
    )
)::text;
COMMIT;
"""


def _psql_env(data: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PGHOST": getenv("LUNA_HONCHO_PGHOST", str(_value(data, "honcho.pg_host", "127.0.0.1"))),
            "PGPORT": getenv("LUNA_HONCHO_PGPORT", str(_value(data, "honcho.pg_port", 5432))),
            "PGUSER": getenv("LUNA_HONCHO_PGUSER", str(_value(data, "honcho.pg_user", "postgres"))),
            "PGDATABASE": getenv("LUNA_HONCHO_PGDATABASE", str(_value(data, "honcho.pg_database", "postgres"))),
        }
    )
    password = getenv("LUNA_HONCHO_PGPASSWORD") or getenv("POSTGRES_PASSWORD")
    if password:
        env["PGPASSWORD"] = password
    return env


def _invalidate_honcho_cache(sessions: list[str], *, host: str, port: str, namespace: str, home: Path | None = None) -> int:
    if not sessions:
        return 0
    redis = getenv("LUNA_HONCHO_REDIS_CLI", "redis-cli")
    removed = 0
    for session in sessions:
        key = f"{namespace}:{session}"
        try:
            command = [redis, "-h", host, "-p", port, "DEL", key]
            stack = (home or runtime_home()) / "honcho"
            if (stack / "docker-compose.yml").exists() and not getenv("LUNA_HONCHO_REDIS_CLI"):
                from luna_core.data_ops import compose_command
                command = compose_command(stack, "exec", "-T", "redis", "sh", "-c", 'export REDISCLI_AUTH="$REDIS_PASSWORD"; exec redis-cli DEL "$1"', "redis", key)
            result = subprocess.run(
                command,
                env=os.environ.copy(),
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                removed += 1
        except (OSError, subprocess.SubprocessError):
            continue
    return removed


def prune_honcho(*, data: dict[str, Any], days: int, batch_size: int, now: datetime | None = None, home: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"messages": 0, "queue_rows": 0, "sessions": [], "failed": 0}
    if days <= 0:
        return result
    workspace = getenv("LUNA_HONCHO_WORKSPACE", str(_value(data, "honcho.workspace", "luna")))
    sql = honcho_prune_sql(
        workspace=workspace,
        cutoff=cutoff_iso(days, now),
        batch_size=batch_size,
    )
    psql = getenv("LUNA_HONCHO_PSQL", "psql")
    stack = (home or runtime_home()) / "honcho"
    managed = (stack / "docker-compose.yml").exists() and not getenv("LUNA_HONCHO_PSQL") and not getenv("LUNA_HONCHO_PGHOST")
    command = [psql, "-X", "-q", "-A", "-t", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", sql]
    if managed:
        from luna_core.data_ops import compose_command
        command = compose_command(stack, "exec", "-T", "database", "sh", "-c", 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -U postgres -d postgres "$@"', "psql", *command[1:])
    try:
        completed = subprocess.run(
            command, # argv is never shell interpolated
            env=_psql_env(data), text=True, capture_output=True, timeout=120, check=False,
        )
        if completed.returncode != 0:
            result["failed"] = 1
            return result
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        result["messages"] = int(payload.get("messages", 0))
        result["queue_rows"] = int(payload.get("queue_rows", 0))
        result["sessions"] = [str(item) for item in payload.get("sessions", [])]
        if _bool_value(data, "honcho.invalidate_cache", True, "LUNA_HONCHO_INVALIDATE_CACHE"):
            result["cache_keys"] = _invalidate_honcho_cache(
                result["sessions"],
                home=home,
                host=getenv("REDIS_HOST", "127.0.0.1"),
                port=getenv("REDIS_PORT", "6379"),
                namespace=getenv(
                    "LUNA_HONCHO_CACHE_NAMESPACE",
                    f"honcho:v2:workspace:{workspace}:session",
                ),
            )
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError, IndexError):
        result["failed"] = 1
    return result


def prune_all(home: str | Path | None = None, *, now: datetime | None = None,
              sqlite_only: bool = False, honcho_only: bool = False) -> dict[str, Any]:
    root = _home(str(home) if home is not None else None)
    data = _config(root)
    if data is None:
        return {"skipped": "config unreadable"}
    days = _int_value(
        data,
        "luna.data.retention_days",
        DEFAULT_RETENTION_DAYS,
        "LUNA_DATA_RETENTION_DAYS",
    )
    batch_size = max(
        1,
        _int_value(data, "luna.data.batch_size", DEFAULT_BATCH_SIZE, "LUNA_DATA_BATCH_SIZE"),
    )
    result: dict[str, Any] = {"retention_days": days, "luna": {}, "gateway": {}}
    if not honcho_only:
        result["luna"] = prune_luna_db(
            root / "luna-state.db", days=days, batch_size=batch_size, now=now
        )
        if _bool_value(data, "luna.data.prune_gateway_state", True, "LUNA_PRUNE_GATEWAY_STATE"):
            watermark = _observe_watermark(root / "luna-state.db")
            if watermark is None:
                # No indexer watermark: every observed row may still be un-indexed raw log.
                result["gateway"] = {"messages": 0, "failed": 0, "skipped": "no indexer watermark"}
            else:
                result["gateway"] = prune_gateway_db(
                    root / "state.db", days=days, batch_size=batch_size, now=now,
                    indexed_through=watermark,
                )
    if not sqlite_only:
        result["honcho"] = prune_honcho(
            data=data, days=days, batch_size=batch_size, now=now, home=root
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home")
    parser.add_argument("--sqlite-only")
    parser.add_argument("--honcho-only")
    args = parser.parse_args(argv)
    result = prune_all(
        args.home,
        sqlite_only=args.sqlite_only,
        honcho_only=args.honcho_only,
    )
    print(json.dumps(result, sort_keys=True))
    return 1 if (
        result.get("luna", {}).get("failed")
        or result.get("gateway", {}).get("failed")
        or result.get("honcho", {}).get("failed")
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
