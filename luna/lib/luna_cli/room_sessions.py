"""Local operator tool for listing and resetting the live shared room sessions.

Example: python -m luna_cli.room_sessions list
Then: python -m luna_cli.room_sessions reset KEY --expected-session-id ID
This uses the gateway control socket, never edits its routing files or database.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    from luna_core.runtime import home
    from gateway.control_socket import query_gateway_control
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=None, help="The home of the gateway owning the route")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="List shared room keys and their current session IDs")
    reset = sub.add_parser("reset", help="Reset one idle shared room, retaining its old history")
    reset.add_argument("session_key")
    reset.add_argument("--expected-session-id", required=True)
    args = parser.parse_args(argv)
    root = args.home.resolve() if args.home else home()
    verb = "list-room-sessions" if args.action == "list" else "reset-room-session"
    params = {} if args.action == "list" else {"session_key": args.session_key, "expected_session_id": args.expected_session_id}
    result = query_gateway_control(root, verb, params=params, timeout=65)
    if result is None:
        print(json.dumps({"reset": False, "reason": "control_unavailable", "detail": "Start or update the owning gateway, then retry. No offline edits were made."}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if args.action == "list" and isinstance(result.get("rooms"), list) or result.get("reset") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
