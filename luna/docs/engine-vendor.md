# Engine vendor record — hermes-agent

Luna is built on a **vendored engine**: hermes-agent **0.21.3** (commit
`59f9ff8dbc75b9c4f07ae10174df730f7882a505`, MIT — see `NOTICE`). This repo owns its own
history; upstream updates are deliberate re-vendors, not routine merges.

## Inventory — native OpenCode runtime

| File | Edit |
|---|---|
| `hermes_cli/runtime_provider.py` | Explicit `opencode-engine` virtual runtime bypasses API-key discovery and HTTP/provider fallback. It never adopts another provider's credentials or endpoint. |
| `agent/agent_init.py` | Construct a native auxiliary adapter for OpenCode instead of an unused HTTP SDK client. |
| `agent/conversation_loop.py` | After the ordinary turn prologue, dispatch OpenCode turns to the product overlay. The ordinary finalizer still enforces output transforms, memory sync, cleanup and persistence. |
| `agent/auxiliary_client.py` | Route explicit and automatic text auxiliary calls to the same native free engine; support the async wrapper without constructing an HTTP client. |
| `agent/turn_finalizer.py` | Failed turns do not synchronize an error response into external memory or start background memory/skill reviews. Native quota/error turns exposed this failure path. |
| `agent/turn_context.py` | Multimodal turns query memory using their clean text, then stamp/replay the memory/plugin text sidecar while retaining attachment parts. Gateway note merging preserves the original lookup input. Shared send-path substitution also preserves live attachments across provider changes. |
| `web/src/pages/OnboardingPage.tsx`, `web/src/pages/ModelsPage.tsx` | Reusable dashboard install/catalog/probe/selection flow, with no terminal or API key required for free chat models. |

Implementation, protocol and installer tests live under `luna/`; UI tests live under `web/`.
See [OpenCode integration](opencode-engine.md) for ownership, isolation, license notices and live-test limits.

## Policy (PRODUCT_PLAN P1)

- The engine tree **may carry Luna edits** — this is the product's tree, not a fork that must
  stay mergeable. Before P1 those edits lived in `luna/patches/*.patch` and were applied by
  `luna/deploy/assemble.sh`; they are folded into the tree now and the patch series is gone.
- Keep engine edits **minimal, tested, and listed below**. Prefer product code under
  `luna/` (plugins, `luna_core`, config templates) — an overlay hook beats an engine edit.
- Every edited engine file must appear in the inventory. `luna/tests/contract/test_engine_edits.py`
  fails if an edit is unrecorded or a record points at a missing file.
- Behaviour is gated by the contract tier (`luna/tests/contract/`) — it pins the private engine
  symbols the overlay depends on and the wiring of every edit below. It gates re-vendors too.

## Re-vendor procedure

Release-install audit additions:

- `pyproject.toml`, `uv.lock`: the `luna` extra installs Telegram and the pinned Honcho SDK up front;
  all self-referencing extras use the renamed `luna-harness` distribution. Lock metadata matches.
- `hermes_cli/update_contract.py`: the shared CLI/dashboard update admission gate refuses the
  engine's upstream ZIP/git update for a Luna tree. Upgrades use Luna release bundles and preserve
  runtime state; a future automatic update channel must target this product explicitly.
- `hermes_cli/web_routers/actions.py`: update availability reports the same Luna bundle guidance,
  without querying or offering the engine's upstream update channel.
- `skills/productivity/powerpoint/SKILL.md`: distinguish developer-only pytest checks from
  document verification, since nested test trees do not ship in the slim runtime.

