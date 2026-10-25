#!/usr/bin/env bash
# One install command for both a source checkout and a prebuilt release.
# Optional: SKIP_VENV=1 (packaging tests), SKIP_SYSTEMD=1 (omit service definitions).
set -euo pipefail
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: bash install.sh [LUNA_HOME]  (default: ~/.luna)"
  echo "Then open ~/.local/bin/luna dashboard to complete setup."
  exit 0
fi
HERMES_HOME="${1:-${LUNA_HOME:-$HOME/.luna}}"
if [[ -f "$HERMES_HOME/current-release.json" ]]; then
  echo "This home is managed by the Luna desktop app. Update it through the app to preserve its verified release pointer." >&2
  exit 1
fi

# Prefer uv: it can fetch a compatible Python even on hosts shipping Python 3.14+.
if [[ "${SKIP_VENV:-0}" != "1" ]] && ! command -v uv >/dev/null 2>&1; then
  if command -v curl >/dev/null 2>&1; then
    echo "==> installing uv (Python environment manager)"
    curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh \
      | env UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh
    export PATH="$HOME/.local/bin:$PATH"
  else
    echo "install: curl or uv is required" >&2; exit 1
  fi
fi
PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v uv >/dev/null 2>&1 && [[ "${SKIP_VENV:-0}" != "1" ]]; then
    PYTHON_BIN="$(uv python find --python-preference managed 3.11 2>/dev/null || true)"
    if [[ -z "$PYTHON_BIN" ]]; then
      uv python install 3.11
      PYTHON_BIN="$(uv python find 3.11)"
    fi
  else
    PYTHON_BIN=python3
  fi
fi
HERMES_HOME="$("$PYTHON_BIN" -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$HERMES_HOME")"
export HERMES_HOME LUNA_HOME="$HERMES_HOME"

# Refuse a live code swap. Stopping and restarting a gateway is the operator's action.
if [[ -x "$HERMES_HOME/venv/bin/python" ]]; then
  "$HERMES_HOME/venv/bin/python" -c \
    'from gateway.status import is_gateway_running; import sys; sys.exit("Stop this home\u0027s gateway in the dashboard before upgrading." if is_gateway_running(cleanup_stale=False) else 0)'
fi

# Source installs build once; release bundles already carry the SPA and need no Node/npm.
if [[ -f "$REPO_ROOT/web/package.json" && "${BUILD_DASHBOARD:-1}" == "1" ]]; then
  command -v npm >/dev/null 2>&1 || { echo "install: Node/npm is required for a source build; use a prebuilt release otherwise" >&2; exit 1; }
  if [[ ! -x "$REPO_ROOT/node_modules/.bin/vite" ]]; then
    (cd "$REPO_ROOT" && npm ci --workspace web --workspace ui-tui --include-workspace-root)
  fi
  (cd "$REPO_ROOT" && npm run build --workspace web && npm run build --workspace ui-tui)
  mkdir -p "$REPO_ROOT/hermes_cli/tui_dist"
  cp "$REPO_ROOT/ui-tui/dist/entry.js" "$REPO_ROOT/hermes_cli/tui_dist/entry.js"
  printf '{"name":"luna-chat","private":true,"type":"module"}\n' > "$REPO_ROOT/hermes_cli/tui_dist/package.json"
fi
[[ -f "$REPO_ROOT/hermes_cli/web_dist/index.html" ]] \
  || { echo "install: dashboard assets missing; build the dashboard or use a prebuilt release" >&2; exit 1; }

# Build the code and environment at their FINAL immutable path. A dependency failure can only
# leave an unreferenced staging directory; it cannot change the active runtime.
RELEASE_ROOT="$("$PYTHON_BIN" "$REPO_ROOT/luna/deploy/releases.py" stage "$REPO_ROOT" "$HERMES_HOME")"
PRODUCT_ROOT="$RELEASE_ROOT/luna"
if [[ "${SKIP_VENV:-0}" != "1" ]]; then
  "$PYTHON_BIN" -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14), "Luna requires Python 3.11–3.13"'
  uv venv --python "$PYTHON_BIN" "$RELEASE_ROOT/venv"
  UV_PROJECT_ENVIRONMENT="$RELEASE_ROOT/venv" uv sync --project "$RELEASE_ROOT" \
    --python "$PYTHON_BIN" --frozen --extra luna --no-dev --inexact
  uv pip install --python "$RELEASE_ROOT/venv/bin/python" -e "$PRODUCT_ROOT/lib"
  "$PYTHON_BIN" "$RELEASE_ROOT/luna/deploy/node_runtime.py" "$RELEASE_ROOT"
  (cd / && "$RELEASE_ROOT/venv/bin/python" -I -c 'import luna_core, luna_cli, gateway, model_tools, hermes_cli.web_server')
