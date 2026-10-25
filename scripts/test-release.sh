#!/usr/bin/env bash
# Build and install a release outside the checkout. No real services or credentials are used.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/luna-release-check.XXXXXX")"
trap 'rm -rf "$OUT"' EXIT
PY="${PYTHON:-python3}"
"$PY" "$ROOT/luna/deploy/build-release.py" "$OUT"
ARTIFACT=("$OUT"/*.tar.gz)
"$PY" "$ROOT/scripts/release_smoke.py" "${ARTIFACT[0]}"
