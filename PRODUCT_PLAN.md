# Luna product plan

The roadmap from personal fork to standalone product anyone can use to run their own companion.
Research-backed; update this file as phases land. Session decisions are recorded in §1.

---

## 1. Product decisions (recorded)

| # | Decision |
|---|---|
| D1 | **Luna names the harness, not the companion.** Each user chooses their companion's name, persona and voice. Fresh personas use the neutral placeholder Companion; the Luna character in `luna/soul/SOUL.md` is an optional example, never the public product's identity. |
| D2 | **Fresh repo, vendored engine.** Own history; upstream hermes-agent is a pinned dependency re-vendored deliberately (MIT attribution in `NOTICE`). |
| D3 | Dashboard = **keep the existing web SPA's controls and add to it** (not a scorched-earth rewrite): rebrand + extend `web/` on the existing FastAPI routers, add companion pages. |
| D4 | Users must **never touch the terminal or hand-edit configs**. Every `luna tune`/`peers` capability and every config key becomes dashboard UI; terminal commands shrink to dev-only (P5). |
| D5 | Companion-first scope: "a character at home in group chats, a good assistant in DMs". Remove hermes/coding-agent-harness features Luna doesn't need, **but don't gut the agentic spine** (files/terminal/search stay, approval-gated). |
| D6 | Internal dev docs (`luna/docs/`) retire as their knowledge lands in dashboard help/UI (P5). |
| D7 | Work happens in this repo (`~/Projects/luna`); the live personal deployment is never touched by product work. |
| D8 | **Voice and identity are config, never code.** Persona text lives in `SOUL.md` (dashboard-editable); the room's voice (`luna.ambient.room_register`) and every identity/voice knob are config keys with product-neutral defaults — no deployment's character is baked into the engine or overlay code. |
| D10 | Audit remediation: groups default to web tools and room-public recall; configured transport owners retain full DM capabilities. Broader group host access requires dashboard opt-in. Reply language defaults to following the conversation. |
| D11 | **Managed memory installation.** Docker/Compose prerequisites and Luna-owned Honcho containers are set up through the installer/dashboard, with normal OS permission prompts when required. Users never run Compose commands, choose container ports or edit database settings. Existing unrelated Docker installations and workloads are preserved. |
| D12 | **Bundled local embeddings.** Ship a small, pinned, CPU-capable multilingual embedding model and its runtime for Honcho. Embeddings require no API key, paid endpoint, separate model app or runtime model download. Model/vector-schema compatibility and migration are Luna's responsibility. Exact model selection follows retrieval and resource testing. |
| D13 | **Group memory is a supported setup path.** One guided memory action configures and verifies Honcho, embeddings, reasoning connectivity, transport-derived author attribution, room isolation and restart persistence. Do not label memory ready after only a container health check. Requirements and implementation gates: `luna/docs/beginner-setup-plan.md`. |
| D14 | **Thin Rust desktop launcher.** A small native app downloads the versioned Luna runtime, starts its local backend and displays the existing dashboard inside a webview. It does not bundle the whole repo or introduce a second product UI. Onboarding stays in the dashboard, with OpenCode free chat as the immediate path. Memory and Jev each have a persistent Skip for now choice. Container setup is deferred when memory is skipped. |
| D15 | **Honcho reasoning follows the companion by default.** The normal choice is Use my companion's model, resolving its current provider/model/credentials by reference. A different memory model is an optional simple override. Native OpenCode must work through a tested Honcho-compatible adapter; do not silently substitute a fixed paid model or ask for a duplicate key. Reuse the model connection, not the companion persona prompt or host tools. |
| D16 | **Honcho controls and status belong in the dashboard.** Include the effective dialectic cadence in turns, reasoning effort/cap, passes, context budget/cadence, observation/recall/write modes and session/peer/workspace status shown by `luna honcho status`. Dashboard changes must reach the actual client configuration, not only a parallel YAML form. |
| D17 | **Native startup and background controls.** The launcher exposes opt-in launch at login, close-to-tray behavior, and companion start/stop using the dashboard's existing gateway lifecycle. Starting the companion with Luna is a separate opt-in. Reopening Luna raises its existing window instead of starting another backend or poller. Native startup changes are unavailable to dashboard/external webviews. |
| D18 | **New-user defaults, not operator preferences.** Neutral editable character, live OpenCode model choice, balanced reasoning and text-first replies. Memory, wakes, voice, writing-style rewrites and startup behaviour are opt-in. Existing saved choices are preserved. Portable config/persona files import into new profiles with fresh identity/connection state. See `luna/docs/profiles-and-people.md`. |
| D19 | **Basic model-writable PEOPLE.md.** A profile-local who's-who fallback remains available without Honcho. Store only names, aliases, pronouns and short roles, keyed to observed transport identities. One person can belong to several groups; model updates remain scoped to their source group or DM. Bounded context uses the sidecar/user-message path, never the system prompt. |
| D20 | **Bounded group turn taking.** One selected reply per profile/bot/chat/topic, fixed transport recipient, short request lifetimes and limited answers per burst. Other authors' pending questions are never merged tasks; DMs remain independent. Behaviour exposes controls and recent decisions. Dynamic targets stay out of the cached prompt. See `luna/docs/group-conversation-audit.md`. |
| D21 | **Group file memory uses the engine's maintenance loop.** Each group/topic owns MEMORY.md, with scoped PEOPLE.md as its basic people directory. Keep the existing memory enable flags, character limits, nudge cadence, write-approval setting and auxiliary background-review controls. Owner DMs look up group files explicitly, without automatically injecting their contents. Private USER.md/MEMORY.md reads are approval-free in the owner's DM; groups need a separate one-read owner-DM approval showing the exact excerpt and destination. The verified Telegram setup owner is an administrator; arbitrary DM senders are not. |
| D9 | **Dashboard identity is Sakura:** midnight violet, blossom pink, lavender and warm gold, inspired by the operator's reference image. Sakura Dusk is the fresh-install and first-paint default, independent of OS appearance. Sakura Day, Mono and custom themes remain available. Dashboard and launcher share typography, control/panel radii and one canonical crescent-and-blossom icon. Retired preset preferences migrate. Remaining polish work is tracked in `POLISH_PLAN.md`; this does not authorize a release or changes to the live deployment. |

