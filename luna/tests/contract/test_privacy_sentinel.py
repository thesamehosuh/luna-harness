"""Privacy sentinel: no real Telegram ids or chat ids in tracked Luna files.

Golden rule 6 — secrets and member PII never enter the repo. This scans every tracked Luna
source/config/doc for 9–11 digit tokens that look like Telegram user or chat ids and fails on
anything outside the known-synthetic set. Synthetic fixtures use the ``10000000xx`` series,
epoch seconds look like ``17xxxxxxxx``, and the only real external id allowed is Telegram's own
public ``GroupAnonymousBot`` constant.
"""

from __future__ import annotations

import re
from pathlib import Path

LUNA_ROOT = Path(__file__).resolve().parents[2]
SCAN_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".sh", ".service", ".timer", ".toml"}
_TOKEN_RE = re.compile(r"(?<![\w.+-])\d{9,11}(?![\w.+-])")

# 10000000xx synthetic member ids; 17xxxxxxxx epoch seconds (2023-2026); 1087968824 is
# Telegram's public GroupAnonymousBot user id (documented platform constant, not member PII).
_SYNTHETIC_PREFIXES = ("1000000", "17")
_PUBLIC_IDS = {"1087968824"}


def _tracked_files():
    for path in sorted(LUNA_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def test_no_real_telegram_ids_in_tracked_files():
    offenders = []
    for path in _tracked_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _TOKEN_RE.finditer(text):
            token = match.group(0)
            # Pinned public artifact sizes are not transport IDs. Exempt only
            # the numeric `bytes` field here; other fields in this manifest
            # and every other source/config continue through the same scan.
            if path.relative_to(LUNA_ROOT).as_posix() == "lib/luna_core/embedding-model.json":
                prefix = text[text.rfind("\n", 0, match.start()) + 1:match.start()]
                if re.search(r'"bytes"\s*:\s*$', prefix):
                    continue
            if token in _PUBLIC_IDS:
                continue
            if token.startswith(_SYNTHETIC_PREFIXES):
                continue
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(LUNA_ROOT)}:{line}: {token}")
    assert not offenders, "possible real Telegram ids in tracked files:\n" + "\n".join(offenders)
