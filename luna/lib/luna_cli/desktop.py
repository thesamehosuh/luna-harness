"""Start only the dashboard for the owned native launcher.

The inherited stdin pipe is a lifetime lease: EOF means the launcher has gone,
even if its OS PID is later reused. Gateways remain an explicit dashboard action.
"""
from pathlib import Path
import os
import signal
import sys
import threading


def main():
    from luna_cli.main import luna_home
    os.environ["HERMES_HOME"] = luna_home()
    os.environ.pop("LUNA_HOME", None)
    root = Path(__file__).resolve().parents[3]
    os.environ["HERMES_WEB_DIST"] = str(root / "hermes_cli/web_dist")
    if not os.environ.get("LUNA_DESKTOP_NONCE") or not os.environ.get("HERMES_DASHBOARD_SESSION_TOKEN"):
        raise RuntimeError("The desktop backend must be started by its launcher")
    from hermes_cli.product_runtime import seed_home
    seed_home(Path(os.environ["HERMES_HOME"]))
    # Finish the engine's import/bootstrap chain before any restore thread can
    # import its legacy `utils` alias concurrently.
    from hermes_cli.web_server import start_server
    from luna_core.managed_memory import restore
    threading.Thread(target=restore, daemon=True, name="luna-memory-restore").start()
    def watch():
        try:
            # Avoid a daemon thread holding BufferedReader's lock when a
            # startup exception sends Python into interpreter shutdown.
            while os.read(sys.stdin.fileno(), 1):
                pass
        finally:
            os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=watch, daemon=True, name="luna-launcher-lease").start()
    start_server(host="127.0.0.1", port=0, open_browser=False)


if __name__ == "__main__":
    main()