## 2. What the product is

A self-hosted harness where **each user creates their own companion**:

1. **Character creator** — persona (SOUL), voice rules, hard limits (language, emoji, length),
   skills, skin. Fresh profiles start with a neutral Companion placeholder. The Luna persona is an optional example character.
2. **Wake/behaviour tuning** — when the companion speaks up, reacts, or stays quiet. Sliders over
   the cascade thresholds, live verdict feed, wake ledger, cost, what-if replay.
3. **People & memory** — identity registry (peers, pronouns, roles, aliases), Honcho-backed
   per-person and shared room memory with budgets.
4. **Ops without terminal** — onboarding wizard, health, channels (Telegram), models/keys,
   retention, updates.

## 3. Architecture (post-productization)

- **Engine** (vendored hermes-agent 0.21.3): agent loop, gateway + Telegram adapter, tools,
  state DBs, CLI, dashboard backend (`hermes_cli/web_server*.py`, `web_routers/` — 236 REST
  endpoints already cover config/schema, secrets, models, memory providers incl. Honcho writes,
  Telegram onboarding, persona (`PUT /api/profiles/{name}/soul`), cron, plugins, ops).
- **`luna/` overlay**: companion plugins (`luna-room`, `luna-memory`, `luna-ambient`, `luna-logger`),
  `luna_core` (cascade, identity, peers, room, text, db), config templates, persona, deploy,
  tests. Tunable wake params live in `luna:` config (mtime-cached; live-applied) + `luna-state.db`
  (wakes, jev_usage) + verdict lines in `logs/agent.log`.
- **Dashboard** (`web/` SPA): kept controls + new pages (§5). Auth stack as-is (loopback session
  token; OAuth gate for non-loopback).
- **Runtime**: `assemble.sh` slim keep-set → `~/.luna` + Honcho docker stack + systemd units.

## 4. Feature disposition (from audit)