1. Import the new upstream tree (keep `NOTICE`'s version/commit line in step).
2. Re-apply the inventory below — each entry notes its provenance marker (`Luna 00NN` comments
   in the code locate most hunks). Deleted modules must be deleted again.
3. Run `scripts/test.sh` (luna unit + component + contract + replay) and the bounded upstream
   subset in `scripts/test.sh`. The contract tier is the gate: it fails when a re-vendor drops
   or drifts any recorded edit.
4. Update this file (inventory + version line) in the same change.

## Inventory — folded patch series (pre-P1 `luna/patches/` 0001–0015)

| File(s) | Provenance | Edit |
|---|---|---|
| `gateway/run.py`, `gateway/run_busy.py`, `gateway/run_turn.py` | 0001 | Per-surface output routing: `display.platforms.<surface>` resolves on the surface key so `telegram_group` (group) and `telegram` (DM) carry separate display policies. |
| `hermes_cli/web_server_chat.py` | The WebSocket credential compared `?token=` against the import-time `_SESSION_TOKEN`, the same inconsistency fixed on the REST paths — so with `HERMES_DASHBOARD_SESSION_TOKEN` set, the built WS URL carried a token the verifier rejected. Both the verifier and the URL builder now use `_active_session_token()`. |
| `hermes_cli/web_routers/models.py` | `MoaModelSlot.dict()` → `.model_dump()`; `.dict()` is deprecated in Pydantic v2 and removed in v3. |
| `plugins/platforms/telegram/adapter.py` | 0002 | Reply author: the quoted-message author ("[Replying to: …]") is preserved for identity/reply chains. |
| `hermes_cli/_parser.py` | 0003 | CLI branding: `prog="luna"`, product description. |
| `plugins/platforms/telegram/adapter.py` | 0004 | `progress_reactions` split from the reactions capability: reactions can stay on (self-wake tier) while hermes' own lifecycle reactions stay quiet. |
| `gateway/run_inbound.py`, `hermes_cli/plugins.py` | 0005 | Plugin message-injection reply anchor: injected messages can anchor replies like native ones. |
| `plugins/platforms/telegram/adapter.py` | 0006 | Observe-reply marker: the observe transcript carries a `[reply_to\|<id>]` line for `luna-logger`. |
| `gateway/run.py` | 0008 | Observed (unmentioned group) rows never replay as conversation turns. |
| `gateway/run_turn_runner.py` | 0009 | Streaming resolves on the surface key (`telegram_group` overrides `telegram`). |
| `gateway/operator_route.py` (new), `gateway/run_inbound.py`, `gateway/run_notifications.py`, `gateway/run_turn.py`, `gateway/run_turn_runner.py` | 0010 | Operator-DM routing (`Luna 0010`): approvals/clarify prompts, status cards and operational notices from group turns go to the operator DM; prompt replies correlate back to the group session (FIFO `register_forwarded_prompt`/`resolve_forwarded_session_key`); cron origin is exempt. |
| `cron/scheduler_delivery.py`, `tools/cronjob_job_args.py` | 0011 | Cron group envelope (`Luna 0011`): group/channel deliveries drop the management envelope and get chat rhythm; job origin records chat_type. |
| `cron/scheduler.py` | 0012 | `cron.disabled_toolsets` denylist layered last so a per-job enable cannot widen an unattended run (inert unless set). |
| `tools/cronjob_tools.py` | 0013 | Script/no-agent cron jobs are refused at create/update/run from a chat origin (`_chat_surface_script_denied`). |
| `gateway/run_config_loaders.py` | 0014 | Per-surface busy policy (`Luna 0014`): `display.platforms.<surface>.busy_input_mode` — groups queue follow-ups instead of interrupting. |
| `gateway/platforms/base.py`, `gateway/run_turn.py` | 0015 | Queued final reply anchor (`Luna 0015`): a queued chain's terminal reply anchors to the queued message (event stash `_luna_queued_reply_anchor`). |

### Behavioural notes (the old ledger's "overreach to know about")

- **0001** also rewires `show_reasoning` / display-bool resolution through the surface key (not
  just routing). `notify.operator_chat` is read as a namespace here; operator-DM *routing* is 0010.
- **0002** populates `reply_to_author_id`/`reply_to_author_name` in `_build_message_event`;
  consider upstreaming.
- **0005** the injected event reuses the *trigger's* message_id — anything indexing by
  `message_id` (e.g. luna-room's room log) would overwrite the trigger row. luna-room guards this
  by skipping injected/internal events entirely.
- **0008** observed rows are dropped from replay even when `separate_observed_context` is off — a
  config upstream honors is now ignored for observed rows. With the observe marker they stay the
  context-only wrapper; plugin-injected wake turns on the observe session are dropped (the wake
  brief already carries curated room context).
- **0009** the old lookup used the raw platform key, so `display.platforms.telegram.streaming: true`
  (owner DM) streamed group replies live even with `telegram_group.streaming: false`.
- **0010** every non-conversational send that reads `_status_chat_id` moves with the routing
  (status bubbles, interim, long-running notices) — broader than "prompts", and the point. Cron is
  exempt by construction and by the policy's `origin="cron"` guard.
- **0011** non-origin explicit targets with no known chat type are treated as group (the delivery
  layer's `is_dm_target` is False), so their envelope is stripped too. `cron.wrap_response: false`
  still disables wrapping everywhere.
- **0012** security posture: the dashboard Help page's Security section. **0013** likewise; operator CLI (no origin)
  is unaffected.
- **0014** a per-surface value now wins over the routed-profile snapshot for that surface.
- **0015** the handler returns text (not the result), so `_hmwa_deliver_turn_response` stashes the
  drain's `queued_terminal_inbound_id` on the event; `_queued_terminal_reply_anchor` prefers it.
  Telegram only; unanchored surfaces (topics/handoffs) and absent ids keep the old anchor.
- **0007-observation-hook** was never needed (fallback if the observe transcript proves
  unsuitable) — intentionally not implemented.

## Inventory — P1 feature trim (PRODUCT_PLAN §4)

| File(s) | Edit |
|---|---|
| `batch_runner.py`, `mini_swe_runner.py`, `trajectory_compressor.py`, `toolset_distributions.py` | **Deleted** — data-gen cluster, no product user. Their tests (`tests/test_batch_runner_*`, `tests/test_mini_swe_runner.py`, `tests/test_trajectory_compressor*`, `tests/tools/test_toolset_distributions.py`, `tests/integration/test_batch_runner.py`, `tests/integration/test_checkpoint_resumption.py`) go with them. |
| `mcp_serve.py`, `scripts/sample_and_compress.py` | **Deleted** — hermes-as-MCP-server for other editors + its data-gen helper script. |
| `hermes_cli/mcp_config.py`, `hermes_cli/subcommands/mcp.py` | `hermes mcp serve` command wiring and usage removed with `mcp_serve`. |
| `hermes_logging.py` | `batch_runner` dropped from the agent log-module map. |
| `hermes_cli/tips.py` | batch/trajectory tips removed. |
| `hermes_cli/plugin_catalog.py`, `plugin-catalog/` | Plugin catalog ships **empty and offline**: live fetch/cache machinery removed; `load_catalog_live`/`live_removed_list`/`get_live_catalog_entry` resolve the in-tree catalog only; bundled third-party entries deleted (`plugin-catalog/README.md` is the policy). |
| `hermes_cli/_parser.py` | Product subcommand hide-list (`PRODUCT_HIDDEN_SUBCOMMANDS`): non-product subcommands (`acp`, `bundles`, `claw`, `codex-runtime`, `computer-use`, `console`, `curator`, `debug`, `dump`, `import-agent`, `insights`, `journey`, `moa`, `monitoring`, `pets`, `prompt-size`, `slack`, `sync`, `webhook`, `whatsapp`, `whatsapp-cloud`, `worktree`) stay unregistered — their modules still import (main wires every builder eagerly) but never land in the argparse tree. Full module removal is P5. |
| `agent/trajectory.py`, `run_agent.py`, `gateway/slash_commands_model.py`, `hermes_bootstrap.py` | Comment/docstring only: stale references to removed modules. |
| `tests/gateway/test_plugin_message_injection.py` | Engine test updated for edit 0005 (`reply_to_message_id` kwarg on `_dispatch_plugin_message_injection`). Modified engine tests ride with their edits; deleted tests rode with their modules above. |

## Inventory — P2 companion API (PRODUCT_PLAN §5)

| File(s) | Edit |
|---|---|
| `plugins/platforms/telegram/adapter.py` | **Privileged approver gate.** Buttons that authorize an action (`ea:` exec approvals, `sc:` slash confirms) now require the tapping user to be listed in `allow_from`/`group_allow_from` or `allow_admin_from`/`group_allow_admin_from`. Previously they went through `_is_callback_user_authorized` alone, which honours the *chat*-scoped grant (`group_allowed_chats`) — so every member of a watched group could approve an arbitrary host command the model was about to run. Fails closed: with no id listed, nobody can approve. `cl:` clarify prompts deliberately stay on the general gate (conversational). |
| `hermes_cli/web_server.py` | Mounts the Luna companion API (`luna_cli.web_routers`, `/api/luna/*`) behind the existing `/api/` auth gate — guarded import; absent in an engine-only runtime. |
| `hermes_cli/web_server_config.py` | Merges `luna_cli.config_schema.LUNA_SCHEMA_FIELDS` into `CONFIG_SCHEMA` so every companion knob (`luna.*`, `honcho.*`, `display.platforms.telegram_group.*`) is a first-class form field. |
| `hermes_cli/web_routers/config_env.py` | Category order: the `companion` tab leads (`LUNA_CATEGORY_ORDER`). |

Product-side companions (no engine file): `luna/lib/luna_cli/{api_models,web_routers,config_schema}.py`,
`luna/lib/luna_core/peers.py` (shared identity ops), `web/src/pages/{BehaviourPage,PeoplePage}.tsx`.
Endpoint tests: `tests/hermes_cli/test_web_luna_routes.py`; model/schema tests: `luna/tests/unit/`.

## Inventory — P5 CLI retirement + rebrand (PRODUCT_PLAN D6)

| File(s) | Edit |
|---|---|
| `hermes_cli/subcommands/` | **21 builder modules deleted** — the non-product subcommands P1 hid from the CLI surface: `acp`, `bundles`, `claw`, `codex_runtime`, `computer_use`, `console`, `curator`, `debug`, `dump`, `import_agent`, `insights`, `journey`, `moa`, `monitoring`, `pets`, `prompt_size`, `slack`, `whatsapp`, `webhook`, `worktree`, `sync`. Their parser builders are gone from `main.py` (imports, build calls, `_BUILTIN_SUBCOMMANDS`, and the handler wrappers). Handler *helper* modules (`hermes_cli.webhooks`, `hermes_cli.dump`, `hermes_cli.debug`, …) stay inert; the `luna`-facing surfaces (`doctor`, `gateway`, `sessions`, `dashboard`, `config`, `mcp`, `cron`, `skills`, `plugins`) are untouched. |
| `hermes_cli/_parser.py` | The P1 `PRODUCT_HIDDEN_SUBCOMMANDS` filter + `_UnregisteredParser`/`_ProductSubparsers` sink are removed; `build_top_level_parser` returns the plain argparse subparsers action again. Branding (`prog="luna"`, Luna description) stays. |
| `hermes_cli/web_server.py`, `hermes_cli/dashboard_auth/login_page.py`, `hermes_cli/banner.py`, `hermes_cli/_startup_fast.py`, `hermes_cli/cli_info_mixin.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/subcommands/doctor.py`, `hermes_cli/web_routers/messaging.py`, `web/index.html` | Product-name rebrand: visible "Hermes Agent" strings (FastAPI title, dashboard/login/banner titles, version banner, update dialog, doctor description) read "Luna". The login page's external docs link now points at the in-dashboard Help page (`/help#authentication`). |
| `hermes_cli/web_server.py` | `_has_valid_query_token()` compared `?token=` against the import-time `_SESSION_TOKEN` while `_has_valid_session_token` uses `_active_session_token()`, so with `HERMES_DASHBOARD_SESSION_TOKEN` set the two paths disagreed about which token was live. |
| `hermes_cli/web_server_dashboard.py` | The session token was interpolated into the SPA HTML as `"{token}"`, unescaped, so an operator-supplied token containing a quote or `</script>` could break out of the script tag. Now `json.dumps` + `</` escaping, matching the adjacent `initial_profile_js`. |
| `hermes_cli/main.py` | The 21 non-product subcommand builders are removed: imports, `build_*` calls, `_BUILTIN_SUBCOMMANDS` entries, and the handler wrappers (`cmd_webhook`, `cmd_dump`, `cmd_debug`, `cmd_prompt_size`, `cmd_claw`, `cmd_import_agent`). `AI_AGENT` is deliberately **unchanged** (see below). |
| `AI_AGENT` (unchanged) | The `AI_AGENT` attribution marker stays `hermes-agent`. It is a registered id in the public agent-harness registry (`huggingface.js` `agent-harnesses.ts`), matched exactly; `luna-harness` is not registered, so tools would attribute the process as "unknown". A future registry entry can adopt the new name — pinned by `tests/hermes_cli/test_agent_env_advertisement.py`. |
| `pyproject.toml`, `hermes_cli/update_cmd_deps.py`, `hermes_cli/uninstall.py` | Distribution renamed `hermes-agent` → `luna-harness`. The install-verification probe reads the new name; `uninstall` removes either name so a legacy install is still cleaned up. Python import paths (`hermes_cli`, `agent`, `gateway`) stay — renaming them is a fork-wide change, not a rebrand. |
| `hermes_cli/tips.py`, `hermes_cli/cli_info_mixin.py` | Curated companion tips point to dashboard configuration and supported commands. Home placeholders resolve through `get_hermes_home()` at display time; CLI tips escape Rich markup. Real `.hermes.md`, `.hermes/`, `HERMES_*` and `hermes_tools` identifiers stay compatible. |
| `hermes_cli/main.py` | `cmd_chat` cwd-restore guard read `getattr(args, False)` — a literal `False` as the attribute name, so every `--resume` that reached it raised `TypeError: attribute name must be string, not 'bool'`. Now reads the `--worktree` flag it always meant to read. |
| `hermes_cli/web_server.py` | `_active_session_token()`: `HERMES_DASHBOARD_SESSION_TOKEN` now wins at request time over the import-time value, so setting it after import (desktop shell, embedders, tests) authenticates correctly instead of 401ing. |
| `tests/hermes_cli/test_config_read_guard.py` | `luna/lib/luna_core/config_read.py` added to the raw-config allowlist (it calls `load_config_readonly()` first; the raw branch only runs when the engine is absent). |
| `tests/conftest.py` | Kanban test files excluded from collection: they share hook registries and cached board paths across files and poison each other in a single-process batch. Kanban is not in the shipped Luna surface (P1). |
| `hermes_cli/cli_billing_mixin.py`, `hermes_cli/commands.py`, `hermes_cli/completion.py`, `hermes_cli/claw.py`, `hermes_cli/cli_tui_mixin.py`, `hermes_cli/projects_cmd.py`, `hermes_cli/telegram_managed_bot.py`, `hermes_cli/relay_plugin_migrate.py` | Rebrand completion: product copy (slash-command help, shell completions, billing notices and the TUI `agent_name` branding default) reads "Luna". The actual third-party `HermesSetupBot` account and published container image (`nousresearch/hermes-agent`) stay unchanged. |
| `web/src/**`, `apps/shared/src/**` | Dashboard rebrand completion: product name, theme presets ("Luna Teal"), plugin-catalog copy, and internal identifiers (i18n keys, `api.updateLuna`/`checkLunaUpdate`, `LunaConsoleModal`, `LunaSkin`, `LunaPluginSDK`, `buildGatewayWebSocketUrl`) across all 17 locales. `~/.hermes/` paths in user-facing copy now read `~/.luna/`. Wire contracts keep their names: the `X-Hermes-Session-Token` header, the `window.__HERMES_PLUGIN_SDK__` global (prebuilt plugin dists read it), and `/api/hermes/*` endpoint paths. |

## Not engine edits

Everything under `luna/` (plugins, `luna_core`, config templates, persona, deploy, tests,
docs) is product code and is not tracked here. `web/` dashboard extensions are product code
even when they live under engine paths — they are listed when they patch engine modules.

## Inventory — POLISH_PLAN P0 completion and implementation audit

| File(s) | Edit |
|---|---|
| `hermes_cli/completion.py` | Zsh profile discovery uses the same resolved Luna home for its directory check and glob, including custom homes. |
| `hermes_cli/telegram_managed_bot.py`, `hermes_cli/setup_platforms.py`, `hermes_cli/gateway.py`, `hermes_cli/web_server_messaging.py` | Telegram quick setup has no hosted default in the dashboard or developer setup helpers. Both read the shared configured URL; manual BotFather setup is the default. Visible channel descriptions use Luna; the distinct Hermes Relay connector name and actual Telegram manager account remain unchanged. |
| `hermes_cli/web_server_oauth.py`, `hermes_cli/web_server_config.py`, `hermes_cli/web_server_dashboard.py`, `hermes_cli/web_server_lifecycle.py`, `hermes_cli/web_server_gateway.py`, `hermes_cli/web_server.py` | Dashboard OAuth commands/status labels, restart and launch hints, and privileged gateway action guidance use Luna. Internal OAuth IDs, auth headers, import paths, API routes, and actual subprocess execution remain compatible. |
| `hermes_cli/web_routers/actions.py`, `hermes_cli/web_routers/sessions.py`, `hermes_cli/web_routers/_common.py`, `hermes_cli/web_routers/chat_ws_errors.py`, `hermes_cli/web_routers/messaging.py` | User-facing update/corruption/setup guidance names supported Luna commands. Updater translation is limited to exact engine phrases; image/package identifiers and third-party proper nouns are preserved. |
| `web/src/pages/{CharacterPage,ConfigPage,CronPage,ProfileBuilderPage}.tsx`, `web/src/lib/dirty-registry.ts`, `web/src/contexts/UnsavedChanges.tsx`, `web/src/components/DirtyBar.tsx`, `web/src/App.tsx`, `web/src/index.css` | P-1 audit follow-up: independent Character drafts survive unrelated saves; limits/colors and config forms are guarded; partial MCP drafts and cron profile selection participate in dirty state. Save-less entries cannot be saved away, delayed saves cannot resume a replacement navigation, and the opaque guard bar wraps on small screens with measured space beneath route content. Stale theme comments use Luna. |

Regression gates: the expanded dashboard brand scope in `test_brand_gate.py`, engine inventory,
Telegram opt-in contracts, runtime tip-home tests, CLI completion/setup tests, and real-page web
regressions. Existing prompt-cache, identity, output-policy and replay contracts remain the gates for
companion behavior. Release remains deferred by the operator.

## Inventory — Sakura dashboard redesign

| File(s) | Edit |
|---|---|
| `hermes_cli/config_defaults.py`, `hermes_cli/web_server_config.py` | Dashboard default is `sakura-dusk`; schema choices match the three frontend built-ins (`sakura-dusk`, `sakura-day`, `mono`). |
| `hermes_cli/web_server_dashboard.py` | Built-in IDs match the frontend manifest; retired preset names resolve to Sakura Dusk, with existing custom theme definitions taking precedence. Custom theme normalization and bootstrap CSS support optional light/dark `colorScheme`; fallback colors use the violet palette. Labels remain frontend-owned. |
| `hermes_cli/web_routers/dashboard_ui.py` | Active-theme GET and PUT share retired-name normalization. GET remains read-only; explicit theme changes persist the canonical name. Custom themes retain their names. |
| `tests/hermes_cli/test_web_server.py`, `tests/hermes_cli/test_web_server_config_offloop.py` | Pin the canonical default and theme write concurrency. The product contract tier (`luna/tests/contract/test_dashboard_theme_ids.py`) pins current IDs, schema/default agreement, preference compatibility, custom-theme precedence, and bootstrap CSS. |

Product UI changes: self-hosted Manrope and DM Serif Display fonts (OFL licenses included), native
Luna button/card/input/label/typography/badge primitives, crescent-and-blossom SVG identity, grouped
navigation, responsive shell, and redesigned Character/Behaviour/People pages. Runtime semantic CSS
variables remain overridable by the active theme rather than being inlined into utilities. Existing
save guards and companion behavior remain contract-tested. No deployment or gateway restart is
part of this redesign.

## Audit remediation engine seams

- Profile portability/defaults: `hermes_cli/product_runtime.py` seeds a neutral starter character
  and empty basic `PEOPLE.md`; `hermes_cli/config_defaults.py` applies the checked-in new-user
  template as product fallbacks. Setup completion and Honcho connection state remain explicit.
  `plugins/memory/honcho/client.py` applies only explicitly saved YAML tuning over an existing
  JSON client configuration. `hermes_cli/tools_config.py` honors explicit empty tool lists even
  when a companion plugin registers tools. Dashboard changes in `web/src/pages/ProfilesPage.tsx`,
  `web/src/components/ProfileTransfer.tsx` and `web/src/lib/luna-api.ts` expose versioned portable
  config/persona files. `web/src/pages/PeoplePage.tsx` displays the basic, model-writable directory.
  Product logic and round-trip/isolation tests live under `luna/`; details are in
  `luna/docs/profiles-and-people.md`.

- `agent/bedrock_adapter.py`, `agent/vertex_adapter.py`: importing provider binding/conversion
  helpers no longer installs unused AWS/Google dependencies. Installation occurs only when that
  provider needs its SDK. This fixes fresh installed chat hanging before its first model request.

- `hermes_constants.py`, `hermes_cli/_startup_fast.py`, `hermes_cli/product_runtime.py`:
  detect the Luna distribution before bootstrap, use its isolated default home, and pin child
  processes to the installed code and interpreter. Inherited Hermes TUI/source paths cannot win.
- `hermes_cli/config_home.py`, `hermes_cli/profiles.py`: first-run companion config, example
  persona, skin, skills and isolated memory workspace for fresh homes and named profiles;
  customized files are preserved. Only the exact untouched engine SOUL is migrated.
- `hermes_cli/plugins_discovery.py`, `plugins/memory/__init__.py`: discover overlay plugins and
  memory providers even when a named profile has no manually created plugin links.
- `hermes_cli/main_tui_launch.py`, `hermes_cli/web_server_chat.py`,
  `hermes_cli/web_server_gateway.py`, `hermes_cli/gateway.py`: dashboard chat and action/service
  subprocesses use Luna's active installation and selected profile. The release includes a bundled
  chat TUI and a pinned, checksummed Node runtime, independently of the source checkout.
- `hermes_cli/free_tier_bootstrap.py`: Luna never implicitly creates an upstream vendor account;
  setup status follows the selected configured provider. Configuration and verification differ.
- `agent/system_prompt.py`: companion fallback identity and dashboard setup guidance replace
  unconditional engine identity. Dynamic room context still uses the existing sidecar seam.
- `hermes_cli/skin_engine.py`, `tui_gateway/server.py`, `tui_gateway/change_watcher.py`:
  configured character name, product version and setup status reach the chat surface; explicit
  empty tool selections remain empty; persona changes refresh built-in as well as user skins.
- `hermes_cli/web_server.py`, `hermes_cli/web_routers/status.py`: dashboard/API version is the
  Luna release version; vendored engine attribution remains in NOTICE and the footer link.
- `ui-tui/src/{theme.ts,banner.ts}`, `ui-tui/src/components/branding.tsx`,
  `ui-tui/src/content/{setup.ts,placeholders.ts}`, `ui-tui/src/app/{uiStore.ts,useMainApp.ts,userMessages.ts}`,
  `ui-tui/src/app/slash/commands/core.ts`,
  `ui-tui/src/__tests__/{theme.test.ts,createSlashHandler.test.ts}`: companion chat identity,
  setup/update guidance, clean theme-colored banner and matching tests.
- `agent/agent_init.py`, `gateway/run_turn_runner.py`, `gateway/slash_access.py`: private file
  memory and external recall are surface-gated, group streams cannot bypass final shaping, and
  privileged chat commands fail closed when the owner list is empty.

- `hermes_cli/config.py`, `hermes_cli/config_lock.py`: engine saves and companion staged writes
  share thread/process locks; no read/modify/write overlap within a profile.
- `gateway/run_turn.py`: apply the companion capability policy before constructing or caching
  an agent. Groups and non-owner DMs receive narrow capabilities; owner matching uses transport IDs.
- `plugins/memory/honcho/client.py`: when Luna owns memory, reuse its profile connection resolver.
- `web/src/lib/api.ts`: companion endpoints follow the dashboard profile selector.
- `web/src/pages/SystemPage.tsx`, `web/src/components/LunaDataPanel.tsx`: delivery/retention coverage,
  dated memory verification, private backups, restore and previous-release rollback controls.
- `.github/workflows/luna.yml`: product CI only; inherited engine automation is archived outside
  the workflows directory. `luna-release.json` identifies product, engine, native and data versions.


## Thin launcher and managed memory

- `apps/bootstrap-installer/src-tauri/src/lib.rs`, `apps/bootstrap-installer/src-tauri/src/launcher.rs`:
  adapt the existing Tauri bootstrap into Luna's verified-runtime launcher, keeping the existing
  `events.rs` and `powershell.rs` console decoder and tests. Dashboard webviews cannot invoke
  setup commands: Rust checks the calling window label and bundled origin explicitly.
- `apps/bootstrap-installer/src-tauri/src/desktop_controls.rs`,
  `apps/bootstrap-installer/src/desktop-controls.tsx`: opt-in launch at login, background/tray
  preferences and authenticated existing-gateway start/stop with running-state verification.
  Tauri supplies tray/single-instance and macOS/Windows startup integration. Linux uses a small
  XDG adapter because the upstream auto-launch dependency ignores XDG_CONFIG_HOME and writes
  unquoted Exec arguments. Luna quotes its executable/home and keeps startup changes reversible.
- `apps/bootstrap-installer/src-tauri/Cargo.toml`, `apps/bootstrap-installer/src-tauri/Cargo.lock`,
  `apps/bootstrap-installer/src-tauri/build.rs`, `apps/bootstrap-installer/src-tauri/tauri.conf.json`,
  `apps/bootstrap-installer/src-tauri/capabilities/default.json`,
  `apps/bootstrap-installer/src-tauri/Info.plist`, `apps/bootstrap-installer/src/app.tsx`,
  `apps/bootstrap-installer/vite.config.ts`, `apps/bootstrap-installer/index.html`:
  Luna branding, pinned release descriptor, native menus, repair/update handoff, narrow native
  permissions and reproducible dependencies. Native icons derive from `web/public/luna-mark.svg`.
- `hermes_cli/_file_lock.py`, `hermes_cli/config_lock.py`: shared fail-closed flock/msvcrt locking,
  reentrant settings writers and native-worker leases. Windows needs no optional POSIX package.
- `hermes_constants.py`, `hermes_cli/product_runtime.py`: native Windows Luna home, atomic JSON
  release selection, release-local Python/Node and per-home Git Bash discovery.
- `scripts/install.ps1`: optional `LUNA_BOOTSTRAP_SCOPED=1` mode for the reused Git stage, retaining
  its compatibility/ASLR checks while suppressing User PATH/environment writes. The selected
  shell path is recorded only in the owned home. Other upstream installer flows are unchanged.
- `plugins/memory/honcho/client.py`: Luna's dashboard Honcho tuning feeds the existing behavior
  parser; actual cadence, effort, budgets and recall modes match the Memory page and CLI status.
  JSON identity/peer entries remain intact. Canonical profile connection resolution still holds.
  Explicit alternate Honcho config paths retain their own connection/tuning; bound refreshes of
  the canonical file continue to apply Luna's dashboard settings.
- `pyproject.toml`, `uv.lock`: the supported Luna extra includes pinned local ONNX/tokenizer and
  JSON-schema runtimes, so first memory setup does not build or fetch model code at inference.
- `web/src/pages/OnboardingPage.tsx`, `web/src/lib/luna-onboarding.ts`, `web/src/pages/MemoryPage.tsx`,
  `web/src/components/MemoryReasoningSelector.tsx`, `web/src/components/AutoField.tsx`,
  `web/src/App.tsx`, `web/src/lib/navigation.ts`: persistent optional setup, immediate chat,
  a dedicated Honcho status/tuning page, shared reasoning selection and accessible field labels.
- `web/src/themes/theme-runtime.ts`, `web/src/themes/context.tsx`, `web/src/themes/presets.ts`,
  `web/src/index.css`, `web/src/components/ui/Input.tsx`, `web/src/pages/ConfigPage.tsx`,
  `web/src/pages/DocsPage.tsx`, `web/src/pages/ChatPage.tsx`: shared Sakura rendering/typography,
  server-seeded appearance, local fonts for every built-in, theme-aware status colors, matching
  chat fallbacks, and mobile field/action wrapping. Launcher styling imports these primitives.
- `apps/bootstrap-installer/src/theme.ts`, `apps/bootstrap-installer/src/styles.css`,
  `apps/bootstrap-installer/src/main.tsx`, `apps/bootstrap-installer/tsconfig.json`,
  `apps/bootstrap-installer/package.json`, `package-lock.json`: use the same Luna renderer,
  controls, mark and bundled fonts, following the owned dashboard's persisted appearance.
- `hermes_cli/web_server.py`, `hermes_cli/web_server_dashboard.py`: keep `/docs` for the Luna SPA
  instead of Swagger; inject profile appearance before React renders and support pre-paint
  built-in palettes. Font assets work under the existing proxy prefix handling.
- `hermes_cli/dashboard_auth/login_page.py`, `hermes_cli/dashboard_auth/middleware.py`,
  `hermes_cli/dashboard_auth/routes.py`, `hermes_cli/auth_device_flow.py`,
  `hermes_cli/session_export_html.py`: Luna-branded sign-in/completion/empty/export surfaces,
  shared palette assets, prefixed login assets/actions and offline typography for standalone HTML.

Overlay implementation and current evidence are in `luna/docs/beginner-setup-plan.md` and
`luna/docs/windows-launcher-reuse.md`. Native Windows certification and published download URLs
remain release gates; a Linux build or a Tauri window alone is not a portability claim.

## Group turn taking and portable output controls (2026-10-25)

- `gateway/platforms/base.py`: invoke Luna room admission before busy-session merging or typing;
  text batches remain author/reply-chain-specific even in shared topics. Bind a selected event's
  ContextVar, pin its reply anchor, suppress expired/cancelled text/media/retries and preserve
  silence markers. Selected room replies skip generic crash redelivery, which lacks their
  deadline/anchor. Old follow-up drains return through admission. DMs retain normal delivery.
- `gateway/run_turn.py`: a revoked target suppresses pre-adapter voice/final delivery; queued
  work cannot recurse inside another person's selected reply frame.
- `gateway/run_inbound.py`: plugin injection reports success only when adapter admission gives
  a receipt. A declined autonomous wake is no longer falsely reported as accepted.
- Overlay-only changes implement admission, per-topic context/recall and PEOPLE scopes,
  admission-aware indexing, dashboard controls/status, and protected optional sentence line
  breaks. No dynamic state was added to system/channel prompts or the cache signature.
  The real native OpenCode context verifier now checks the changing transport target as well
  as byte-identical system/resume prefixes.


## Harness branding and companion names (2026-10-25)

- `hermes_cli/skin_engine.py`: companion speaker branding follows the selected persona; a
  missing/blank name falls back to Companion. Product headers still identify the Luna harness.
- `hermes_cli/commands.py`, `gateway/run.py`, `gateway/run_busy.py`, `gateway/run_turn.py`,
  `gateway/run_turn_runner.py`, `gateway/run_notifications.py`, `gateway/relay/command_manifest.py`:
  visible status/help text distinguishes runtime operations from companion replies. No transport
  command names, compatibility identifiers, authorization, wake gates or cache signatures change.
- `hermes_cli/dashboard_auth/login_page.py`: Luna favicon on sign-in and unavailable-auth pages,
  including reverse-proxy prefixes. Existing source attribution remains in LICENSE/NOTICE.
  `hermes_cli/web_server_dashboard.py` also rewrites the SVG favicon URL under proxy prefixes;
  the existing no-store/index asset test covers this path.
- `web/src/`, `web/public/`, `apps/bootstrap-installer/src/`,
  `apps/bootstrap-installer/src-tauri/{tauri.conf.json,icons/}`: harness copy, companion wording,
  local credits, shared theme-aware controls and canonical icon assets. Actual provider names and
  compatibility-facing API/config/storage identifiers remain intact.
- `ui-tui/src/app/slash/commands/{core,wake}.ts`,
  `ui-tui/src/components/{journey,gridStreamsDemo}.tsx`, `ui-tui/src/lib/terminalParity.ts`:
  transcript history uses the configured character's label; runtime/help copy uses Luna or neutral
  wording. Billing-provider attribution continues to name the real service.
- Companion name labels in `luna_core.room` and the room/ambient plugins remain per-turn room
  metadata. No dynamic name, history or roster is inserted into the cached system/channel prompt.
  Ambient substance/settle prefilters now use escaped, bounded configured names/aliases rather
  than the literal harness name. Thresholds, budgets and the default-disabled reaction tier stay
  unchanged; `luna/tests/fixtures/wakes/companion_names.json` gates that distinction.

## Ambient/Jev audit remediation — 2026-10-26

- `hermes_cli/plugins.py`: additive `gateway_ready` / `gateway_stopping` lifecycle hooks tie the
  ambient worker to a real injector owner. `PluginContext.inject_message` optionally forwards a
  trusted in-process `luna_delivery` receipt; the existing scheduling boolean remains unchanged.
- `gateway/run_inbound.py`: preserve the source timestamp and receipt on injected wakes, check the
  owner's relevance lease before adapter admission, and complete rejected/cancelled scheduling.
- `gateway/platforms/base.py`: check wake cancellation before generation and delivery; final
  transport results complete receipts with delivered content/message identity. Generation alone
  cannot populate the wake ledger or outgoing room history. The product overlay owns receipt
  policy, source/topic isolation and retry-time cancellation guards.

Regressions: `luna/tests/component/test_ambient_jev_regressions.py`,
`luna/tests/component/test_room_dispatch_gateway.py`, and
`tests/gateway/test_plugin_message_injection.py`. Cached system/channel prompts are unchanged.

Release platform dependency fix (2026-10-26): `pyproject.toml` and `uv.lock` select pinned
ONNX Runtime 1.23.2 for Intel macOS and 1.27.0 elsewhere. The native launcher now declares
macOS 14+ to match its dependency floor. Actual archive installation/embedding inference
gates every native platform, including Intel Macs.

Windows encoding follow-up: the native launcher's managed Python children, desktop installer
and `hermes_cli/product_runtime.py` child environments select UTF-8. Isolated `-I` installer
checks also pass `-X utf8`, since isolation ignores Python environment settings. This keeps
Unicode templates/personas independent of a Windows account's legacy code page. The native
command test and real Windows archive installation cover this contract.

- Alpha 2: `agent/auxiliary_client.py` forwards the caller timeout through the
  Anthropic auxiliary adapter, including memory reasoning. Covered by the adapter
  timeout regression in the companion setup component tests.

Security and guided setup (2026-10-26):
- `pyproject.toml`, `uv.lock`, npm manifests/locks and `.npmrc` raise reviewed vulnerable versions
  to patched releases. `tools/lazy_deps.py` uses the same patched optional dependency pins.
- `web/src/App.tsx` and `web/src/contexts/PageHeaderProvider.tsx` hide dashboard navigation during
  the focused Setup flow. Existing routes, profile isolation and chat lifetime are preserved.
- Credential-shaped test literals are split into adjacent strings in inherited tests; their
  runtime values and redaction assertions are unchanged. Documentation uses token placeholders.
- The native launcher's GTK3/glib backport is documented under
  `apps/bootstrap-installer/src-tauri/vendor/README.md` and gated by its exact source hash.
- Retired the inherited `nix/`, `flake.nix` and `flake.lock` packaging path. It builds
  the upstream Hermes/Electron distribution, not Luna's released thin launcher, and
  carried an independent stale node-gyp lock. Supported Luna installers are documented
  in the root README and desktop-release guide.
- `web/vite.config.ts` initializes the optional compiler filter under the patched Vite
  types. The runtime bundle filter is unchanged.
- `web/src/components/OAuthProvidersCard.tsx` defaults to browser-supported account flows,
  with terminal instructions and token previews omitted from guided account setup.
  Persona application in Setup targets the selected management profile.

Desktop interaction polish (2026-10-26):
- `web/src/App.tsx`, `web/src/lib/navigation.ts`, `web/src/pages/ControlCenterPage.tsx`:
  common model/account/key controls are gathered above companion navigation; management
  routes remain available in More. Chat's persistent terminal lifetime is unchanged.
- `web/src/components/ChatSidebar.tsx`, `web/src/lib/eventsFeedClient.ts`,
  `web/src/pages/ChatPage.tsx`, `web/src/components/ModelReloadConfirm.tsx`:
  the toolbar subscribes to the actual chat rather than spawning a second agent. Completed
  replies copy directly to the clipboard without typing into the composer. New model
  confirmation starts a fresh chat. Pending event tickets cannot open after unmount.
  Bounded reconnect/auth handling, profile scoping and stored conversation identity remain.
- `web/src/pages/{EnvPage,OnboardingPage}.tsx`, `web/src/components/ui/{Button,Input,Card}.tsx`,
  `web/src/index.css`: searchable keys, configured advanced keys remain visible, collapsed
  optional categories, flat provider rows, inherited card corners and shared interaction
  feedback. Native canvas stays opaque; document crossfades and selection-driven root
  style mutations are removed. Native chat uses the DOM terminal renderer to avoid an
  additional WebGL compositor. Text stays at least 13px with readable line spacing.
- `ui-tui/src/components/appLayout.tsx`: embedded dashboard chat gets a short empty state;
  standalone terminal intro remains intact. The shared Ink transcript/composer is retained.
- `apps/bootstrap-installer/`: frameless launcher, verified-byte progress with transfer totals,
  elapsed setup checklist, cancellable stalled network operations, and an anchored settings
  drop-up. macOS retains its native application menu; other platforms retain tray controls.
  Window-control permissions are limited to the bundled installer, never the dashboard.

Regression coverage: ChatSidebar/ChatPage component suites and native cancellation tests.
No dynamic prompt, cache key, companion memory policy, identity, or wake thresholds change.

Desktop polish follow-up:
- `web/src/components/{ModelPickerDialog,OpenCodeSetup,OAuthProvidersCard,MemoryReasoningSelector}.tsx`,
  `web/src/components/ui/Select.tsx`, `web/package.json`, `package-lock.json`: connected models
  first, in-app connection actions, retained price confirmation, themed portalled dropdowns and
  compact guided account/model controls. Unauthenticated models cannot be applied.
- `web/src/components/AppearanceSettings.tsx`, `web/src/pages/{CharacterPage,ControlCenterPage}.tsx`:
  chat palettes move to Preferences, with guarded drafts and advanced individual colors.
- `web/src/pages/OnboardingPage.tsx`: compact steps, visible Telegram owner/group fields,
  default-admin DM access and preserved existing grants; persona previews use the shared library.
  `web/src/lib/{luna-api,luna-onboarding}.ts` carry preset samples/current selection metadata.
- Dashboard regression suites cover active-profile persona application, optional skips, default
  admin transport access, independent draft saves, passive chat subscription and price confirmation.
- `scripts/test.sh` and `scripts/test-contract.sh` put this checkout's overlay first on PYTHONPATH
  so a legacy editable installation cannot silently supply the engine contract imports.

Persona template changes apply to new installs or explicit preset selection. Per-turn sidecars,
cache signatures, transport identity and wake thresholds remain unchanged.
- `scripts/verify_dashboard_chat.py`: the real bundled-chat acceptance fixture supplies its own
  skin/input-prompt marker for keyboard readiness. It no longer waits for the decorative CLI
  banner removed from embedded chat. Product imports also occur after binding the disposable home.
  Persona/runtime/PEOPLE context and response assertions remain.

2026-10-26 onboarding hotfix:
- `agent/model_metadata.py`, `hermes_cli/{codex_models,models}.py`: Codex catalog uses
  the verified 0.164.0 compatibility version; 0.0.0 now returns a legacy catalog. The
  version participates in the catalog cache fingerprint. Current general models are
  available offline; account-gated Astra still requires live discovery.
- `web/src/components/{ui/Select,ChatSidebar,GatewayControls}.tsx`,
  `web/src/contexts/SystemActions.tsx`, `web/src/lib/gateway-lifecycle.ts`,
  `web/src/pages/{OnboardingPage,ControlCenterPage,SystemPage}.tsx`: selected dropdown
  labels survive disabled/save states; stable numbered steps; Telegram Save & connect
  enables and connects the platform. Control Center exposes live gateway controls.
  Start/stop/restart verify gateway state/process identity with a 30-second deadline;
  a restart child becoming the foreground gateway no longer causes endless spinners.
- `ui-tui/src/components/appLayout.tsx`, `web/src/pages/ChatPage.tsx`,
  `web/src/index.css`, `agent/agent_init.py`: readable bounded chat canvas, bottom
  composer, quiet embedded status, empty-state copy only before the first message,
  and suppression of the embedded chat's one-time CLI compaction tutorial. The shared
  Ink chat, actual compaction behavior and prompt cache remain intact.

Focused validation: current live account catalog (IDs only), Codex catalog regressions,
Telegram onboarding save/connect, dropdown persistence, foreground restart completion,
stalled-request timeout, TypeScript and production dashboard/TUI builds.

2026-10-26 portable gateway start correction:
- `hermes_cli/gateway.py`: Luna start uses the existing foreground gateway when
  no Linux/macOS service is installed. The dashboard already detaches the child.
  Installed services, explicit system-service requests and Windows behavior are
  retained. Covered by `tests/hermes_cli/test_luna_gateway_start.py`.
- `hermes_cli/web_server_gateway.py`: dashboard action children run from the
  selected runtime directory, preventing Python's current-directory precedence
  from loading code from a prior release after an update. Service actions use
  the existing scoped action runner and logs.
- `hermes_cli/gateway.py`: generated service virtualenv paths resolve the selected
  desktop runtime; the OS description identifies Luna.
- `hermes_cli/web_routers/ops.py`, `web/src/{components/GatewayControls.tsx,lib/api.ts,lib/gateway-lifecycle.ts}`:
  explicit user-account background-service install/start-at-login and removal
  controls. Setup stops the direct gateway first, verifies the installed service
  and running gateway, and bounds the operation. System-managed services and
  multiplexed foreign profiles are refused before mutation. No service is installed
  by default. Removal stops the service; direct Start remains available.
- Focused regressions cover service auth, refusal/ownership boundaries, service
  command flags, selected-runtime action cwd, and finite service-setup UI states.

- `gateway/status.py`: recognize exact Luna module/script/binary entrypoints in
  the existing gateway process identity checks. Direct Start execs the canonical
  run command so liveness, stop, restart and the one-poller lock agree. Non-gateway
  commands and unrelated Python command strings remain excluded.
