# Contributing to Luna

Luna is the harness; every user creates their own companion. Read [PRODUCT_PLAN.md](PRODUCT_PLAN.md)
and [AGENTS.md](AGENTS.md) before proposing product changes. User tasks belong in the dashboard.

Use [Luna issues](https://github.com/thesamehosuh/luna-harness/issues) for bugs and feature proposals.
Include the operating system, release version, steps to reproduce and expected behavior. Redact
credentials, transport IDs, people and personal chat history from examples and logs.

## Development

Use Python 3.11–3.13, uv, and a supported Node/npm version. Native launcher development also needs
Rust and the platform's Tauri prerequisites. Install source dependencies with `uv sync --extra luna`
and `npm ci`; install `luna/lib` editable and pytest/pytest-asyncio for the Python tests. Use a
disposable `LUNA_HOME`/`HERMES_HOME`, never your real companion's home, when testing changes.

- Run `scripts/test.sh` with `PYTHON` and `HERMES_PY` pointing to your test interpreter.
- Run dashboard tests/type checking with `npm test --workspace web` and
  `npm run typecheck --workspace web`.
- Packaging changes require `scripts/test-release.sh` and the native release workflow.
- Add a deterministic replay fixture when fixing identity or wake behavior. Network is off by
  default; live tests must be explicitly selected and must not post into real groups accidentally.

Prefer product changes under `luna/`. Engine edits are allowed, but record them in
[luna/docs/engine-vendor.md](luna/docs/engine-vendor.md) and preserve the contract tests.
Dynamic room/memory content must stay out of cached system/channel prompts. Preserve transport-ID
identity, one Telegram poller, silence-first wake thresholds and code-enforced group limits.
New settings need defaults, validation and dashboard controls together.

Submit focused commits and describe the user-visible problem, resulting behavior and verification.
Keep upstream license/NOTICE attribution. Report vulnerabilities through [SECURITY.md](SECURITY.md).
