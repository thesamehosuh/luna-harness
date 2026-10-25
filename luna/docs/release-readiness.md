# Standalone port: evidence and safe cutover

**Ambient/Jev remediation verified (2026-10-26).** The [audit](ambient-jev-audit.md)'s twelve
findings now have production fixes and deterministic regressions. Offline replay makes no provider
requests; routes/credentials are profile-scoped, safety answers validated, topic context isolated,
and only transport-confirmed wakes count as delivered. Setup readiness and worker lifecycle are
verified without real credentials. Optional wakes remain off by default. Live group behavior and
model-quality calibration still require a controlled trial.

The latest approved [system-audit remediation](audit-remediation.md),
[profile/defaults audit](profiles-and-people.md) and
[group conversation fixes](group-conversation-audit.md) cover profile isolation, memory lifecycle,
group capability boundaries, bounded turn taking, recipient/topic isolation, retention/recovery and
every Luna startup path. Current gates pass: **817 companion tests (2 live skipped), 147 gateway
contract tests and 568 frontend tests**. Another focused engine/API run passed 169 tests (1 skipped).
Frontend type checking and production build pass; lint has no errors and 34 existing warnings.

The real OpenCode runtime checked four inference payloads, including a changed group reply target:
persona, room context and recall arrive correctly, dynamic targets stay in user context, and the
system/resumed user prefixes remain byte-stable. Browser checks confirm group limits and Character's
sentence-line-break switch persist after reload. The formatter preserves emoticons, links, code
and quotations; the switch is portable with a profile. Earlier bundled dashboard/TUI tool checks
and the managed Docker memory data path also pass against local model fixtures. Detailed evidence
and remaining limits supersede the historical counts below.

The branding follow-up distinguishes the harness from each user's character, including fresh
persona defaults, room speaker labels, transcript history and wake name prefilters. A replay
fixture covers configured names/aliases versus the unrelated harness name. It also passed 69
focused room/auth/restart checks, 133 targeted TUI tests, dashboard/launcher builds, and an offline
Linux native build. Canonical SVG → native/favicons regeneration and browser checks cover fresh
Sakura Dusk, saved Day/Mono preferences, shared control radii and mobile overflow.
The candidate inspection also caught ignored verification archives being copied into releases;
assembly now excludes ignored evidence, temporary data and browser reports, with a packaging
regression check. Review artifacts remain outside the shipped runtime.

The updated runtime archive also passed installation into a new disposable home containing spaces,
offline multilingual embedding retrieval, authenticated dashboard readiness, neutral defaults,
portable profile export, and save/readback of group coordination and sentence-break controls.
The actual Linux Tauri application passed startup entry creation/removal, home quoting, dashboard
native-permission denial, all three theme/font updates, close-to-background, single-instance reopen
and explicit quit. Native screenshot capture is optional: this machine's WebKitWebDriver stalled
on that endpoint, while the subsequent functional acceptance run passed without capture.

The standalone port is a tested pre-release. Keep the working installation until a controlled
live trial has checked Telegram delivery, real model responses, wake cadence and memory recall.
No finite test suite can guarantee identical generated text or provider behavior.

## What was compared

The legacy checkout was found at `~/Projects/project-luna`. It was read only. The initial comparison
found 49 byte-identical overlay files and 53 changed files (excluding caches and the research tree).
The changes include productization, dashboard APIs, configurable voice/output limits, privacy fixes,
and retention enforcement. These are intentional differences, so byte-for-byte product equivalence
is not the release criterion.

`luna/tools/verify_port.py` runs each checkout in a separate Python process, with synthetic fixtures,
in-memory databases, a fixed clock and seeded random values. It disables bytecode writes and strips
provider credentials. It compares:

- All threshold defaults and the Jev question definitions.
- 512 identical verdict inputs: 419 silent decisions, 69 messages and 24 reactions.
- Both recorded room fixtures, including the 15-member roster, reply reconstruction and identity aliases.

All compared outputs matched. This proves the covered deterministic composition and room/identity
behavior. It does not call Jev, a chat model, Telegram, or the old memory stack. The new room-register
default is neutral; set the group's preferred voice in Behaviour to reproduce a personal deployment's
old prompt. The migrated persona and existing thresholds are preserved.

## Release/install fixes

- Assembly now includes the companion library, plugin code, templates and compiled dashboard in
  the runtime. No plugin or editable Python package points back to the checkout.
- Development metadata, caches, secrets, local databases and development trees do not ship.
  Assembly rejects overlapping paths and external symlinks; dry-run makes no directories.
- One install command works for source and prebuilt bundles. uv supplies supported Python;
  Telegram and Honcho dependencies install before the first chat. The dependency lock and
  self-referencing extras match the `luna-harness` package name.
  Releases carry the dependency lock and install the runtime with `uv sync --frozen`;
  `--inexact` retains additional dependencies installed for the user's tools/providers on upgrades.
- Reinstalling preserves SOUL, config, credentials, customized skin, installed skills and the
  existing Honcho stack. A running gateway must be stopped before its code is upgraded.
- Launchers resolve custom installation homes, including paths with spaces.
- Service definitions use the engine's home-specific gateway name and runtime-owned paths.
  They are installed without enabling, starting or restarting gateways, or removing legacy units.
  Additional Luna service names are home-specific. Enablement on login is not automatic.
