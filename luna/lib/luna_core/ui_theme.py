"""Shared Luna palettes for server-rendered screens and terminal surfaces."""
from pathlib import Path
import json
import base64
import html
import re

ASSETS = Path(__file__).resolve().parents[2] / "assets/ui"


def palette(name=None):
    if name is None:
        from hermes_cli.config import load_config_readonly
        dashboard = load_config_readonly().get("dashboard")
        name = dashboard.get("theme", "sakura-dusk") if isinstance(dashboard, dict) else "sakura-dusk"
    themes = json.loads((ASSETS / "themes.json").read_text(encoding="utf-8"))
    return themes.get(name, themes["sakura-dusk"]) if isinstance(name, str) else themes["sakura-dusk"]


def auth_css():
    theme = palette()
    values = {**theme["colors"], "canvas": theme["background"], "ink": theme["foreground"], "scheme": theme["colorScheme"]}
    css = (ASSETS / "auth.css").read_text(encoding="utf-8")
    for key, value in values.items():
        css = css.replace("@@" + key + "@@", value)
    return css


def bootstrap_css(name):
    theme = palette(name)
    values = {"--background": theme["background"], "--background-base": theme["background"],
              "--midground": theme["foreground"], "--midground-base": theme["foreground"],
              "color-scheme": theme["colorScheme"]}
    for key, value in theme["colors"].items():
        kebab = "".join("-" + character.lower() if character.isupper() else character for character in key)
        values["--color-" + kebab] = value
    return '<style id="luna-builtin-theme">:root:not([data-dashboard-theme]){' + ";".join(key + ":" + value for key, value in values.items()) + "}</style>"


def embedded_font_css():
    """Offline typography for downloaded exports and single-route OAuth callbacks."""
    root = ASSETS.parents[2]
    rules = []
    for family, directory, filename, kind, weight in [
        ("Manrope", "fonts-luna", "Manrope-Variable.ttf", "truetype", "200 800"),
        ("DM Serif Display", "fonts-luna", "DMSerifDisplay-Regular.ttf", "truetype", "400"),
        ("JetBrains Mono", "fonts-terminal", "JetBrainsMono-Regular.woff2", "woff2", "400"),
    ]:
        candidates = [root / "hermes_cli/web_dist" / directory / filename, root / "web/public" / directory / filename]
        path = next((path for path in candidates if path.is_file()), None)
        if path:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            mime = "font/woff2" if kind == "woff2" else "font/ttf"
            rules.append(f"@font-face{{font-family:'{family}';font-weight:{weight};font-display:swap;src:url(data:{mime};base64,{data}) format('{kind}')}}")
    return "\n".join(rules)


def font_notices():
    root = ASSETS.parents[2]
    notices = []
    for directory, name in [("fonts-luna", "Manrope-OFL.txt"), ("fonts-luna", "DMSerifDisplay-OFL.txt"), ("fonts-terminal", "JetBrainsMono-OFL.txt")]:
        candidates = [root / "hermes_cli/web_dist" / directory / name, root / "web/public" / directory / name]
        path = next((path for path in candidates if path.is_file()), None)
        if path:
            notices.append(html.escape(path.read_text(encoding="utf-8")))
    return '<template id="luna-font-notices"><pre>' + "\n\n".join(notices) + "</pre></template>"


def document(title, body):
    css = re.sub(r"@font-face\s*\{[^}]*\}", "", auth_css())
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{embedded_font_css()}{css}</style>{font_notices()}</head>'
            f'<body><main class="card">{body}</main></body></html>')


def export_css():
    theme = palette()
    colors = theme["colors"]
    values = {"bg-color": theme["background"], "text-color": theme["foreground"],
              "secondary-text": colors["mutedForeground"], "user-bg": colors["card"],
              "assistant-bg": colors.get("secondary", colors["muted"]), "border-color": colors["border"],
              "accent-color": colors["primary"], "accent-foreground": colors["primaryForeground"],
              "code-bg": colors["muted"], "code-text": theme["foreground"],
              "reasoning-bg": colors["muted"], "reasoning-border": colors["border"],
              "tool-bg": colors.get("secondary", colors["muted"]), "tool-border": colors["border"], "sidebar-bg": colors["card"]}
    return embedded_font_css() + ":root{" + ";".join("--" + key + ":" + value for key, value in values.items()) + ";--sidebar-width:320px;color-scheme:" + theme["colorScheme"] + "}h1{font-family:'DM Serif Display',Georgia,serif;font-weight:400}"


def logo_svg():
    root = ASSETS.parents[2]
    for path in (root / "hermes_cli/web_dist/luna-mark.svg", root / "web/public/luna-mark.svg"):
        if path.is_file():
            return re.sub(r"<svg\b", '<svg style="width:1.5rem;height:1.5rem;flex-shrink:0"', path.read_text(encoding="utf-8"), count=1)
    return ""
