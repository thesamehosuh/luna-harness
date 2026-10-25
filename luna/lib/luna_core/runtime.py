"""The companion's profile boundary. Never fall back from a scoped secret to process state."""
from pathlib import Path
import os


def home() -> Path:
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        return Path(os.getenv("LUNA_HOME") or os.getenv("HERMES_HOME") or "~/.luna").expanduser()
    return Path(get_hermes_home()).expanduser()


def getenv(name, default=None):
    try:
        from agent.secret_scope import get_secret
    except ImportError:
        return os.getenv(name, default)
    return get_secret(name, default)


def worker_context():
    """Freeze the owning home and credentials before starting a long-lived worker.

    A primary worker can start before the gateway enables multiplexing. Copying an empty
    secret context would then break when a secondary profile is opened later.
    """
    import contextvars
    from hermes_constants import get_process_hermes_home, set_hermes_home_override
    from agent.secret_scope import current_secret_scope, build_profile_secret_scope, set_secret_scope
    root = home()
    secrets = current_secret_scope()
    if secrets is None:
        secrets = dict(os.environ) if root.resolve() == get_process_hermes_home().resolve() else {}
        secrets.update(build_profile_secret_scope(root))
    context = contextvars.copy_context()
    context.run(set_hermes_home_override, root)
    context.run(set_secret_scope, dict(secrets))
    return context
