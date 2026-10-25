#!/usr/bin/env bash
# Snapshot first, then install into DST. --dry-run makes no changes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -eq 0 ]]; then
  set -- "$HOME/.hermes" "$HOME/.luna"
fi
exec "${PYTHON:-python3}" "$ROOT/migrate.py" "$@"
