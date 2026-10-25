#!/usr/bin/env bash
# Luna harness test suite: unit + component + contract + replay + (optional) upstream gateway subset.
#
# The upstream subset needs the hermes runtime deps (and pytest) in a venv. Set HERMES_PY to point
# at one, or it is auto-detected from $HERMES_HOME/venv. When unavailable it is skipped, not failed.
# The contract tier includes the engine-edit inventory check (luna/docs/engine-vendor.md must
# record every Luna edit to an engine file).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Prefer the project venv over the system interpreter. The declared deps (fastapi, pyyaml, psutil)
# live in .venv, and `python3 -m pytest` resolves to an interpreter that has none of them -- which
# surfaces as a wall of collection errors that look like broken tests and are not. Set PYTHON to
# override deliberately.
PY="${PYTHON:-python3}"
if [[ -z "${PYTHON:-}" ]]; then
  for _candidate in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/venv/bin/python"; do
    if [[ -x "$_candidate" ]]; then
      PY="$_candidate"
      break
    fi
  done
fi
echo "==> interpreter: $PY"

echo "==> luna unit + component + contract + replay tests"
# Takes ~8 minutes wall clock. That is not a hang -- do not kill it and assume failure.
"$PY" -m pytest -q luna/tests/unit luna/tests/component luna/tests/contract luna/tests/replay

UPSTREAM_PY="${HERMES_PY:-}"
if [[ -z "$UPSTREAM_PY" && -x "${HERMES_HOME:-$HOME/.luna}/venv/bin/python" ]]; then
  UPSTREAM_PY="${HERMES_HOME:-$HOME/.luna}/venv/bin/python"
fi
# Bounded upstream subset: exactly the private-API surfaces the harness depends on
# (agent cache / sidecar notes, session keys, pre_gateway_dispatch, plugin injection).
# Not the whole tests/gateway tree (900+ files) — that is upstream CI's job, not ours.
UPSTREAM_SUBSET=(
  tests/gateway/test_agent_cache.py
  tests/gateway/test_agent_cache_pressure.py
  tests/gateway/test_stale_self_heal_agent_cache_eviction.py
  tests/gateway/test_adapter_session_key_seam.py
  tests/gateway/test_handoff_thread_session_key.py
  tests/gateway/test_multiplex_adapter_session_key_namespace.py
  tests/gateway/test_queued_native_image_session_key.py
  tests/gateway/test_pre_gateway_dispatch.py
  tests/gateway/test_plugin_message_injection.py
  tests/gateway/test_timestamp_sidecar_replay.py
)
if [[ -n "$UPSTREAM_PY" ]] && "$UPSTREAM_PY" -c "import gateway, pytest" >/dev/null 2>&1; then
  echo "==> upstream gateway contract subset ($UPSTREAM_PY)"
  "$UPSTREAM_PY" -m pytest -q "${UPSTREAM_SUBSET[@]}"
else
  echo "==> skipping upstream gateway subset (set HERMES_PY to a hermes venv with pytest to run it)"
fi

echo "==> ok"
