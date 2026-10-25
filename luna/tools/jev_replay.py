#!/usr/bin/env python3
"""Developer interface for offline stored-judgment replay; never calls a provider."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from luna_core.config_read import load_config
from luna_core.runtime import home
from luna_core.jev_replay import replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(home() / "luna-state.db"))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--recent", type=int, default=10, help="Compatibility only; replay uses stored scores, not history")
    parser.add_argument("--json", default="")
    args = parser.parse_args()
    result = replay(args.db, load_config(), args.limit)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
