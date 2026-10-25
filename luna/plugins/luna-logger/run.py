#!/usr/bin/env python3
"""Standalone tokenless indexer loop (backs the luna-logger systemd unit).

The same indexer also runs in-gateway as a plugin thread; this runner is the out-of-process option
(for when the gateway is down, or for backfills). It never touches Telegram — it only reads
``state.db`` and writes ``luna-state.db``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[1] / "lib"))

_spec = importlib.util.spec_from_file_location("luna_logger_plugin", _HERE / "__init__.py")
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)


def main() -> None:
    poll = max(2, int(os.getenv("LUNA_LOGGER_POLL", "15")))
    interval = _mod._retention_interval_seconds()
    print(
        f"[luna-logger] standalone indexer every {poll}s (retention every {interval}s)",
        flush=True,
    )
    # Seed so the first pass runs immediately (see the plugin loop for why).
    last_prune = time.monotonic() - interval
    while True:
        try:
            _mod.index_once()
        except Exception as exc:  # never die on one bad pass
            print(f"[luna-logger] pass failed: {exc}", file=sys.stderr, flush=True)
        # Retention is part of running the indexer, not an extra service: an operator who chose
        # the out-of-process runner must not silently lose the pruning the plugin thread does.
        now = time.monotonic()
        if now - last_prune >= interval:
            last_prune = now
            try:
                _mod._enforce_retention()
            except Exception as exc:  # never die on one bad pass
                print(f"[luna-logger] retention failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(poll)


if __name__ == "__main__":
    main()
