"""The static-message catalogs must speak as Luna, and stay in parity across all 17 locales.

`locales/*.yaml` holds the user-facing static messages for the CLI approval prompt and the gateway
slash-command replies. Every one of them shipped with the engine's name in it: `/help` and `/status`
headers said "Hermes Commands" / "Hermes Gateway Status", and the hints told people to run
`hermes config set …`, `hermes debug share`, `hermes kanban …`, `hermes gateway restart`,
`hermes update` — none of which exist under the name `luna` prints.

The subtlety that makes this worth a guard rather than a review habit: the catalogs are *values only*.
Keys are a contract shared by the loader (`gateway/slash_commands.py`) and by all 17 files at once, so
a rename is a 17-file breaking change and this phase explicitly keeps every key. That leaves exactly
one legitimate `hermes` in the tree — the key `gateway.update.hermes_cmd_not_found` — so the guard can
be precise about it instead of fuzzy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCALES = REPO_ROOT / "locales"

# The one `hermes` that is allowed to remain: an internal key, read by the loader and never rendered.
ALLOWED_KEY = "hermes_cmd_not_found"

# `Hermes` followed by a *Latin* word character. Deliberately not `\b`: Korean attaches a subject
# particle straight onto the name ("Hermes는"), and `\b` cannot match that because `는` is a Unicode
# word character -- which is exactly how one locale survived a first pass with the brand intact.
BRAND = re.compile(r"\bHermes(?![A-Za-z0-9_])")
# The command name as a whole word: not part of a path, not part of a longer identifier.
COMMAND = re.compile(r"(?<![\w./-])hermes(?![\w-])")
HOME_PATH = re.compile(r"~/\.hermes/")


def _locale_files() -> list[Path]:
    files = sorted(LOCALES.glob("*.yaml"))
    assert len(files) == 17, f"expected 17 locales, found {len(files)}: {[f.name for f in files]}"
    return files


def _leaf_keys(node, prefix: str = "") -> list[str]:
    out: list[str] = []
    for key, value in (node or {}).items():
        path = f"{prefix}{key}"
        out.append(path)
        if isinstance(value, dict):
            out.extend(_leaf_keys(value, f"{path}."))
    return out


@pytest.mark.parametrize("path", _locale_files(), ids=lambda p: p.name)
def test_locale_speaks_as_luna(path: Path):
    """No engine brand, command, or home path survives in any catalog value or comment."""
    text = path.read_text(encoding="utf-8")

    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # A key line may legitimately contain the word, in the key only.
        key_part, sep, _value = stripped.partition(":")
        if sep and key_part.strip() == ALLOWED_KEY:
            assert BRAND.search(_value) is None, (
                f"{path.name}:{lineno} the {ALLOWED_KEY} value still brands the engine: {_value}"
            )
            assert HOME_PATH.search(_value) is None, f"{path.name}:{lineno} engine home path in value"
            assert not COMMAND.search(_value), (
                f"{path.name}:{lineno} the value still tells the user to run `hermes`: {_value}"
            )
            continue

        assert BRAND.search(line) is None, f"{path.name}:{lineno} still says Hermes: {stripped}"
        assert HOME_PATH.search(line) is None, f"{path.name}:{lineno} still uses ~/.hermes: {stripped}"
        if sep:
            assert not COMMAND.search(_value), (
                f"{path.name}:{lineno} still tells the user to run `hermes`: {_value}"
            )
        else:
            assert not COMMAND.search(line), (
                f"{path.name}:{lineno} still names the `hermes` command: {stripped}"
            )


@pytest.mark.parametrize("path", _locale_files(), ids=lambda p: p.name)
def test_locale_keys_match_the_english_baseline(path: Path):
    """Values were changed; keys must not have been.

    `tests/agent/test_i18n.py` asserts this too, but that is upstream CI's tree. This is the guard
    that runs in `scripts/test.sh`, so a key added to one locale and not the others cannot reach a
    merge on the strength of a test nobody runs locally.
    """
    english = sorted(_leaf_keys(yaml.safe_load((LOCALES / "en.yaml").read_text(encoding="utf-8"))))
    other = sorted(_leaf_keys(yaml.safe_load(path.read_text(encoding="utf-8"))))
    assert other == english, (
        f"{path.name} key set differs from en.yaml: "
        f"missing={sorted(set(english) - set(other))} extra={sorted(set(other) - set(english))}"
    )


def test_the_one_allowed_hermes_key_still_exists_and_is_the_only_one():
    """Pin the exception, so a future rename cannot silently change what is exempt."""
    offenders: list[str] = []
    for path in _locale_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in _leaf_keys(data):
            if "hermes" in key.lower():
                offenders.append(f"{path.name}: {key}")
    # One entry per locale: the same key, seventeen times.
    assert len(offenders) == 17, f"expected exactly one hermes-named key per locale: {offenders}"
    assert {o.rsplit(":", 1)[1].strip() for o in offenders} == {
        f"gateway.update.{ALLOWED_KEY}"
    }, offenders
