#!/usr/bin/env python3
"""GPU fan guard — kill GPU load before the card hangs.

Why fan speed and NOT temperature: on the hang-prone card class this runs on (RX 580 / gfx803),
the crash mode is loss of fan speed control — the fan defaults to full blast (`fan1_max` RPM)
while temperature still reads modestly. The tachometer is the leading indicator.

On trigger: stop the CLM stack and kill any GPU batch runner immediately, then keep watching.
If the fan is still pinned 20s later, say so loudly (the hang may already be irreversible —
killing user processes is the only lever left).

Usage:
    python3 gpu_fan_guard.py                 # autodetects the amdgpu hwmon
    python3 gpu_fan_guard.py --hwmon /sys/class/hwmon/hwmon1
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

NEAR_MAX_FRAC = 0.85        # >= 85% of fan1_max = control likely lost
JUMP_FACTOR = 2.0           # doubling within JUMP_WINDOW with floor = jump signature
JUMP_FLOOR_RPM = 1500
JUMP_WINDOW = 3             # seconds
POLL = 1.0
KILL_REPEAT = 20.0          # seconds between repeated kill attempts

DEFAULT_PATTERNS = [
    r"run_backends\.py",
    r"extract_embeddings\.py",
    r"llama-server",
    r"clm-serve",
    r"luna_paced\.py",
    r"luna_clm_only\.py",
]


def find_amdgpu_hwmon() -> Path | None:
    for d in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            if (d / "name").read_text().strip() == "amdgpu" and (d / "fan1_input").exists():
                return d
        except OSError:
            continue
    return None


class Guard:
    def __init__(self, hwmon: Path, patterns: list[str], log_path: Path | None):
        self.fan_input = hwmon / "fan1_input"
        self.pwm = hwmon / "pwm1"
        self.fan_max = self._fan_max(hwmon)
        self.patterns = patterns
        self.log_path = log_path

    @staticmethod
    def _fan_max(hwmon: Path) -> int:
        try:
            return int((hwmon / "fan1_max").read_text().strip()) or 3500
        except OSError:
            return 3500

    def log(self, msg: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
        print(line, flush=True)
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def read_fan(self) -> tuple[int, int]:
        rpm = int(self.fan_input.read_text().strip())
        pwm = int(self.pwm.read_text().strip()) if self.pwm.exists() else -1
        return rpm, pwm

    def kill_gpu_load(self) -> None:
        self.log("TRIGGER: killing GPU workloads")
        try:
            subprocess.run(["clm", "stop"], capture_output=True, timeout=30)
        except Exception as exc:
            self.log(f"  clm stop failed: {exc}")
        pat = "|".join(self.patterns)
        try:
            out = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=10)
            pids = [p for p in out.stdout.split() if p and int(p) != os.getpid()]
            if pids:
                subprocess.run(["kill", "-TERM", *pids], capture_output=True, timeout=10)
                self.log(f"  SIGTERM -> pids {pids}")
                time.sleep(2)
                subprocess.run(["kill", "-KILL", *pids], capture_output=True, timeout=10)
            else:
                self.log("  no batch/encoder processes found")
        except Exception as exc:
            self.log(f"  pkill failed: {exc}")

    def run(self) -> None:
        self.log(f"guard up: fan1_max={self.fan_max} near-max={NEAR_MAX_FRAC:.0%} "
                 f"jump>={JUMP_FACTOR}x & >={JUMP_FLOOR_RPM}RPM over {JUMP_WINDOW}s")
        recent: list[tuple[float, int]] = []
        last_kill = 0.0
        triggered_at: float | None = None
        while True:
            try:
                rpm, pwm = self.read_fan()
            except OSError as exc:
                self.log(f"read failed: {exc}")
                time.sleep(POLL)
                continue
            now = time.monotonic()
            recent.append((now, rpm))
            recent = [(t, r) for t, r in recent if now - t <= JUMP_WINDOW]

            near_max = rpm >= NEAR_MAX_FRAC * self.fan_max
            base = min((r for _, r in recent[:-1]), default=rpm)
            jump = rpm >= JUMP_FLOOR_RPM and base > 0 and rpm >= JUMP_FACTOR * base
            step = rpm >= JUMP_FLOOR_RPM and base <= JUMP_FLOOR_RPM // 2

            if (near_max or jump or step) and now - last_kill > KILL_REPEAT:
                self.log(f"fan anomaly: rpm={rpm}/{self.fan_max} pwm={pwm} "
                         f"(near_max={near_max} jump={jump} step={step})")
                self.kill_gpu_load()
                last_kill = now
                triggered_at = triggered_at or now
            elif triggered_at and now - triggered_at > 20 and near_max:
                self.log(f"STILL PINNED at {rpm} RPM after 20s — hang may be irreversible, "
                         f"save your work / prepare for reboot")
                triggered_at = now
            elif not near_max and triggered_at and now - last_kill > 30:
                self.log(f"fan recovered: rpm={rpm} — standing by")
                triggered_at = None
            time.sleep(POLL)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwmon", default=None, help="hwmon dir (default: autodetect amdgpu)")
    ap.add_argument("--kill-pattern", action="append", default=None,
                    help="extra pgrep -f patterns of GPU workloads to kill (repeatable)")
    ap.add_argument("--log", default=str(Path.home() / ".luna/gpu_fan_guard.log"))
    a = ap.parse_args()

    hwmon = Path(a.hwmon) if a.hwmon else find_amdgpu_hwmon()
    if hwmon is None or not (hwmon / "fan1_input").exists():
        sys.exit("no amdgpu fan sensor found — pass --hwmon /sys/class/hwmon/hwmonN")
    guard = Guard(hwmon, DEFAULT_PATTERNS + (a.kill_pattern or []),
                  Path(a.log) if a.log else None)
    signal.signal(signal.SIGTERM, lambda *_: (guard.log("guard stopped"), sys.exit(0)))
    guard.run()


if __name__ == "__main__":
    main()
