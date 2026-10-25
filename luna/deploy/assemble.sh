#!/usr/bin/env bash
# Build a self-contained runtime. DRY_RUN=1 lists files without writing anything.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "${PYTHON:-python3}" "$REPO_ROOT/luna/deploy/assemble.py" "$REPO_ROOT" \
  "${1:-${LUNA_HOME:-${HERMES_HOME:-$HOME/.luna}}}"
