#!/usr/bin/env bash
# Public entry point: run once, then configure Luna in the dashboard.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  exec bash "$ROOT/luna/deploy/install.sh" "$@"
fi
bash "$ROOT/luna/deploy/install.sh" "$@"
# Interactive installs open setup. CI/packaging captures stdout and stays non-interactive.
OPEN_SETUP="${LUNA_OPEN_DASHBOARD:-auto}"
if [[ "$OPEN_SETUP" == "1" || ( "$OPEN_SETUP" == "auto" && -t 1 ) ]]; then
  exec env -u LUNA_HOME -u HERMES_HOME "$HOME/.local/bin/luna" dashboard
fi
