# AGENTS.md — Luna

Luna is an open-source harness for a **personal AI companion**: a character at home in your group
chats, and a capable assistant in your DMs. This repo is the product. The roadmap is
`PRODUCT_PLAN.md`; read it before planning feature work.

Users configure Luna through the **dashboard**, never the terminal and never hand-edited YAML.
Terminal commands exist for development and debugging only, and the product goal is to shrink them
over time (see PRODUCT_PLAN.md P5).

---

## 1. What Luna is

- **Companion-first.** In group chats the user's companion is a member of the room: shaped output (short, no emoji
  spam, no other members' personal details), judgement about when to speak, memory of the people in
  the room. In the owner's DM the companion is a full-capability assistant (tools, files, terminal, cron).
- **Luna is the harness. Every user makes their own companion.** Name, persona, voice, wake behaviour, and memory are configuration,
  edited in the dashboard (character creator, wake tuning, people/identity pages). The shipped
  persona (`luna/soul/SOUL.md`) is an example character, not the product's fixed identity.
- **Self-hosted.** Your keys, your server, your chat history. Honcho (memory) runs as a local
  docker stack; the model provider is any OpenAI-compatible endpoint.

## 2. Repo layout

| Path | What |
|---|---|
| root (`agent/`, `gateway/`, `tools/`, `hermes_cli/`, `tui_gateway/`, `web/`, …) | **Vendored engine** — hermes-agent 0.21.3 (see `NOTICE`). |
| `luna/` | **Product overlay** — companion plugins, config templates, persona, deploy, skills, tests. |
| `web/` + `hermes_cli/web_routers/` | **Dashboard** — the product UI (kept + extended per PRODUCT_PLAN.md P2–P4). |
| `luna/docs/engine-vendor.md` | Inventory of every Luna edit to engine files (folds the pre-P1 `luna/patches/` series). |
| `luna/deploy/` | `assemble.sh` (slim runtime), `install.sh`, `migrate-from-hermes.sh`, `rollback.sh`. |
| `PRODUCT_PLAN.md`, `NOTICE` | Roadmap; license attribution for the vendored engine. |

## 3. Invariants (do not break)

1. **The prompt cache is sacred.** Per-turn dynamic content (room roster, reply chains, memory
   recall, digests) rides the ephemeral sidecar path (`_set_pending_turn_sidecar_notes`) or the
   bounded user-message recall block. Never the system prompt or `channel_prompt` (both enter the
   cached-agent signature). Contract-tested.
2. **Identity is code-level certainty.** Peers derive only from transport ids via the
   `luna_identity` registry (`luna-state.db`). Never infer identity from message text, display
   names, or model output.
3. **One Telegram poller.** The gateway is the sole `getUpdates` consumer (Telegram answers 409
   otherwise). Room history arrives via `observe_unmentioned_group_messages` → `state.db` → the
   tokenless `luna-logger` indexer.
4. **Silence is the default.** Self-wakes are rare and strictly gated by the cascade. Never loosen
   wake thresholds without replay-harness evidence.
5. **No secrets in the repo.** No tokens, keys, chat ids, or user PII in tracked files. Templates
   use placeholders; real values live in the untracked runtime `.env`.
6. **Surface policy is code, not just prompt.** Group length/emoji/privacy limits are enforced in
   `luna/lib/luna_core/text.py` + `luna-room`'s output transform, configurable via `luna.output.*`.
7. **Security defaults hold.** Chat surfaces may never create shell-backed cron jobs (engine edit
   0013); cron runs carry a toolset denylist (engine edit 0012); file writes go through the
   edit-approval guard.

## 4. Engine policy (vendored)

- The engine is **vendored** hermes-agent 0.21.3 (`59f9ff8dbc`), MIT. This repo owns its own
  history; upstream updates are deliberate re-vendors, not routine merges. Record each re-vendor
  (version, commit, notes) in `luna/docs/engine-vendor.md`.
- Prefer product code under `luna/`. Engine files **may** be edited here (this is the product's
  tree, not a fork that must stay mergeable) — but keep engine edits minimal, tested, and listed in
  `luna/docs/engine-vendor.md` so re-vendors stay cheap.
- The private-API contract tests (`luna/tests/contract/`) still gate re-vendors: they pin the
  engine symbols the overlay depends on.

## 5. Testing

```bash
scripts/test.sh            # luna unit + component + contract + replay (+ engine subset)
scripts/test-contract.sh   # engine private-API contract set
```

- Test home: `luna/tests/{unit,component,contract,replay,fixtures}`. Every branch of the identity
  write path and the wake cascade has a test. The replay corpus is the regression gate for
  identity + wake bugs; add a fixture whenever one is fixed.
- Determinism: injected clock, UTC, seeded RNG, no network by default. jev tests use recorded
  fixtures unless `--live` with `OPENCODE_API_KEY`. Honcho tests use a local `docker compose`
  workspace (`luna-test`).

## 6. Where to put things

- New companion capability → `luna/plugins/` or `luna/lib/luna_core/` first.
- New dashboard page → `web/src/pages/` + a router in `hermes_cli/web_routers/` (or a `luna/`
  router module mounted by the web server). Never require a config-file edit for a user task.
- Character/voice behavior → `luna/soul/`, `luna/skills/`, `luna.output.*` config keys.
- New config keys → `luna/config/config.yaml.luna` template **and** the dashboard config schema
  (P2) — a key that only exists in raw YAML is not done.

## 7. Standing constraints

- Deploy scripts never restart the gateway; restarts are the operator's action.
- The self-wake reaction tier ships disabled (`luna.ambient.reactions.allowed: []`); it is opt-in.
- Keep the slim-runtime excludes in `luna/deploy/assemble.sh` honest: dev-only trees never ship.
