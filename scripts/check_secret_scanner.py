#!/usr/bin/env python3
"""Prove that the configured gate catches synthetic credentials without logging them."""
import base64
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
scanner = sys.argv[1]
with tempfile.TemporaryDirectory(prefix="luna-scanner-probe-") as directory:
    home = Path(directory)
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    jwt = ".".join([encode({"alg": "HS256", "typ": "JWT"}), encode({"sub": "synthetic-scanner-probe"}), "synthetic_signature_for_a_test"])
    (home / "probe.env").write_text("\n".join([
        "TELEGRAM_BOT_TOKEN=" + "9847362510" + ":" + base64.urlsafe_b64encode(hashlib.sha256(b"synthetic-bot-probe").digest()).decode()[:35],
        "OPENAI_API_KEY=" + "sk-" + "abcdefgh0123456789" * 3,
        "ACCESS_TOKEN=" + jwt,
    ]))
    result = subprocess.run([scanner, "dir", str(home), "--config", str(root / ".gitleaks.toml"), "--redact", "--no-banner", "--report-format", "json", "--report-path", str(home / "report.json")], capture_output=True)
    if result.returncode != 1:
        raise SystemExit("Secret scanner failed its rejection probe")
    rules = {row["RuleID"] for row in json.loads((home / "report.json").read_text())}
    if not {"luna-telegram-token", "luna-chatgpt-session", "luna-openai-key"} <= rules:
        raise SystemExit("Secret scanner did not detect every required credential type: " + ", ".join(sorted(rules)))
print("Synthetic Telegram, account-session and API-key probes rejected.")