**Remove from the product (P1):**
- Data-gen cluster: `batch_runner.py`, `mini_swe_runner.py`, `trajectory_compressor.py`,
  `toolset_distributions.py` (self-contained; breaks only their own tests).
- `mcp_serve.py` (hermes-as-MCP-server for other editors) + its command wiring.
- Tool families from product config: `kanban_*` (14), `desktop_ui` (10), `browser_*` (15),
  `computer_use`, `homeassistant` (4), `connections` — off the toolsets; code can stay inert.
- Platform extras not Telegram: discord/yuanbao/feishu toolsets; `optional-mcps`, `contributors`,
  `MagicMock`, `evals` out of runtime, `plugin-catalog` (falls back to network — ship empty/offline
  instead).
- CLI surface: subcommands no product user needs (`acp`, `bundles`, `claw`, `codex_runtime`,
  `computer_use`, `console`, `curator`, `debug`, `dump`, `import_agent`, `insights`, `journey`,
  `moa`, `monitoring`, `pets`, `prompt_size`, `slack`, `whatsapp`, `webhook`, `worktree`, `sync`,
  `claw`, `codex_runtime`) — hide via a product-level parser patch (P5). **Gotcha:** `main.py`
  imports every subcommand builder at startup; removal is a patch, not a delete.
- `luna/local-jev/` research tree (already excluded from this repo) and `luna tune` CLI (P5, after
  GUI lands).

**Keep (agentic spine + companion core):**
- `agent/`, `gateway/`, `tools/` core (file, terminal, web, vision, image_gen, tts, memory,
  session_search, clarify, todo, skills, cronjob, delegation, code_execution), `cron/` with
  guardrails 0011–0013, `skills/` (slim to conversational categories later), `native/`, `providers/`.
- **Gotchas:** `acp_adapter` is load-bearing (write-guard import in `model_tools`); `tui_gateway`
  is imported by gateway post-connect (hosted-room worker + secret scope) — gate with a patch
  before excluding; `plugins/memory/honcho` is a soft dependency of `luna-memory` (keep).
- **Add:** `image_gen` to the companion surface (a character should be able to send pictures).
- `apps/`, `website/`, `ui-tui/`, `web/`... `web/` is now first-class (the dashboard); `apps/`
  (Electron) and `website/` stay out of the runtime. The old full desktop UI remains out of scope;
  D14 separately authorizes the proposed thin Rust launcher around the existing dashboard.

## 5. Dashboard plan (D3)

Base: existing `web/` SPA + `hermes_cli/web_routers/`. Keep the controls we use (config editor +
schema, models/keys/env, memory providers, channels incl. Telegram onboarding, profiles/SOUL,
cron, system/doctor, logs, analytics) — restyle chrome to Luna branding.

