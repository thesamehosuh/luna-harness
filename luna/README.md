# luna/ — Luna harness overlay

This directory contains Luna’s product overlay; the dashboard and launcher also carry product code. Prefer adding capabilities
here (plugins, `luna_core`, templates) over editing engine files; when an engine file must change,
the edit is minimal, tested, and recorded in `luna/docs/engine-vendor.md` (see `AGENTS.md` §2).

The product roadmap is at `../PRODUCT_PLAN.md`. For installation, use the [main README](../README.md) and [public downloads](https://github.com/thesamehosuh/luna-harness/releases).
Luna names the harness. Each user chooses the name and identity of their own companion.

## Layout

| Path | What |
|---|---|
| `config/` | `config.yaml.luna`, `honcho.json.luna`, `skins/luna.yaml` (templates) |
| `soul/DEFAULT.md` | Neutral new-user persona, seeded as the profile's `SOUL.md` |
| `soul/SOUL.md` | Optional Luna example character; not the default persona |
| `plugins/luna-room/` | Roster + reply-chain reconstruction; stages the bounded room/identity block via the ephemeral sidecar |
| `plugins/luna-memory/` | Vendored+extended Honcho provider: per-identity attribution, tiers, budget, scope |
| `plugins/luna-ambient/` | Thin jev client + conservative self-wake cascade + proactive wake |
| `plugins/luna-logger/` | Tokenless indexer: tails the `state.db` observe transcript into `luna-state.db` |
| `deploy/` | `assemble.sh`, `install.sh`, `migrate-from-hermes.sh`, `rollback.sh` |
| `honcho/` | Honcho deployment: `docker-compose.yml`, `config.toml`, `init.sql`, go-shim, `.env.template` |
| `systemd/` | `hermes-gateway`, `luna-logger`, `honcho-go-shim` units |
| `tests/` | `unit/`, `component/`, `contract/`, `replay/`, `fixtures/` |
| `vendor/plugins.lock` | Pinned third-party plugins by sha |
| `docs/` | Engineering records that gate development: `engine-vendor`, `testing`, `upstream-sync`, `jev`. User-facing knowledge lives in the dashboard Help page. |

## Golden rules (short form)

1. Engine files may carry Luna edits — keep them minimal and record every one in
   `docs/engine-vendor.md`.
2. The prompt cache is sacred — per-turn dynamic content rides the ephemeral sidecar, never the
   system prompt or `channel_prompt`.
3. Identity is code-level — peers come only from transport ids via `luna_identity`.
4. One Telegram bot token — the gateway is the sole `getUpdates` consumer.
5. Silence is the default — self-wakes are rare and gated.

See `../AGENTS.md` for the full guide.
