#!/usr/bin/env bash
# Private-API + prompt-cache contract set for the Luna harness.
#
# Run after EVERY upstream merge. A failing private-symbol contract BLOCKS the merge until the
# pin/engine-edit is reconciled (see AGENTS.md §6 and §7).
#
# The source-level contract tests run anywhere. The upstream gateway subset needs the hermes runtime
# deps (and pytest); set HERMES_PY or it is auto-detected from $HERMES_HOME/venv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Contract checks must import this checkout’s overlay, even when the chosen
# engine interpreter has a different editable Luna deployment installed.
export PYTHONPATH="$REPO_ROOT/luna/lib:$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

PY="${PYTHON:-python3}"

# Prefer the project venv over the system interpreter — see the note in scripts/test.sh. The declared
# deps (fastapi, pyyaml, psutil) live in .venv, and `python3 -m pytest` here resolves to an
# interpreter without them, which reads as broken tests rather than a missing environment.
if [[ -z "${PYTHON:-}" ]]; then
  for _candidate in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/venv/bin/python"; do
    if [[ -x "$_candidate" ]]; then
      PY="$_candidate"
      break
    fi
  done
fi
echo "==> interpreter: $PY"

echo "==> luna contract tests (private APIs + prompt cache + engine edits)"
"$PY" -m pytest -q luna/tests/contract

UPSTREAM_PY="${HERMES_PY:-}"
if [[ -z "$UPSTREAM_PY" && -x "${HERMES_HOME:-$HOME/.luna}/venv/bin/python" ]]; then
  UPSTREAM_PY="${HERMES_HOME:-$HOME/.luna}/venv/bin/python"
fi
if [[ -n "$UPSTREAM_PY" ]] && "$UPSTREAM_PY" -c "import gateway, pytest" >/dev/null 2>&1; then
  echo "==> upstream gateway contract subset ($UPSTREAM_PY)"
  "$UPSTREAM_PY" -m pytest -q \
    tests/gateway/test_agent_cache.py \
    tests/gateway/test_agent_cache_pressure.py \
    tests/gateway/test_stale_self_heal_agent_cache_eviction.py \
    tests/gateway/test_adapter_session_key_seam.py \
    tests/gateway/test_handoff_thread_session_key.py \
    tests/gateway/test_multiplex_adapter_session_key_namespace.py \
    tests/gateway/test_queued_native_image_session_key.py \
    tests/gateway/test_pre_gateway_dispatch.py \
    tests/gateway/test_plugin_message_injection.py \
    tests/gateway/test_timestamp_sidecar_replay.py
else
  echo "==> skipping upstream gateway subset (set HERMES_PY to a hermes venv with pytest to run it)"
fi

echo "==> ok"