- Migration snapshots every root SQLite database through SQLite's backup API, including committed
  WAL content and `luna-state.db` identities/wakes. It also preserves config, persona, aliases,
  credentials, profiles, skills and local history. It refuses nonempty/overlapping destinations,
  materializes source symlinks, validates snapshots, and never copies live systemd units.
- Rollback stops only the units recorded by the trial install, with no hardcoded legacy service name.
- Fresh memory stacks pull a digest-pinned published Honcho image. They use a private database/cache
  network and a loopback API port, with a home-specific Compose project. Locally built images,
  an OpenCode-specific proxy and a personal embedding server are no longer prerequisites.
  Existing memory stacks keep their settings. Managed stacks can refresh provider keys without
  rotating database/cache passwords. Local endpoints must be reachable from Docker.
  Image availability and entrypoints were checked against [Honcho's self-hosting documentation](https://github.com/plastic-labs/honcho/blob/main/docs/v3/contributing/self-hosting.mdx)
  and the image registry before the isolated startup test.
- Onboarding writes the canonical `model.default` and key reference, recognizes only the selected
  provider's credentials, rejects template group/admin IDs, and provides separate memory/wake keys.
  A dry-run establishes wiring only. The live wake check now requires a complete validated Jev
  response; saved readiness is invalidated when provider routes or credentials change.
- CLI and dashboard update admission both refuse the engine's upstream updater for Luna trees.
  A future update channel must explicitly target Luna releases.

## Verification

The audit used a fresh supported Python 3.11 environment, not the incomplete Python 3.14 development
venv. The latter initially failed 31 engine checks because OpenAI/aiohttp dependencies were absent.
With runtime/test dependencies installed, all 145 bounded gateway tests passed.

The release smoke check builds an archive, installs into a path containing spaces, removes the
unpacked source, and verifies installed imports, dashboard/assets, authenticated companion APIs,
all four plugin imports, the edit-approval module and the updater guard. It passed.

An isolated Docker project on a separate loopback port started the pinned Honcho API, Postgres,
Redis and a synthetic embedding service. Honcho SDK 2.2.0 created a workspace, peers and a session,
stored two synthetic messages, and retrieved them with the correct distinct peer IDs. No real
credentials, Telegram poller or paid model calls were used. This verifies startup, persistence,
embeddings and attribution; model-driven derivation/dialectic quality still needs a live trial.

The actual dashboard was opened in Chromium. The old provider-save bug was reproduced before
the new compiled assets were installed; the corrected flow is checked against the resulting YAML.
The source-removal smoke check is automated in `scripts/test-release.sh` and CI.

Final audit checks: **576 companion tests passed** (2 live tests skipped), **145 gateway tests
passed**, **231 dashboard/API tests passed**, and **554 frontend tests passed**. The production
frontend build and lint completed; lint reports 31 existing warnings and no errors. Targeted
deployment/migration checks were repeated after the final path and SQLite connection fixes.

The subsequent [native OpenCode integration](opencode-engine.md) adds dashboard installation and
live free-model selection. Its audit passed **626 companion tests** (2 live tests skipped),
**145 gateway tests** and **558 frontend tests**, plus targeted engine regressions. The real native
binary completed a Luna file-tool round trip against both a local deterministic model endpoint and
an explicitly authorized ChatGPT subscription model. Public free routes reached the service but
were rate limited, deprecated or withdrawn; they remain subject to provider availability.

This session did not deploy, restart the working gateway, publish a release, or validate macOS/Windows
installation. Publishing a stable download URL, testing the advertised OS matrix, and selecting a
Luna release version/channel remain release tasks.

## Trial and cutover

For a new-user rehearsal, use `bash install.sh "$HOME/.luna-trial"` and a throwaway Telegram bot/group.
Complete Setup in the dashboard, including a real wake verdict. Check replies, silence, approvals,
identity attribution, memory writes/recall and reconnect behavior. The installer opens Setup on an
interactive terminal; otherwise use `~/.local/bin/luna dashboard`.

For a state-preserving migration, snapshot a runtime home, not a source checkout. Do this before
installing into the destination, which must be empty:

```bash
luna/deploy/migrate-from-hermes.sh /path/to/old-runtime "$HOME/.luna-trial" --dry-run
luna/deploy/migrate-from-hermes.sh /path/to/old-runtime "$HOME/.luna-trial"
bash install.sh "$HOME/.luna-trial"
```

SQLite backups are individually consistent while the old gateway runs. To capture a final coherent
application snapshot across files/databases, stop the old gateway first, then take the final snapshot
into a new empty destination. The installer does not stop it for you.

**Honcho memory is separate from SQLite.** The migration preserves the Honcho connection/workspace
settings and aliases, not Postgres volumes or its remote data. Keep the existing memory stack, or
take and restore an independent Postgres backup before switching it. Do not assume copying this
repository backs up long-term memory. A trial pointing at the old workspace can write to that memory.

For the final switch, stop the old gateway, start the new gateway from its dashboard, and ensure
exactly one process owns the production Telegram token. Test a group reply, an owner DM, identity,
approval routing, memory recall and a self-wake. Keep the old runtime/checkout and memory backup
through a successful soak period. Do not run both gateways with the production token.

If the trial fails, stop its gateway in System before starting the previous gateway. The optional
`luna/deploy/rollback.sh /path/to/trial` stops service units installed by the new installer; it retains
all files and never starts the previous gateway. It is not a database downgrade tool or a rollback
of writes already made to a shared Honcho workspace.