**New pages (the product's core):**

| Page | Replaces | Content |
|---|---|---|
| **Onboarding wizard** (P3) | terminal setup | Provider key → Telegram bot + group binding → Honcho stack (one-click docker compose) → character pick → first wake test. Progress + health checks per step. |
| **Character** (P4) | `SOUL.md` by hand | Structured persona editor (sections from the shipped SOUL: voice, rhythm, hard rules, banned list, TTS), hard limits as config (`luna.output.*`), skills auto-load toggles, skin picker + preview, persona presets library. |
| **Behaviour / wake tuning** (P2) | `luna tune …` | Threshold sliders with docs + default badges (`tune thresholds/set/reset`), route chain editor (`luna.ambient.jev`), budget/cooldown controls, dry-run toggle, live verdict feed (`tune verdicts -f`), wake ledger (`tune wakes`), cost chart (`tune cost`), what-if replay (`tune replay`), health panel (`tune status`). |
| **People** (P2) | `luna peers …` | Identity registry table (peers, pronouns, roles, aliases), audit report (`peers audit`), merge accounts (`peers merge`), sync button (`peers sync`), Honcho peer cards preview. |
| **Help / docs** (P5) | `luna/docs/` | In-dashboard help: how wakes work, privacy model, security posture — distilled from the internal docs as they retire. |

**API additions** (new routers; `luna-state.db` readers already exist in `luna_cli/tune.py`,
`luna_core/db.py`, `luna_core/identity.py`):
- `GET /api/luna/health`, `/api/luna/verdicts` (tail/stream), `/api/luna/wakes`,
  `GET/PUT /api/luna/thresholds`, `GET /api/luna/cost`, `POST /api/luna/replay`,
  `GET/POST /api/luna/identity`, `POST /api/luna/identity/merge`, `POST /api/luna/peers/sync`.
- **Config schema for `luna.*`** (+ `honcho` curated panel + `display.platforms.telegram_group`):
  today the schema is generated from engine `DEFAULT_CONFIG` only, so `luna.*` is raw-YAML. P2 adds
  schema contributions so every companion knob is a first-class form field with validation
  (memory ceilings, chat-id pickers, threshold ranges).

**Operator-safety rules for the dashboard:** hide engine-danger surfaces (gateway restart/drain is
operator-initiated only; raw YAML editor behind an "advanced" gate; reaction tier stays opt-in).

## 6. Phases

### P0 — Product repo bootstrap ✅ (this session)
- Fresh repo at `~/Projects/luna`, own history, vendored engine + NOTICE attribution.
- Private/personal content scrubbed (plan, research tree, names, paths).
- README, AGENTS.md (product dev guide), this plan.

### P1 — Feature trim (D5) + engine-edit policy ✅
- Remove/neutralize per §4: data-gen cluster, `mcp_serve`, tool families out of product config,
  CLI subcommand hide-list (parser patch), `plugin-catalog` offline, runtime excludes cleanup. ✅
  - Data-gen cluster + `mcp_serve` deleted with their tests; light engine references cleaned.
  - Tool families stay off `platform_toolsets` (contract-tested: `test_product_toolsets.py`).
  - Hide-list ships in `hermes_cli/_parser.py` (`PRODUCT_HIDDEN_SUBCOMMANDS`): hidden subcommands
    never register (modules still import until P5).
  - `plugin-catalog/` ships empty and offline (no live fetch, no bundled entries).
- Fold `luna/patches/*.patch` into the tree as normal code (we own the tree now); record engine
  edits in `luna/docs/engine-vendor.md` for future re-vendors. ✅
  - The patch-apply contract became `test_engine_edits.py` (inventory completeness gate).
- Re-verify: `scripts/test.sh` green; assemble keep-set honest; `luna doctor` clean on a fresh
  install. ✅ (luna tiers green; assemble audited on a scratch target; doctor runs clean on a
  scratch `HERMES_HOME` — its 4 notices are fresh-environment setup items, not regressions.)

### P2 — Companion API + Behaviour/People dashboard pages (D4 core) ✅
- `luna.*` config schema contributions + Honcho curated panel + `telegram_group` display section. ✅
  - `luna/lib/luna_cli/config_schema.py` feeds `CONFIG_SCHEMA` (97 fields; thresholds generated
    from `CascadeConfig` with ranges). Contract: every template companion key has a field
    (`luna/tests/unit/test_config_schema.py`) — raw-YAML-only keys are a regression.
- New routers (§5) over `luna-state.db`/logs/config; pages: Behaviour (tune) + People (peers). ✅
  - `/api/luna/{health,verdicts,verdicts/stream,wakes,thresholds,cost,replay,identity,
    identity/merge,peers/audit,peers/sync}` behind the dashboard auth gate
    (`luna/lib/luna_cli/web_routers.py` + `api_models.py`).
  - Behaviour page: health strip, threshold sliders with defaults/reset, live verdict feed,
    wake ledger, cost, what-if replay. People page: identity registry CRUD, audit, merge, sync.
  - Route-chain editor / budget sliders land with P4's character work (schema fields exist).
- Remove nothing yet — CLI and GUI coexist until P5. ✅ (`luna tune`/`peers` untouched;
  `luna_core.peers` now holds the shared identity ops both surfaces call.)

### P3 — Onboarding wizard ✅
- First-run flow covering provider keys, Telegram bot creation/link + group binding, Honcho stack
  bring-up (docker compose + health probe), identity seeding, dry-run wake test. ✅
  - `/api/luna/onboarding` step state machine (`luna/lib/luna_cli/onboarding.py`): provider →
    telegram → honcho → character → wake_test, each with a health check; the wizard page
    orchestrates the existing setup endpoints (`/api/env`, `/api/config`, `/api/profiles/*/soul`).
  - One-click Honcho: `POST /api/luna/onboarding/honcho/up` seeds `.env` (generated DB/cache
    passwords; provider keys passed through — **not** proxy vars, which hang the api at startup),
    runs `docker compose up -d --wait`, probes `/health`. `install.sh` now lays the stack down in
    `$HERMES_HOME/honcho` (secrets stay untracked; never in the repo).
  - Character pick: persona presets (`GET /api/luna/onboarding/personas`) → `PUT
    /api/profiles/default/soul`. Wake test: synthetic candidate through the cascade
    (`POST /api/luna/onboarding/wake-test`, dry-run default, live spends one jev call).
  - First-run: `/` lands on the wizard only when neither provider nor telegram is configured.
  - D8 landed alongside: `luna.ambient.room_register` configures the room voice (was hardcoded).
- Success criterion: a new user goes from clone to a working companion **without opening a
  terminal** beyond `install.sh`/`luna dashboard` (packaging to hide even that is P6). ✅

### P4 — Character creator ✅
- Structured SOUL editor (sections, presets, live preview of limits), `luna.output.*` hard limits
  as GUI fields (config-ize the code-enforced limits first), skills auto-load management, skin
  picker/editor, persona import/export. ✅
  - `/api/luna/character` (+ `/preview`): section editor over SOUL.md, presets (current/generic/
    warm-friend), live group/DM shaping preview, hard limits (`emoji_filter`, `strip_emoji`,
    `allowed_emoji`, `max_lines` — the line cap is now config, not a code constant), skin picker,
    skills auto-load toggles, persona import/export. Writes go through
    `luna_core.configedit` (comment-preserving) + whole-file SOUL regeneration.
  - `/api/luna/behaviour`: dry-run toggle, room voice, budget/cooldowns, mention-fallback +
    reaction policy, and the jev route-chain editor (providers replaced wholesale; validation
    refuses unknown routes/model-less providers). Behaviour page extended.
  - Skin **editor** ships: `write_skin()` rewrites the colour keys of the active skin through the
    comment-preserving config editor, `CharacterUpdate.skin_colors` carries them over the API, and
    `CharacterPage.tsx` renders swatch pickers with a live preview.
- Respect the cache contract: persona edits write SOUL.md / stable config only — never per-turn
  injection. ✅

### P5 — Docs retirement, tune/peers CLI removal, rebrand sweep (D6) ✅
- Move `luna/docs/` knowledge into in-dashboard Help; delete the internal docs. ✅
  - `web/src/content/help.ts` (wakes, surfaces/output, people/identity, memory, privacy, security,
    appearance, authentication) is the single user-facing source; served at `/help` (route + nav).
  - Retired: architecture, memory, group-chat, security, output-routing, theming. Retained as
    engineering records (gated by contract/AGENTS): engine-vendor, upstream-sync, testing, jev.
  - Every reference retargeted (config template, skins, honcho compose, code comments, skills that
    must never name a dead command, install/migrate output, `luna/README.md`).
- Remove `luna tune` CLI (keep the read-model code it shares with the API) and narrow `peers` to
  the API; keep `doctor`/`gateway`/`sessions` as dev tools. ✅
  - `luna tune` argparse CLI stripped; `luna_cli/tune.py` stays as the read/write library behind
    `/api/luna/*` (thresholds, verdict log, db paths). `luna peers` plugin command removed (the
    People page owns identity now); `luna_core.peers` shared ops keep audit/sync/merge for the API
    and tests. The 21 hidden `hermes_cli/subcommands/*` builders are deleted outright and the P1
    hide-list is unwrapped from `_parser.py`.
  - Retained dev tools: `doctor`, `gateway`, `sessions`, plus the operator surfaces (`dashboard`,
    `config`, `mcp`, `cron`, `skills`, `plugins`, …). Product help retargets to `/help`.
- Rebrand sweep: CLI `prog`, FastAPI title, login page, error strings, package names, default
  skin, docs strings ("hermes"→product language where it's user-facing), setup script names. ✅
  - Wake telemetry logs ids, reasons and weights only: message and reply text never reach
    `agent.log` (privacy), so the verdict feed is the weight audit trail, not a transcript
    archive. Pinned by `test_verdict_log_never_contains_message_text`.
  - Titles/login/banner/version/update/doctor/messaging read "Luna" across the dashboard (all 17
    locales), shared lib, and CLI help; `~/.hermes/` paths in copy read `~/.luna/`; login's external
    docs link now
    points at in-dashboard Help; distribution → `luna-harness` (import
    paths kept). Default skin (`display.skin: luna`) already shipped. Engine edits recorded in
    `luna/docs/engine-vendor.md`.

### P6 — Product hardening ✅ / alpha release pipeline active
- Privacy defaults review + threat model pass on the dashboard and Telegram surfaces. ✅
  - Reasoning, trust boundaries, and the full findings list: `luna/docs/threat-model.md`.
  - **Retention was only half-enforced.** `install.sh` installs a daily systemd timer that runs the
    pruner, but that was the only path — a deployment without it (manual start, container, second
    gateway) had no enforcement, and elsewhere the transcript could sit unpruned for a day.
    `luna_core.retention.enforce` now also runs in-process from both indexer loops (the gateway
    thread and `luna-logger/run.py`), gated by `luna.data.auto_prune` + `auto_prune_interval_minutes`,
    which the CLI path honours too so the two agree. Fail-soft: never raises, never blocks indexing;
    an unreadable config skips the pass instead of falling back to the 1-day default.
  - **The observe switch is now visible.** `telegram.observe_unmentioned_group_messages` ships on and
    is the widest thing Luna stores, but was raw-YAML-only (AGENTS.md §6). Now a Config field that
    states what turning it off costs.
  - **Two fail-open paths closed.** `luna-room` could concatenate untrusted room text into
    `channel_prompt` (system-level, inside the cached-agent signature — invariant 1) when the sidecar
    seam was missing; and group output shaping skipped redaction entirely for an unrecorded session
    and on its own exception path. Both now fail closed (unknown surface shapes as `group`).
  - **Dashboard edges:** rate limits on the multi-minute operations, an 8-connection cap on the
    verdict SSE tail, a JSON content-type guard on the bodyless `/peers/sync`, a router-level
    `_require_token` second auth layer, and an auth contract test that derives its route list from
    the router rather than hand-maintaining it.
  - Engine edits (query-token source, HTML token escaping, `X-Hermes-Session-Token` wire contract)
    recorded in `luna/docs/engine-vendor.md`.
  - **Deliberately not changed, needs an operator decision** (all recorded in the threat model):
    group/DM toolset parity, `operator_chat: '0'` disabling approval routing into the group,
    effectively-open self-wake caps, fail-open slash gating when the admin list is absent, unescaped
    room-block content, config-mediated SSRF, surface-agnostic memory recall.
- Packaging pre-release checks are implemented: one-command source/bundle installer, a
  self-contained archive with compiled dashboard and frozen dependency lock, state-preserving
  migration/reinstall, runtime service definitions, differential legacy replay and a CI release
  smoke check that removes the unpacked source before probing the installed product. Alpha builds
  use the cross-platform workflow and draft-release acceptance gate documented in
  `luna/docs/desktop-release.md`. Stable releases, signing, and unassisted clean-machine acceptance
  remain future gates.
  Optional: desktop port re-evaluated here.

## 7. Testing policy

- Keep the tiered suite (`luna/tests/{unit,component,contract,replay}`) green every phase; every
  phase adds its tests alongside its code (API endpoints get endpoint-probe + auth tests like the
  existing `web_routers` suites; GUI gets vitest where the SPA already has it).
- Contract tests gate engine re-vendors (P1 makes them gate engine edits too).
- The replay corpus stays the regression gate for identity + wake behaviour; threshold changes
  need replay evidence.
- Onboarding and character-creator flows need end-to-end tests (fresh runtime → wizard → first
  wake) before P6 release.

### Running the engine suite

`tests/hermes_cli/` is the vendored upstream suite (~12.2k tests). It is **not isolation-safe**:
several files share module-level registries, cached paths and env mutation, so a single-process
run fails on order alone, and `pytest -n` still fails because each xdist worker is itself a
long-lived process. Verified green by running **one process per test file**, each with its own
`HERMES_HOME` and `--basetemp`.

Two traps that produce phantom failures, both hit during the P0–P5 verification:

- Passing `-p no:cacheprovider` puts `-p no:cacheprovider` into `sys.argv`, which
  `test_relaunch.py::test_calls_execvp` asserts on. Use `-o cache_dir=<tmpdir>` instead.
- Pointing `HERMES_HOME` at the real `~/.luna` makes tests that pass `user_config=None` read the
  operator's real config and fail. Luna's own tests must pin an isolated home.

## 8. Risks & invariants

- **Cache contract / identity rule / one poller / silence default** are load-bearing (AGENTS.md
  §3). Product features may never violate them (e.g. character preview must not inject per-turn
  persona into cached prompts).
- **Engine re-vendor cost:** own history means upstream fixes are deliberate imports. Mitigations:
  keep engine edits minimal + listed, keep contract tests, prefer `luna/` overlay code.
- **`tui_gateway`/`acp_adapter` coupling** (§4 gotchas) — gate before excluding anything.
- **Scope creep on "assistant in DM":** D5's line is "companion products don't need a
  coding-agent harness, but the owner DM keeps real tools". Kanban/browser/desktop-bench go;
  file/terminal/web/search/cron stay (approval-gated).
- **Solo-operator risk** (this product serves many users): onboarding must not assume the old
  personal ops knowledge (proxy quirks, manual systemd, `peers sync` folklore). That knowledge
  lives in P3's wizard and P5's Help.

Native OpenCode support is implemented as an optional model engine. Setup and Models install a
verified runtime, discover its current public free models, probe one and select it without a chat
API key. Luna keeps its guarded tools, identity, recall sidecars and output shaping. Text auxiliary
work follows the selected native engine; Honcho embeddings and Jev wake judgments remain separate.
Architecture and live-test evidence: `luna/docs/opencode-engine.md`.

The approved standalone system-audit remediation is implemented. Profile isolation, memory
lifecycle/delivery, group/private capability boundaries, settings recovery, retention/backups,
immutable releases and dashboard/chat/service startup now have regression and integration evidence.
See `luna/docs/audit-remediation.md`; release remains an alpha pending the controlled live Telegram
trial. This does not authorize replacing or restarting the existing deployment.

The 2026-10-25 ambient/Jev audit's twelve findings were remediated on 2026-10-26. Route and
credential selection, strict protocol validation, offline replay, topic isolation, delivery receipts,
resource admission, Setup readiness and gateway-owned worker lifecycle now have regressions.
See `luna/docs/ambient-jev-audit.md`. Optional wakes remain off by default; threshold calibration
and real crowded-room quality remain controlled-live-trial gates for the public alpha.

## 9. Open questions

- Pricing/positioning: free self-hosted only, or hosted offering later? (Affects P6 packaging.)
- Persona presets library licensing (ship community presets?).
- Whether `image_gen`, spotify, video tools become first-class companion features or optional
  plugins.
- Multi-platform: Discord/WhatsApp adapters stay in the engine as inert code — promote later?

## 10. Beginner installation and managed memory — next work

The user explicitly requires automatic Docker setup, a bundled small embedding model and Honcho
setup that removes the old group-chat configuration burden. These are recorded decisions, not
completed features. The current installer still expects Docker to exist and the current fresh
memory template defaults to remote OpenAI embeddings. The next release must replace that path;
do not advertise the current alpha as satisfying these requirements.

Implementation and acceptance criteria are in `luna/docs/beginner-setup-plan.md`. A graphical
launcher and shorter onboarding flow are proposed packaging work; they do not imply approval to
install or configure Luna on the operator's machine. The operator wants to perform the real user
installation personally. Development checks use isolated homes and explicitly scoped test stacks.
