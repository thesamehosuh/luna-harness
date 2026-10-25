![Luna — personal AI companion harness, in Sakura Dusk ASCII art](assets/luna-ascii.svg)

**Your own AI companion for the group chat.** Luna is a self-hosted harness for a personal AI
character that lives in your Telegram group and can assist in your DM. **Luna is the harness's
name; you choose your companion's name and personality.** The dashboard handles setup. No terminal,
no hand-edited config files.

> **Public alpha:** [download Luna](https://github.com/thesamehosuh/luna-harness/releases).
> Start with a clean setup; existing Hermes/Luna installations are preserved. The release page
> lists the exact platforms tested and any preview limitations.

## What makes Luna different

- **Your own character.** Your companion has a voice, opinions, rhythm, and memory of the
  people they talk to. Fresh profiles start with a neutral Companion placeholder; the Luna persona
  is an optional example. The character creator lets you write
  your own, down to the hard rules (languages, emoji, length).
- **Judgement about when to speak.** A staged cascade (cheap prefilter → small-model verdicts →
  hand-tuned thresholds) decides when a message deserves the companion's attention. Silence is the
  default. Delivered wakes are recorded. Settings are tunable, and stored Jev scores can be replayed offline
  without sending chat history to a provider.
- **People-aware memory.** Deterministic identity from transport ids (never guessed from text),
  per-person memory in a local Honcho stack, shared room memory with strict budgets.
- **Different surfaces, different rules.** Group output is shaped (short, quiet, private). The
  owner's DM keeps the full agentic toolkit: files, terminal, code, search, cron, skills.
- **A dashboard for everything.** Config, persona, wake tuning, people/identity, memory, models,
  channels, cost — all GUI. The goal: nothing in this product requires the terminal.

## Quickstart

1. Open [Downloads](https://github.com/thesamehosuh/luna-harness/releases) and choose the launcher
   for your operating system. Linux AppImage users may need **Properties → Permissions → Allow
   executing as a program**, then double-click. Linux packages can be opened in the system's
   software installer. macOS 14+/Windows builds are preview artifacts until their platform checks and
   publisher signing are complete; see the release notes before installing them.
2. Open **Luna**. It downloads a checksummed, versioned runtime with the dashboard and a small
   multilingual embedding model. You do not need Git, Python, Node or a terminal.
3. Finish **Setup** inside the app: choose a model and create your companion. Telegram, memory
   and ambient wakes can each be skipped. Enable them later from the dashboard.

Your model's availability and any usage limits belong to its provider. OpenCode's free-model
catalog changes; Luna discovers available choices instead of hardcoding a chat model.

The **Luna → Launcher settings** menu controls launch at login, background behavior and companion
start/stop. All three automatic behaviors start off. Closing Luna normally stops its dashboard;
**Quit Luna** also exits background mode.

For developers working from a source checkout:

```bash
bash install.sh
```

The installer manages Python, builds the dashboard, installs a self-contained runtime under
`~/.luna`, and opens Setup in an interactive terminal. Source builds need Node/npm
(Node 22.22+, 24.11+, or 26+); prebuilt release bundles need no Node build tools or source checkout.
If Setup did not open, run `~/.local/bin/luna dashboard` and visit `http://127.0.0.1:9119`.

In Setup, choose **OpenCode (free models)**, install its engine if needed, select a model and use
**Test model**. No chat API key is required. API providers remain available as alternatives.
Pick a character and start chatting. Telegram, memory and Jev each have **Skip for now**, saved
across reloads. Enabling memory sets up Docker/Compose and the owned Honcho stack, with a bundled
multilingual CPU embedding model. Its reasoning defaults to **Use my companion’s model**, including
native OpenCode; no second provider key or fixed paid fallback is required. The **Memory** page
shows effective Honcho status and edits dialectic cadence in turns, reasoning effort, passes,
context budgets, observation, recall and write behavior. Self-wakes use Jev separately and remain
off until enabled. All settings are in the dashboard. Start the gateway from System when ready; the installer never starts or restarts it.

**Already running Luna or Hermes?** Keep it. Install a trial into a separate home first:

```bash
bash install.sh "$HOME/.luna-trial"
```

Use a separate test bot for a simultaneous live trial. One Telegram token must have only one
running gateway. The [cutover procedure](luna/docs/release-readiness.md) covers state snapshots,
Honcho memory, rollback, and the limits of the parity checks.

## Architecture

- **Engine** — vendored [hermes-agent](https://github.com/NousResearch/hermes-agent) 0.21.3 (MIT,
  see `NOTICE`): agent loop, gateway, tools, state, CLI, dashboard backend.
- **`luna/` overlay** — the companion layer: room/reply-chain reconstruction, identity + memory,
  the wake cascade (jev), the tokenless indexer, persona, config templates, deploy.
- **`web/` dashboard** — the product UI on the engine's REST/JSON-RPC APIs.

See `AGENTS.md` for engineering invariants. User documentation is in the dashboard Help page.

## Release checks

```bash
scripts/test.sh                  # companion + configured engine contracts
scripts/test-release.sh          # build bundle, install outside checkout, delete source, probe runtime
python3 luna/tools/verify_port.py /path/to/legacy/project-luna
```

`Luna release checks` runs the companion, gateway, frontend, and isolated bundle checks in CI.
To produce a distributable archive and SHA-256 checksum without publishing it:

```bash
python3 luna/deploy/build-release.py /tmp/luna-release
```

Extract the archive and run its `install.sh`. Upgrades use a new Luna bundle, with the gateway
stopped; character, configuration, credentials and history are preserved. The inherited engine
updater is disabled for Luna trees. The native launcher pins its runtime to a versioned GitHub release and verifies the archive
checksum. Updates require an explicit newer launcher/verified update; code repair preserves data.

## License

MIT. Engine portions © Nous Research; product portions © the Luna authors. Keep `LICENSE` and
`NOTICE` when redistributing. The native OpenCode integration is Apache-2.0 with inherited MIT
portions; its notices ship in `luna/lib/luna_core/OPENCODE_NOTICES.txt`.
