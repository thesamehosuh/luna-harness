"""Luna distribution identity and launch paths, before any profile or provider imports."""
from pathlib import Path
import os
import sys
import tempfile
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent


def enabled():
    return (ROOT / "luna-release.json").is_file()


def default_home_name():
    return ".luna" if enabled() else ".hermes"


def installation_home(home):
    home = Path(home)
    return home.parent.parent if home.parent.name == "profiles" else home


def code_root(home):
    install = installation_home(home).resolve()
    marker = install / "current-release.json"
    if marker.is_file():
        record = json.loads(marker.read_text(encoding="utf-8"))
        target = (install / record["path"]).resolve()
        if target.parent != install / "releases" or not (target / ".ready").is_file():
            raise ValueError("Invalid Luna release pointer; repair this installation")
        return target
    current = install / "current"
    return current.resolve() if current.is_dir() else ROOT


def executable(home):
    for root in (code_root(home), installation_home(home)):
        for name in ("venv/bin/python", "venv/Scripts/python.exe"):
            path = root / name
            if path.is_file():
                return str(path)
    return sys.executable


def cli_module():
    return "luna_cli.main" if enabled() else "hermes_cli.main"


def child_environment(env, home):
    env = dict(env)
    if enabled():
        root = code_root(home)
        env.update(HERMES_HOME=str(home), LUNA_HOME=str(home), LUNA_PRODUCT="1",
                   HERMES_PYTHON=executable(home), HERMES_PYTHON_SRC_ROOT=str(root),
                   PYTHONPATH=os.pathsep.join((str(root / "luna/lib"), str(root))))
        # A previous Hermes checkout's TUI must never be selected for this product.
        env.pop("HERMES_TUI_DIR", None)
        git_path = installation_home(home) / ".luna-git-bash"
        if os.name == "nt" and git_path.is_file():
            bash = Path(git_path.read_text(encoding="utf-8-sig").strip())
            if bash.is_file():
                env["HERMES_GIT_BASH_PATH"] = str(bash)
                env["PATH"] = str(installation_home(home) / "git/cmd") + os.pathsep + env.get("PATH", "")
        node = root / ("runtime/node/node.exe" if os.name == "nt" else "runtime/node/bin/node")
        if node.is_file():
            env["HERMES_NODE"] = str(node)
    return env


def default_soul():
    path = ROOT / "luna/soul/DEFAULT.md"
    return path.read_text(encoding="utf-8") if enabled() and path.is_file() else None


def product_defaults(defaults, *, runtime_fallbacks=False):
    """New-user product defaults, never derived from an installed user's configuration."""
    if not enabled():
        return defaults
    import copy
    import yaml

    def merge(base, override):
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merge(base[key], value)
            else:
                base[key] = copy.deepcopy(value)
        return base

    template = yaml.safe_load((ROOT / "luna/config/config.yaml.luna").read_text(encoding="utf-8"))
    if runtime_fallbacks:
        # Setup completion is persisted state. Legacy configured homes predate it.
        # A default URL must also never shadow an existing honcho.json connection.
        template["luna"].pop("setup", None)
        template["honcho"].pop("baseUrl", None)
        # Provider selection is explicit state too: a deleted custom endpoint
        # must not silently reroute its retained model name into OpenCode.
        template.pop("model", None)
    return merge(copy.deepcopy(defaults), template)


def seed_home(home, *, skills=True):
    """First-run product files, including named profiles. Never replace user-owned files."""
    if not enabled():
        return
    home = Path(home)
    files = [(ROOT / "luna/config/config.yaml.luna", home / "config.yaml"),
             (ROOT / "luna/assets/PEOPLE.md", home / "PEOPLE.md"),
             (ROOT / "luna/config/honcho.json.luna", home / "honcho.json"),
             (ROOT / "luna/config/skins/luna.yaml", home / "skins/luna.yaml")]
    if skills:
        files.extend((path, home / "skills" / path.relative_to(ROOT / "luna/skills"))
                     for path in (ROOT / "luna/skills").rglob("*") if path.is_file())
    for source, target in files:
        if target.exists() or not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".luna-seed-")
        try:
            content = source.read_bytes()
            if target.name in {"config.yaml", "honcho.json"}:
                workspace = "luna_" + hashlib.sha256(str(home.resolve()).encode()).hexdigest()[:16]
                if target.name == "honcho.json":
                    value = json.loads(content)
                    value.setdefault("hosts", {}).setdefault("hermes", {})["workspace"] = workspace
                    content = (json.dumps(value, indent=2) + "\n").encode()
                else:
                    content = content.replace(b'workspace: luna', ("workspace: " + workspace).encode())
            with os.fdopen(fd, "wb") as output:
                output.write(content)
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)


FALLBACK_IDENTITY = "You are a personal AI companion. Your character, voice and name are configured in Luna's dashboard."
HELP_GUIDANCE = (
    "You run in Luna, a self-hosted personal companion harness. The owner configures character, "
    "models, Telegram, memory, behaviour and recovery through the Luna dashboard. Use its Help "
    "page and installed Luna documentation/schema for product setup and troubleshooting. "
    "The vendored Hermes engine is an implementation detail; upstream setup and update commands "
    "do not manage this Luna installation."
)


def version():
    import json
    return json.loads((ROOT / "luna-release.json").read_text())["version"] if enabled() else ""


def provider_configured():
    from hermes_cli.config import load_config_readonly
    cfg = load_config_readonly().get("model") or {}
    if not isinstance(cfg, dict) or not str(cfg.get("default") or "").strip():
        return False
    if cfg.get("provider") == "opencode-engine":
        from luna_core.opencode_install import find_binary
        return str(cfg["default"]).startswith("opencode/") and find_binary() is not None
    return bool(cfg.get("provider") or cfg.get("base_url"))