fi
printf 'verified\n' > "$RELEASE_ROOT/.ready"
"$PYTHON_BIN" "$REPO_ROOT/luna/deploy/releases.py" publish "$RELEASE_ROOT" "$HERMES_HOME"
PRODUCT_ROOT="$HERMES_HOME/luna"
mkdir -p "$HERMES_HOME"/{plugins,skins,logs,bin}

# Relative links point wholly inside the runtime, so the source checkout can be removed.
for plugin_dir in "$PRODUCT_ROOT"/plugins/*/; do
  name="$(basename "$plugin_dir")"
  link="$HERMES_HOME/plugins/$name"
  if [[ -L "$link" ]]; then
    rm -f "$link"
  elif [[ -e "$link" ]]; then
    mv "$link" "$link.pre-luna-$(date +%s)-$$"
  fi
  ln -s "../luna/plugins/$name" "$link"
done

# Every user makes their own character. Reinstall/upgrade never replaces their settings.
for spec in 'config/config.yaml.luna:config.yaml' 'config/honcho.json.luna:honcho.json' 'soul/DEFAULT.md:SOUL.md' 'assets/PEOPLE.md:PEOPLE.md' 'config/skins/luna.yaml:skins/luna.yaml'; do
  src="${spec%%:*}"; dst="${spec#*:}"
  if [[ ! -e "$HERMES_HOME/$dst" ]]; then
    cp "$PRODUCT_ROOT/$src" "$HERMES_HOME/$dst"
  fi
done
for skill_dir in "$PRODUCT_ROOT"/skills/*/*/; do
  [[ -d "$skill_dir" ]] || continue
  name="$(basename "$skill_dir")"; category="$(basename "$(dirname "$skill_dir")")"
  if [[ ! -e "$HERMES_HOME/skills/$category/$name" ]]; then
    mkdir -p "$HERMES_HOME/skills/$category"
    cp -R "$skill_dir" "$HERMES_HOME/skills/$category/$name"
  fi
done

# Existing memory deployments keep their stack/config; a reinstall must never change DB wiring.
if [[ ! -d "$HERMES_HOME/honcho" ]]; then
  cp -R "$PRODUCT_ROOT/honcho" "$HERMES_HOME/honcho"
  # The image runs as its own unprivileged user and reads these public bind mounts.
  chmod 0644 "$HERMES_HOME/honcho/config.toml" "$HERMES_HOME/honcho/database/init.sql"
fi
cp "$PRODUCT_ROOT/bin/luna" "$HERMES_HOME/bin/luna"
chmod 0755 "$HERMES_HOME/bin/luna"
mkdir -p "$HOME/.local/bin"
ln -sf "$HERMES_HOME/bin/luna" "$HOME/.local/bin/luna"

# Install service definitions only. Do not invoke the engine systemd_install helper: its
# legacy-unit cleanup can stop an unrelated working Hermes deployment. Generate the same
# CLI-owned name/body without cleanup, enablement, or any gateway start/restart.
if [[ "${SKIP_SYSTEMD:-0}" == "0" ]] && command -v systemctl >/dev/null 2>&1; then
  "$HERMES_HOME/venv/bin/python" "$PRODUCT_ROOT/deploy/install_units.py"
  systemctl --user daemon-reload || echo "==> user service manager unavailable; service definitions are ready for the next login"
fi

echo "==> Luna installed at $HERMES_HOME"
echo "    Open setup: $HOME/.local/bin/luna dashboard"
echo "    Gateway services have not been started. Connect from the dashboard when ready."
