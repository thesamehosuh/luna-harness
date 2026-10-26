# Luna rebrand + dashboard polish — plan

Audit date: 2026-10-05. Scope: the whole tree, with the dashboard (`web/` + `hermes_cli/web_routers/`)
as the centre of gravity.

Baselines verified green before writing this: `web` typecheck clean, `vitest run` → 51 files / 354 tests
passing. Every phase below must keep both green.

> **Current verified state (2026-10-09 Sakura redesign):** `npm run check` passes:
> typecheck clean, **63 files / 554 tests**, **0 lint errors / 31 warnings** (33 at this audit's
> start). `npm run build` succeeds. The updated contract script passes **124 Luna contracts +
> 145 upstream gateway tests**; the preceding full audit passed **557 Luna tests**. P-1 and P0
> are implemented. The Sakura theme, core visual primitives, navigation/header shell, and three
> companion-page layouts are now implemented; the remaining P1–P6 work below is not complete.
> PRODUCT_PLAN's completed P6 hardening is a separate milestone. Release remains deferred by
> the operator. These changes are in the working tree, not a release or a commit.

### Sakura redesign — 2026-10-09

- **Reference direction:** midnight violet, blossom pink, lavender, warm gold, curved petal detail.
  The previous teal preset's renamed label did not deliver this identity. Sakura Dusk is now the
  actual default; Sakura Day and Mono complete the three built-ins. Day's primary accent is
  `#A65370`, darkened from the proposed `#B96A84` to meet normal-text contrast on filled controls.
- **Preference compatibility:** retired built-in IDs migrate to Dusk on both sides. A real custom
  definition with a retired name wins. A newer frontend hides retired preset entries from a still
  running older server. Theme labels remain frontend-owned; GET normalization is read-only.
- **Shared visual foundation:** local, licensed Manrope and DM Serif Display fonts; native Luna
  buttons, cards, inputs, labels, typography and badges; crescent-and-blossom logo/favicon. Semantic
  color utilities now read runtime theme variables. Old inline utilities bypassed those overrides;
  the vendor's default badge also carried hardcoded yellow text that failed in light mode.
- **Shell and companion pages:** one navigation manifest drives grouped links, titles and
  breadcrumbs; larger display headings, wrapping toolbars, clear selected links, mobile focus
  containment and a skip link. Character has an editor/preview layout and section navigation;
  Behaviour and People have matching botanical headers, wrapping actions and local table scrolling.
  Save guards and the chat host lifecycle are preserved.
- **Visual verification:** the actual SPA was checked at 390 / 768 / 1440px with isolated synthetic
  API data, including both Sakura palettes, mobile menu keyboard focus, Save-and-leave, and local
  table scrolling. The production build was separately served and checked: pink button/card colors
  apply, both local fonts load, and default themes make no external resource requests. This covers
  the companion screens and shared shell. A subsequent bounded audit passed all 144 combinations
  of 24 routes × Sakura Dusk / Sakura Day / Mono × desktop / 390px, plus sign-in in all themes.
  That audit fixed mobile Config/Setup overflow and the FastAPI Swagger collision at `/docs`.
- **Still pending:** remaining foundation/state/table primitives, route-specific migrations,
  onboarding/System restructuring, command palette and full localization. Login, OAuth completion,
  HTML exports, launcher styling, CLI-skin alignment and runtime release packaging now use shared
  Luna assets; native lifecycle controls have real Linux acceptance coverage. No live
  deployment, gateway restart, release, or unrelated backend commit is included.

### Implementation audit — 2026-10-09

- **Character draft preservation:** saving persona, output limits, skin/colors or skills now
  updates only that saved slice. Unrelated drafts survive. Limits and colors have independent
  dirty guards, color edits are guarded before skin changes, and inputs are disabled during writes.
  Tests render the real page and cover cross-card saves, failures and draft export.
- **Guard completeness:** Config form edits now have a saved baseline alongside YAML; mode changes
  and imports are guarded, YAML discard restores synchronously, and responses cannot mark newer
  edits saved. Partial MCP wizard drafts and cron target-profile changes count as dirty.
- **Guard races and mobile layout:** Save-and-leave requires every dirty entry to be saveable;
  failed writes hold navigation, duplicate saves are blocked, and delayed saves cannot resume a
  replacement navigation after Stay. The opaque, wrapping bar reserves its measured height beneath
  route content. An isolated real-page browser fixture verified success/failure navigation and
  reachable actions at 390 / 768 / 1440px; the last Character controls remain clear at 390px.
  This was not the pending full route × theme screenshot sweep.
- **Truthful brand/setup copy:** tips now describe supported commands and dashboard configuration;
  home references resolve through the runtime home resolver and escape Rich markup. Zsh profile
  discovery honors custom homes. Telegram developer setup helpers share the dashboard's configured
  service URL, with no hosted default and manual setup first. OAuth, channel descriptions, update,
  repair and launch guidance use Luna. Actual Hermes Relay, HermesSetupBot, package/image names,
  `.hermes` project identifiers and `HERMES_*` contracts remain intact. The brand gate now includes
  CSS and the backend copy helpers; updater translation uses exact phrases with documented exemptions.
- **Verification tooling:** both test scripts honor `PYTHON`; the contract script runs the same
  bounded upstream private-API subset as the full script. Engine changes are inventoried in
  `luna/docs/engine-vendor.md`. Focused CLI/auth/copy/tips tests passed (102), as did the separately
  reviewed backend/setup regressions. Temporary browser fixtures and the dev server were removed.

**Next:** remaining P1 foundations and P3/P4 route-specific work. P6 must still make dashboard
artifacts reproducible from a clean checkout:
`hermes_cli/web_dist/` has zero tracked files and is ignored. The successful local rebuild refreshes
this checkout only; it does not resolve the slim-runtime packaging gap or authorize release.

---

## Desktop interaction pass — 2026-10-26

The launcher, Control Center, chat toolbar and guided Setup have been updated in the desktop-polish
branch. System actions remain visible outside More. Chat colors live in Preferences; the embedded
Ink chat remains the primary conversation UI. Setup and Character share the new persona library.
See `luna/docs/desktop-polish.md` for the implemented scope and rendering evidence. The older
verification/environment notes above and below are historical; the checkout venv now runs both
Luna and the bounded engine contract subset. No release is authorized by this pass.

## 0.0 Environment facts — read this before running anything

Every item here cost real time to discover. They are facts about the machine and the scripts, not
about the code, so they do not show up in a diff.

**There are two Python environments, and they are not interchangeable.**

| Interpreter | Has | Use it for |
|---|---|---|
| `.venv/bin/python` | fastapi, pyyaml, psutil, httpx. **No `rich`, `prompt_toolkit`, or `kawaii`.** | `luna/tests/**` |
| `~/.luna/venv/bin/python` (`$HERMES_HOME/venv`) | the full upstream runtime + pytest | `tests/hermes_cli/`, `tests/gateway/` |

- Running `tests/hermes_cli` with `.venv` gives **118 collection errors** (`No module named 'rich'`).
  That is the wrong interpreter, not broken tests. The same tree collects **12,434 tests, zero errors**
  under `~/.luna/venv/bin/python`.
- `scripts/test.sh` and `scripts/test-contract.sh` now prefer `.venv/bin/python` automatically when
  `PYTHON` is unset (they used to hardcode `python3`, which has none of the declared deps — the reason
  `scripts/test.sh` "failed"). Both scripts still auto-detect `$HERMES_HOME/venv` for the upstream
  subset.
- **The Luna suite takes several minutes** (557 tests, ~6 minutes on the latest run). It is not
  hung; do not kill it. Counts above are the latest verification, not the original baseline.
- **The contract tier is fast** — use `scripts/test-contract.sh` while iterating on anything in
  `luna/tests/contract/`; it also runs the bounded upstream gateway subset when available.

**Test placement follows from the table.** A contract test belongs in `luna/tests/contract/` if it
should gate the dashboard work, because that tier is in `scripts/test.sh` and runs in 0.7s.
`tests/hermes_cli/` is upstream CI's business (see the comment in `scripts/test.sh`) and needs the
full runtime — a contract placed there is a contract nothing runs locally. This is why P0 item 4's
id-set contract went into `luna/tests/contract/`.

**Shell gotchas that produced false results.**

- `cmd | tail -5 && echo OK` exits 0 even when `cmd` failed, because the pipeline's status is `tail`'s.
  This printed a false "TYPECHECK CLEAN" during P0. Check `${PIPESTATUS[0]}` or drop the pipe.
- In a scratch worktree, `npx tsc` fails to resolve even after symlinking `web/node_modules`; the
  hoisted root `node_modules` is what carries `tsc`. Symlink **both**:
  `ln -s <repo>/node_modules <wt>/node_modules && ln -s <repo>/web/node_modules <wt>/web/node_modules`.
- `grep -c` exits 1 when the count is 0, which silently truncates an `&&` chain. The count is
  printed *and* the command "fails".

**Lint baseline: 0 errors / 33 warnings. Do not add warnings.**

- The earlier note in this file claiming several Luna pages (`BehaviourPage`, `CharacterPage`,
  `HelpPage`, `OnboardingPage`, `PeoplePage`) are **untracked** is **stale** — 86d1971 tracked them.
  `web/` and `apps/shared/src/` are fully tracked and clean, so `git stash` and `git stash -u` now
  behave identically there and a before/after lint diff is trustworthy.
- 416 files are still uncommitted (the backend/rebrand layer: `luna/`, `hermes_cli/`, `gateway/`).
  Several P0 files are **already dirty from that layer**, so `git add <file>` would sweep in
  someone else's unreviewed work. Stage hunk-by-hunk: filter `git diff -U3 -- <file>` and
  `git apply --cached --recount` only the hunks that are yours. Verify with
  `git diff --cached -- <file> | grep -c <their marker>`.

---

## 0. Decisions taken

Two were open at audit time; both are settled and the plan assumes them.

**D-A. Telegram "Create with QR" → config escape hatch, default off.**
Add `luna.telegram.onboarding_service_url`, default empty. When unset, the QR panel in
`ChannelsPage.tsx:1061-1310` hides itself and manual token entry becomes the only path; when set, it
points at whatever service the operator chooses. Also fix the `HermesDashboard/<ver>` UA to
`Luna/<ver>`, and change the "recommended" badge to name whoever operates the service.
Rationale: self-hosters shouldn't silently depend on Nous Research's infrastructure for the path we
label recommended, and the config key follows AGENTS.md §6 (new key → template **and** dashboard
schema field). Manual setup already exists and is already offered, so nothing is lost.

**D-B. Ship 3 themes, not 8.**
`sakura-dusk` (new default), `sakura-day` (new light), `mono` (retained as a genuine accessibility
affordance). Retire `default`, `default-large`, `nous-blue`, `midnight`, `ember`, `cyberpunk`,
`rose`, aliasing every retired id in `THEME_NAME_ALIASES` → `sakura-dusk` so saved preferences
resolve instead of silently resetting. Rationale: each theme is a palette that must pass contrast,
honour `colorScheme`, and look deliberate next to the new default; shipping four nobody should pick
is four chances to ship something ugly. `cyberpunk` in particular is the opposite register from the
brief.

---

## 1. Where we actually are

### 1.1 The rebrand is ~40% done, and P5's checklist overstates it

`PRODUCT_PLAN.md:198-208` claims "Titles/login/banner/version/update/doctor/**messaging** read 'Luna'
across the dashboard (all 17 locales), shared lib, and CLI help". Verified false in four places, and
`luna/docs/engine-vendor.md:124-125` records rebrands that were never made — which means the
re-vendor procedure would faithfully reproduce the gaps next time.

**Done and correct:** root `README.md` / `NOTICE`, `pyproject.toml` → `luna-harness`,
`web/index.html` title, `web/src/i18n/*.ts` (all 17 locales, zero "Hermes"), `web/src/themes/presets.ts`
→ "Luna Teal", the five new companion pages, `LunaConsoleModal`, `web_server.py` FastAPI title,
`login_page.py` title, CLI `prog="luna"`, `display.skin: luna` + `luna/config/skins/luna.yaml`,
`on-disk home = ~/.luna`.

**Not done, in order of how badly a user notices:**

| # | Surface | Evidence | Why it matters |
|---|---|---|---|
| 1 | **Telegram / group-chat static messages** | `locales/*.yaml` — 289 matches, 238 lines, 17 files. `/help` header is `📖 **Hermes Commands**`, `/status` is `📊 **Hermes Gateway Status**` | This is *the product surface*. The companion's actual voice in the room still says Hermes. |
| 2 | **Telegram "Create with QR" quick setup** | `web_server_messaging.py:376-377,395` → `https://setup.hermes-agent.nousresearch.com`, UA `HermesDashboard/<ver>`; `telegram_managed_bot.py:16,145,151,155,197` → `HermesSetupBot` | The *product surface* points at a Hermes-branded Nous service. **Scope correction:** P3's wizard does **not** use it (`OnboardingPage.tsx:124-141` takes a pasted token), and `ChannelsPage`'s panel already offers a **manual setup** path beside the QR path (`ChannelsPage.tsx:1300-1310`). So Luna is not *blocked* — it just advertises a foreign brand on its recommended button. |
| 3 | **`luna --help` examples** | `_parser.py:77-125` — 49 epilog lines starting `hermes`; the `luna_cli/main.py` shim patches only `prog` + `description` | The help output is unusable as written. |
| 4 | **`luna <TAB>`** | `completion.py` emits `complete -F _hermes_completion hermes` / `compdef _hermes hermes` / `complete -c hermes` | Shell completion is dead for the product's own binary. |
| 5 | **Paths in dashboard copy** | `ChannelsPage.tsx:135,167` prints `~/.hermes/.env`; `:137,168` prints `hermes gateway start`; `EnvPage.tsx:917`; `OnboardingPage.tsx:265` (`$HERMES_HOME/.env` — *inside* the new wizard) | Directly contradicts the `~/.luna` reality, and P5 claims it was fixed. |
| 6 | **External docs links** | `DocsPage.tsx:8` + `PluginsPage.tsx:923` → `hermes-agent.nousresearch.com/docs` (iframed as a whole page) | The Docs nav item is a foreign product's docs. |
| 7 | **Theme label divergence** | backend `web_server_dashboard.py:249-250` serves `"Hermes Teal"`; frontend `presets.ts:70` says `"Luna Teal"`; `themes/context.tsx:480-497` prefers the server label | The picker shows "Hermes Teal". One of the two lists is a lie and nothing catches the drift. |
| 8 | **`web_server.py:1310,1312`** | `"Hermes backend listening…"`, `"Hermes Web UI → …"` | The two lines printed on every dashboard launch. |
| 9 | **24 platform card descriptions** | `web_server_messaging.py:26-215` — "Run Hermes from Telegram DMs…", "Connect Hermes to Discord…" | |
| 10 | **19 router strings + ~90 `hermes_cli` string literals** | full table in the audit; `chat_ws.py:157` `_CONSOLE_PROMPT = "hermes> "` is the dashboard console's own prompt | |
| 11 | **Vendored brand assets** | `web/public/favicon.ico` is the upstream Hermes mark; `web/public/fonts/{Collapse,Rules*,Mondwest}.woff2` are Hermes display faces loaded by the login page; `apps/desktop/assets/icon.png` is the upstream avatar | There is no Luna logo anywhere. The only Luna mark is the ☾ glyph. |
| 12 | **Upstream docs shipping into `~/.luna`** | `cli-config.yaml.example` (161 hits), `README.{es,zh-CN,ur-pk}.md`, `CONTRIBUTING*`, `SECURITY*`, `Dockerfile`, `docker-compose*` — none are in `assemble.sh`'s exclude list | |
| 13 | **Two CLIs in one venv** | `pyproject.toml:413-415` still installs `hermes`/`hermes-agent`/`hermes-acp`; `install.sh:43,48` does `pip install -e` | A Luna install has both `luna` and `hermes` on PATH. |
| 14 | **Stale i18n artifact** | `en.ts:59` `app.brandShort: "HA"` — Hermes Agent initials | |

**Do-not-touch list** (deliberate, and the plan must say so out loud): `HERMES_HOME` (6,119 refs),
`~/.hermes` engine default, `X-Hermes-Session-Token`, `window.__HERMES_*` (`__HERMES_PLUGIN_SDK__` is
read by prebuilt plugin dists), `/api/hermes/*`, the `hermes-cli` toolset id (contract-tested),
`hermes-gateway-bede7b14.service`, `AI_AGENT = "hermes-agent"` (registered in the public
`huggingface.js` agent-harnesses registry), and all Python import paths. These are the engine, not
the brand.

### 1.2 The dashboard's real problems

Verified counts (`web/src`, 194 files / 58.6k lines):

- **Three parallel "muted text" vocabularies**: `text-muted-foreground` 403, `text-text-tertiary` 81,
  `text-text-secondary` 71, `text-midground` 23. Four surface idioms: `border-border` 157,
  `border-current/20` 31, `bg-card` 22, `bg-background-base` 11, `bg-background/*` 53. The
  shadcn-compat layer in `index.css:154-187` exists to paper over this.
- **No type scale.** Four font stacks in active use (`font-mono` 130, `font-mondwest` 65,
  `font-courier` 14, `font-expanded` 2), 101 `uppercase`, 50 arbitrary `tracking-[…]`, 29 `text-[…]`
  (22 of them `text-[0.xxrem]` micro-sizes). Sidebar nav is `uppercase text-sm tracking-[0.12em]`; the
  page `<h1>` is `font-expanded text-sm tracking-[0.08em]`. The loudest text on screen is the *least*
  readable.
- **No state vocabulary.** Loading = `<Spinner>` (94×, 29 files). Empty = hand-copied markup (18 sites,
  12 files, three competing spellings). Error = 2 shared + ~60 inline `text-destructive` boxes.
  `LoadErrorNotice` is used by 2 of 24 pages. No `Skeleton` component exists.
- **Three dialogs for one job.** Local `components/ConfirmDialog.tsx` (z-200) vs DS `ConfirmDialog` vs
  a `DeleteConfirmDialog` wrapper; only 4 files use the DS `Dialog`; 19 hand-rolled `createPortal`
  overlays, 13 hardcoded backdrops, `z-[100]` 21× / `z-[200]` 1×.
- **No focus trap anywhere**, despite `role="dialog" aria-modal="true"` in `ConfirmDialog.tsx:62-65`.
  `useModalBehavior` documents the omission as future work.
- **Reduced motion honored in exactly one place** (`ProfilesPage.tsx:62`); `motion-reduce:` 0 across 5
  keyframe animations and 37 transitions.
- **IA:** 21 flat nav items with zero grouping (`App.tsx:209-252`). The three actual Luna product
  surfaces — `/character`, `/behaviour`, `/people` — sit buried between admin pages. `/onboarding`
  ("Setup") is permanently nav item #2 even after setup is done. `/analytics` is flag-gated but
  URL-reachable. `/profiles/new` has no nav entry.
- **Two nav definitions** that must be kept in sync by hand: `App.tsx:209-252` labels +
  `lib/resolve-page-title.ts:3-28`. 9 of 21 nav labels are hardcoded English; 11 use `labelKey`.
- **Theming is two unrelated systems.** The dashboard theme (`web/src/themes/`, 3-layer
  background/midground/foreground + shadcn override escape hatch) and the agent skin
  (`apps/shared/src/skin.ts`, 44 terminal-first tokens) never meet — `web/src` imports neither
  `SKIN_COLOR_TOKENS` nor `LunaSkin`. `CharacterPage`'s skin editor edits the *agent's* palette, not
  the dashboard's. `help.ts:172` then tells the user the "product default is luna (the Sakura Night
  mauve palette)" while the dashboard renders Hermes Teal. So: **the CLI already wears the intended
  brand; the dashboard does not.**
- **No `color-scheme` axis.** `dark:` appears 5× (badge colors only). Light mode exists as one
  non-default theme (`nous-blue`).
- **Breakpoints:** `sm` 177 / `lg` 61 / `md` 9 / `xl` 5, plus a `max-width: 768px` block in
  `index.css:132` that fights the mobile-first utility strategy. Tablets fall into the phone layout.
- **i18n:** 17 locales, `i18n/types.ts` = 903 lines / ~503 keys, and 16 of 17 are exhaustive
  `Translations` objects — **adding an English key breaks the build until all 16 are updated.** Only
  `ar.ts` uses `defineLocale` and tolerates drift. Meanwhile `content/help.ts` (184 lines, 9 prose
  sections) is 100% hardcoded English, as are 79 `placeholder=`, 8 `<Label>` children, and every
  `<H2>` in `PeoplePage` / `CharacterPage` / `BehaviourPage`.
- **Data layer:** `lib/api.ts` is a 2,747-line object literal with ~548 untyped members and a
  module-level mutable `profile` variable. 192 `useState` / 84 `useEffect` in `pages/`, no cache, no
  dedupe, no abort-on-unmount, no react-query/SWR/loader.
- **Dead weight:** `motion`, `gsap`, `leva`, `@observablehq/plot`, `@react-three/fiber`, `three`,
  `class-variance-authority` are all declared in `web/package.json` with zero imports (plus dead
  `codeSplitting` groups in `vite.config.ts:118-153`). `AnalyticsPage`'s chart is 100 lines of
  hand-rolled `div` bars while `@observablehq/plot` sits unused. DS has `graphs/bar-chart`,
  `graphs/line-chart`, `grid`, `stats`, `separator`, `dropdown-menu`, `animated-count` — unused.
- **UI test coverage is near zero.** 51 test files but only 5 `.tsx`, none covering `App.tsx`
  (shell/nav/routing), `themes/context.tsx` (theme application), `i18n`, or 19 of 24 pages.
  `jsdom` / `@testing-library/*` are declared only in `apps/desktop/package.json`, not `web/package.json`.
- **Operational footgun (corrected by the implementation audit):** the built SPA at
  `hermes_cli/web_dist/` is **ignored and untracked**. `assemble.sh` excludes `web/` and copies the
  local build output if present, without building it. A clean checkout can ship no dashboard;
  a previously built checkout can ship stale UI. P6 must make packaging reproducible.
- **Chat tab has no TUI in the slim runtime:** `web_server_chat.py:321` builds argv from
  `PROJECT_ROOT / "ui-tui"`, which `assemble.sh:33` excludes and `hermes_cli/tui_dist/` does not exist.
  Out of scope for a polish pass, but it should be recorded rather than left as a surprise.

---

## 2. Non-color UX: what's actually broken

Colors were the visible half. This is the larger half — layout, interaction, feedback, and
information design. Audited across all 24 pages + 30 components (~30.7k lines).

### 2.1 Four things that are bugs, not polish

These go first, before any visual work, because two of them destroy user data.

**B1. The Behaviour page threshold sliders are wired wrong and will corrupt the wake cascade.**
`BehaviourPage.tsx:76-84` hardcodes `max={1}` on every `<input type="range">`, but the thresholds it
edits are minutes-since-last-spoke and message counts — real values like `45`, `10`, `1440`. Verified
against the backend: `config_schema.py:56-63` already knows the correct bounds
(`min_minutes_since_luna: (0, 1440)`, `min_new_messages: (1, 1000)`), and `api_models.thresholds()`
returns `value`/`default`/`type`/`overridden` but **not** `min`/`max` — so the frontend has no way to
know the range and guesses `1`. Consequences:
- Every slider renders pinned to the far right (`value=45` against `max=1` clamps).
- **Dragging one left writes `0`** — silently zeroing a cooldown in `config.yaml`. No confirm, no
  undo, no preview of the change, one toast.
- The paired number input (`:86-94`) has no `min`/`max` at all, so it accepts anything.
- `aria-label={name}` exposes the raw config key (`min_minutes_since_luna`) instead of
  `thresholdLabel(name)`, which is what the visible text shows — a label/content mismatch.
- Every slider write goes straight to the network on drag (`:75-95` → `writeThreshold`), so the
  slider fights the user mid-drag.

This touches **AGENTS.md §3 invariant 4** ("silence is the default… never loosen wake thresholds
without replay-harness evidence"). A user dragging a slider to zero is exactly that, unguarded.
Fix: emit `min`/`max`/`step` from `_RANGES` through the thresholds API, bound both inputs, and
debounce writes to commit rather than per-pixel.

**B2. Zero unsaved-changes protection, anywhere.** `grep 'beforeunload|isDirty|unsaved|hasChanges'`
over `web/src` returns **one hit and it is a comment** (`EnvPage.tsx:868`). At least 12 multi-field
forms lose work silently:
- `ConfigPage.tsx:543-548` — a free-text YAML textarea. Anything typed is one nav away from gone.
- `CharacterPage.tsx:324-357` — the persona. Hours of tuning, one click from lost.
- `BehaviourPage.tsx:112-316` — 11 fields and **4 separate Save buttons** (`:168, 201, 228, 309`)
  with no dirty tracking, so saving the route chain discards edits to the room-voice textarea 20
  lines above it.
- `CronPage.tsx:588,604` — the create/edit modal closes on Escape, discarding a composed job.
- `ProfileBuilderPage` — 5 wizard steps; browser-back discards all of them, and `ProfileKeyedRoutes`
  (`App.tsx:870-873`) remounts the whole tree on profile switch, discarding them again.

**B3. Irreversible actions with no confirmation.** `DeleteConfirmDialog` coverage is otherwise
genuinely good, which makes the gaps stand out:
- `CharacterPage.tsx:142-153` — applying a persona preset **silently overwrites the user's entire
  SOUL.md**. No confirm, no diff, no backup. This is the worst one: an hour of tuning, one click.
- `CharacterPage.tsx:244-256` — importing a SOUL file does the same.
- `PeoplePage.tsx:160-176` — identity merge is irreversible, unconfirmed.
- `CharacterPage.tsx:233-242` — `exportSoul` exports `bundle.soul.raw`, the **last-saved** version,
  from a page where the user may have unsaved edits in the textarea. Export silently discards work.
- `PairingPage.tsx:74` — `window.confirm(...)`, the only `window.confirm` in the codebase, on an
  action that clears *all* pending requests with no consequence statement, sitting next to a
  properly-done `DeleteConfirmDialog` for the single-user case.

**B4. `PluginsPage.tsx:324`** — `.catch(() => showToast(t.common.loading, "error"))` toasts the
literal string **"Loading"** as an error message.

### 2.2 Layout and composition

**23 of 24 pages have no content max-width.** Only `ProfileBuilderPage.tsx:284` has one
(`max-w-3xl`). `PageHeaderProvider.tsx:123-132` and `App.tsx:796` add none. At 2560px, Behaviour's
6-column verdict feed and 5-column wake ledger stretch full-bleed, and `CharacterPage.tsx:500`'s
`grid-cols-2` skills list becomes two 1200px checkbox columns. There is no shared page-layout
component at all — each page independently re-derives its own wrapper, and **7 different gap values**
are in use (`gap-3`, `gap-4`, `gap-6`, `gap-8`, `p-4`, …).

**The 5 Luna pages are the weakest structurally**, which is the opposite of what should happen:
- `BehaviourPage.tsx:112-316` — one 204-line component, 11 controls, 4 save buttons, 6 stacked cards.
- `CharacterPage.tsx:266-519` — 6 stacked cards, **three different save targets** plus instant-apply
  on preset/skin/skills, and no indication which card is dirty.
- `SystemPage.tsx:713-1649` — 936 lines of render, 11 top-level sections at `gap-8`, no tabs, no
  anchor nav.
- `OnboardingPage.tsx:216-407` — a 5-step wizard renders **every step's form simultaneously**, so it
  reads as one 400px wall instead of a wizard.
- `HelpPage.tsx` — 8 sections of genuinely good prose in one card, with a wrapping pill row, no TOC,
  no scroll-spy, no search, and a `#wakes` deep-link hack that never updates `location.hash`.

By contrast `SessionsPage` is the reference implementation and the model to copy: filter bar,
scoped bulk-select, pagination, empty state, a live action log for long operations.

### 2.3 Mobile is broken on six pages, and overflow is clipped not scrollable

`main` is `overflow-x-hidden` (`PageHeaderProvider.tsx:130`), so anything wider than the viewport is
**unreachable, not merely ugly**:

| Page | Why it breaks |
|---|---|
| `BehaviourPage` | `w-64` label + `w-52` range + `w-20` number = **384px of fixed width before the input** (`:65,83,92`); `grid-cols-3`/`:188` and `grid-cols-2`/`:210` with no `sm:` prefix; both tables unwrapped |
| `PeoplePage` | 8-column table with **no overflow wrapper** (`:234-265`); `grid-cols-2` with no prefix (`:276`) |
| `CharacterPage` | `w-64` inputs, `grid-cols-2` skills list, `w-48` mono labels (`:327,355,395,470,500`) |
| `OnboardingPage` | `max-w-2xl grid-cols-2` with no prefix (`:228,283`) — two 320px columns on a 375px screen |
| `FilesPage` | `min-w-[42rem]` hard floor on every row (`:368/379/402`); scrolls, but with zero affordance and no card fallback |
| `ProfileBuilderPage` | 5-step pill row with no wrap (`:293-313`) |

Plus the header stacks at `sm:` (640px) while the sidebar switches at `lg:` (1024px), so 640–1024px
gets a two-row header *and* a permanent sidebar, with `end` capped at `sm:max-w-md`.

The shell itself is well built — sidebar drawer, mobile header, single scroll container all correct.
The problem is entirely page-level.

### 2.4 Feedback: 270 toast call sites doing the work of error UI

`showToast(` appears **272 times**. Toasts are the *only* error surface on 8 pages, and on **8 pages
load failures are surfaced as auto-dismissing toasts** — `McpPage:102,112`, `ChannelsPage:170`,
`WebhooksPage:98`, `PairingPage:47`, `PeoplePage:112`, `OnboardingPage:66`, `CharacterPage:92`,
`BehaviourPage:406`. A user who arrives late sees a blank page with no error and no retry.
`LoadErrorNotice.tsx` exists precisely to fix this, documents why it's right in its own comment, and
is used by **2 of 24 pages**.

Long operations get no progress indication, which means the user cannot tell whether the product is
working:

| Operation | Current feedback |
|---|---|
| What-if replay (25×10) | Button text flips to "Replaying…" for the whole run; result arrives as **one toast and is never rendered** (`BehaviourPage:473-483,521-524`) |
| Honcho stack up | `honchoUp(180)` is **3 minutes** with no stage output (`OnboardingPage:151-162`) |
| Apply Telegram / WhatsApp | "gateway restarting…" in a vanishing toast (`ChannelsPage:1242`) |
| Gateway restart (System) | Toast only (`SystemPage:322`) |
| Backup / import / update | Toast only (`SystemPage:463-524`) |

Contrast `SessionsPage.tsx:1766-1828`, which streams a live action log. That pattern should be the
shared one.

### 2.5 Forms: 17 surfaces, 3 with validation

Only `ProfileBuilderPage:329-334`, `ProfilesPage:854-862`, and `ChannelsPage:492-508` do inline
field-level validation. The other 14 validate post-submit via toast. Required fields are marked on
3 pages (`ChannelsPage:464`, `McpPage:552`, `PluginsPage:683`) — and `PeoplePage`'s genuinely
required `user_id` is marked on none.

**`AutoField.tsx` is the worst case**: it renders *every* `config.yaml` field on the Config page and
has **no error prop at all** and **no `htmlFor`/`id` on any `<Label>`** (7 `<Label>` sites, zero
`htmlFor`). So every Config control is programmatically unlabeled, and a bad value surfaces as a
page-level toast with no field anchoring. It also has no required/help affordance.

Secret handling is inconsistent: `EnvPage:750-765` has proper masked + per-key reveal;
`ChannelsPage:484` masks with no reveal; **`McpPage`'s add-server form renders env vars as plain text
inputs**, so a pasted bearer token is visible on screen. And the **env-var-name vs env-var-value**
distinction is never surfaced anywhere — typing a secret into `api_key_env` writes it into
`config.yaml` in plaintext.

### 2.6 Data density: 5 tables, none sortable, searchable, or bulk-selectable

Only `PeoplePage:234` and `BehaviourPage:339,576` plus `AnalyticsPage:254,313,368` render real
`<table>`s. **Zero tables are sortable** (no `<th onClick>` anywhere), none are searchable, only
`SessionsPage` paginates, and only `SessionsPage` has bulk select. Two of Behaviour's tables have no
overflow wrapper at all. Column widths for the same logical field differ three ways
(`BehaviourPage:364,365,595`).

Meanwhile five other pages fake tables with card stacks (`CronPage`, `McpPage`, `PairingPage`,
`WebhooksPage`, `ChannelsPage`) — consistent with each other, inconsistent with the real tables.

### 2.7 Interaction patterns: four different apply models, no convention

| Model | Where |
|---|---|
| Instant-apply on change | 9 sites — every Behaviour slider, `CharacterPage:284,446,506` (preset dropdown, skin button, skill checkbox), Channels/Webhooks/Mcp/Plugins switches |
| Per-row Save | `ConfigPage:517`, `CronPage:1064`, `ModelsPage`, `ChannelsPage:524`, `McpPage` |
| Single global Save | `ConfigPage:520`, `CharacterPage:320/432/486` |
| Per-field Save | `EnvPage:685` |

Drag-to-reorder exists **nowhere**, which specifically breaks `BehaviourPage:249-292`: the jev
provider route chain is a "route chain" whose order can only be changed by retyping a comma-separated
string. Drag *files* into FilesPage is well done and is the model to reuse.

### 2.8 Accessibility beyond color

- **No focus trap in any of the 9 modals.** `useModalBehavior.ts:9` returns a ref "for optional
  future focus trapping" and never uses it for trapping. Tab escapes every dialog in the app while
  they all claim `aria-modal="true"`.
- **Selected state is color/badge-only with no ARIA** on `CharacterPage:443-452` (skin buttons, no
  `aria-pressed`) and `HelpPage:37-45` (section pills, no `aria-pressed`/`aria-current`/`role="tab"`)
  — so a screen-reader user **cannot tell which of the 8 Help sections they're reading**.
  `ProfileBuilderPage:560-631` (`role="group"` + `aria-pressed`) is the correct pattern; make it the
  template.
- **`h1` → `h3` skip** on `PluginsPage:896,949,987` (no `h2` on the page). Five Luna pages render a
  masthead `H2` duplicating the header `h1` — the page name appears twice, both as headings.
- **`aria-live` appears 4 times in the entire app.** `BehaviourPage` polls every 8s, `LogsPage` every
  5s, `SessionsPage` polls the overview — all completely silent to a screen reader.
- `role="toolbar"` on 1 of 24 pages. `role="alert"` on 1.
- `AutoField`'s unlabeled inputs (§2.5). `<Label>` with no `htmlFor` is the pattern in 8 places.
- `ChatPage.tsx:1573` calls `term.focus()` **unconditionally on mount**, so navigating to `/chat`
  steals focus from wherever the user was (the restore-on-refocus paths at `:1698,1717` are correctly
  guarded; the mount path is not).

### 2.9 Copy: good bones, leaked jargon

The Luna pages are **materially better written** than the engine pages — lowercase labels, real
explanations, genuine voice (`"The persona asks; these clamp."`, `"Silence is the default, since most
messages are not worth waking for"`). Three systemic problems:

**Jargon leaks.** `"Run live (spends one jev call)"` — `jev` is never defined anywhere in the UI.
`"weighted fit/msgfit/openq/addressed/emojiconf/wait"` — six invented abbreviations in a table cell
with no explanation of what any means or which direction is good. `"unknown key"` surfaced raw when a
config key isn't recognised — that's a bug report, not copy. `"Action=… value=… route=… reason=…"`
(`OnboardingPage:390`) dumps a raw decision dict at a first-time user. And
`"mention fallback regexes (one per line; empty = stay silent when jev is down)"`
(`BehaviourPage:212`) asks a non-technical user to author **regexes** on an onboarding surface.

**Missing "why."** The thresholds card says only *"Changes take effect on the next poll. Overrides
edit config.yaml in place."* It never says what lowering a threshold does, or why the shipped default
was chosen.

**Three competing label styles** in the same app: lowercase-no-punctuation (`"provider"`, `"bot
token"`, `"emoji filter"`), sentence case (`"Save provider"`, `"Apply persona"`), and CSS uppercase.
Plus `SessionsPage.tsx:1980-2071` wraps button text in
`<span className="font-mondwest normal-case text-xs">` to *undo* uppercase inherited from the button
— a hack scar that won't survive a theme change.

**Strings that tell the user to do what the dashboard could do for them:**
`OnboardingPage:285-287` re-explains the BotFather flow as a prose blob when `ChannelsPage:413-455`
already has a guided numbered list with deep links; `:329-331` puts a shell command in the UI;
`AnalyticsPage:515-519` tells the user to hand-edit `dashboard.show_token_analytics` in Config to
reveal a page; `:142` says "restart the gateway to connect" when the dashboard has a restart button
in the sidebar.

### 2.10 Reusable patterns with no shared component

24 page wrappers with 7 gap values · ~95 `Card`+`CardContent` · 20 loading blocks in **4 different
treatments** (`py-24` spinner 9×, `p-6` inline 4×, …) · 21 toast hosts mounted mid-tree instead of one
`<Toaster/>` · 10 page mastheads · 5 wasted Refresh buttons in the page header · 8 uses of a local
`inputClass` string that bypasses the DS `Input` · ~40 `<Field>` implementations across 4 files ·
~12 key-value rows (1 extracted) · 3 stat-row implementations · ~9 card-row lists · 5
copy-pasted `<SearchInput>`s (~12 lines each) · 11 hand-rolled modal shells (vs 4 files using the DS
`Dialog`).

### 2.11 Chat page specifically

Good bones, four specific defects:

- **No content max-width** and the side rail wastes ~40px permanently on a dedicated collapse row
  (`ChatPage.tsx:2070-2081`) — at `lg:w-60` the session list, the reason the rail exists, gets
  what's left.
- **Mobile and desktop are two different apps** — below 1024px a portaled slide-over sheet opened by
  a header button; above it a persistent rail. Neither shares layout logic; both render
  `ChatSidebar`, and the scrim is a `<Button>` (`:1817-1826`), putting a focusable full-screen
  control in the tab order.
- **`chatPanelCollapsed` and `narrow` are two independent collapse mechanisms** (`:355-369,384-388`)
  that can both be active, leaving the panel unreachable until the user taps two different controls.
- **`showReconnectOverlay` has a dead branch** (`:1803-1804`): `banner` is set by every failure path,
  so `closed && !banner` is nearly unreachable — meaning on a hard close the user gets a **dead
  terminal** instead of the "Reconnect now" button.
- `terminalFontSizeForWidth` returns **7** below 300px (`:181`), with no user font-size control at
  all despite the theme controlling terminal colors. And `isViewportPinnedToBottom` is computed and
  tested but never used to render a "jump to latest" affordance.

---

## 3. Design direction

### 3.1 The reference

The brief image is a **dusk sakura** frame: a deep indigo-plum night, blossom petals in blush and
rose, hair in pale lilac catching warm gold glints, cream-white highlights, and a band of sage green
foliage at the bottom edge. It is soft, low-contrast, warm-cool split, and it is *already* what the
CLI skin means by "Sakura Night" (`luna/config/skins/luna.yaml`: `#F2C6DD` titles, `#DF8DA5` accents,
`#84415D` dims, `#FBF0F8` text on a `#191D25` bar). The dashboard just never got the message.

### 3.2 Palette — "Sakura Dusk"

Six named values, one accent. Derived from the image and reconciled with the existing skin so the CLI
and the dashboard finally agree.

| Token | Hex | Role |
|---|---|---|
| `--luna-night` | `#1E1830` | page canvas — the indigo of the sky, not black |
| `--luna-plum` | `#2C2342` | raised surfaces: sidebar, cards, header |
| `--luna-haze` | `#453660` | hairline borders, dividers, inactive strokes |
| `--luna-sakura` | `#F2C6DD` | **the** accent: active nav, links, focus ring, primary button |
| `--luna-cream` | `#FBF0F8` | primary text (matches the skin's `banner_text`) |
| `--luna-gold` | `#E6A855` | secondary accent: attention, "overridden", warnings |

Semantic, mapped off the same wheel so nothing reads as a foreign brand: `ok` `#7BD88F` (skin),
`warn` `#E6A855`, `error` `#FF6B8B` (skin) — a rose, not a fire-engine red. Petal accent for data
series: `#DF8DA5` input / `#7BD88F` output.

Contrast rules (enforce with the existing `contrastRatio` helper from `@hermes/shared`):
`cream` on `night` ≈ 14:1; `sakura` on `night` ≈ 8:1; `haze` on `night` ≈ 3.4:1 — borders only, never
text. Nothing below 4.5:1 for body copy, 3:1 for large text and non-text UI.

This is deliberately *not* the AI-default "cream page + terracotta accent + high-contrast serif"
cluster, and not the "near-black + one acid accent" cluster: the canvas stays dark, but it is a
plum, not a tinted black, and the accent is a desaturated blossom rather than a saturated signal
colour. Warm-cool split (gold vs indigo) does the work that a single accent normally can't.

### 3.3 Type

Two families, chosen against the brief rather than defaulting:

- **UI: Inter** (already in `FONT_CHOICES`, already the `midnight` theme's sans). It has the tabular
  figures and unambiguous `l`/`I`/`1` that a dense ops dashboard needs, and it stays quiet.
- **Character voice: Fraunces** for the companion's own words — the greeting, the help prose, the
  character preview, the "Luna is around" line. Optical-size axis means it reads soft at display
  sizes. This is where the reference image's personality goes: **the product's human surfaces are
  typeset differently from its operator surfaces.** That contrast is the one memorable thing; it must
  be spent in exactly this one place.

Kill `font-mondwest` (65 uses) and `font-expanded` as UI faces — they are upstream Hermes display
faces and they're what makes the current dashboard read as "generated console". Keep `font-mono` for
code/paths/values only. Retire the vendored `Collapse`/`Rules*`/`Mondwest` woff2 from the login page
too (`login_page.py:34,41,48,55,327`) — that page is the front door and it is currently typeset in
the old brand's typeface.

Type scale, six steps, replacing 101 `uppercase` + 50 arbitrary `tracking-[…]`:
`display` 28/34 · `title` 18/24 · `heading` 15/20 · `body` 14/21 · `meta` 12.5/18 · `micro` 11/15
(micro is the only step allowed `uppercase` + `0.08em` tracking, and only for real category labels).
Body measure capped at 72ch. Line length rule applies to the new help/character pages especially,
since those are prose.

### 3.4 Structure

The current shell is sound in bones — sticky sidebar, page header, single scroll container, plugin
slots, collapsed rail. What it lacks is **hierarchy**: 21 equally-weighted rows. The restructure is
grouping, not a new layout.

```
┌────────────┬──────────────────────────────────────────┐
│ ☾ Luna     │  Character                    [actions] │  ← header: one h1, one toolbar,
│            ├──────────────────────────────────────────┤    no competing type sizes
│ [profile ▾]│  ┌──────────────┐  ┌──────────────┐     │
│            │  │ card         │  │ card         │     │  ← 12-col grid, cards carry
│ COMPANION  │  └──────────────┘  └──────────────┘     │    exactly one job each
│  Chat      │  ┌───────────────────────────────┐      │
│  Sessions  │  │                               │      │
│  People    │  │                               │      │
│ CHARACTER  │  └───────────────────────────────┘      │
│  Character │                                           │
│  Behaviour │                                           │
│  Wake…     │                                           │
│ ────────── │                                           │
│ SYSTEM     │                                           │
│ …          │  ← gateway dot · status strip            │
└────────────┴──────────────────────────────────────────┘
```

Sections: **Companion** (Chat, Sessions, People) → **Character** (Character, Behaviour, Files) →
**Reach** (Channels, Pairing, Webhooks) → **Automate** (Cron, Skills, MCP, Plugins) →
**Operate** (Models, Keys, Logs, Analytics, Profiles) → **System** (Config, System, Docs, Help).
Collapsible, state persisted, plugin tabs keep their own group. Alignment stays left; nothing centers
except empty states and the login card.

Restraint budget: **one** ornament, and it is the sidebar wordmark treatment (a blossom-tinted ☾
with a soft sakura glow on the active nav item only). No gradients on cards, no glow on hover, no
entrance animations on page content. Motion only where it answers an action.

### 3.5 What gets deleted

`content/help.ts` gets restructured into the i18n system and re-voiced as Fraunces prose, not
converted to a feature-bullet dump. The all-caps tracked eyebrow above every heading goes. The
`·`-joined meta strings go. The `→` on link text goes. `Luna Teal` as a theme name goes (replaced by
Sakura Dusk, with a `THEME_NAME_ALIASES` entry so saved prefs survive). The 7 unused dependencies go.

---

## 4. Phases

Each phase is independently shippable and leaves the suite green. Estimated sizes assume one
focused session each.

### P-1 — Fix the four bugs (½ day, ships first, nothing else matters until these are done)

These are correctness and data-loss defects, not polish. **B1 and B2 in §2.1 are the reason this
phase goes first** — B1 corrupts the wake cascade, B2 loses user work, B3 destroys a persona.

1. ~~**B1 — threshold sliders.**~~ **✅ shipped.** `config_schema.py` gained `threshold_bounds()` and
   a `_WHOLE_NUMBER_STEPS` entry so `min_minutes_since_luna` steps by 1 rather than 0.01;
   `api_models.thresholds()` now emits `min`/`max`/`step`/`description` per key, sourced from the
   same `_RANGES` table the config form reads, and omits bounds entirely rather than guessing when
   the overlay lib is absent. Client side: `canSlider`/`clampThreshold` in `luna-thresholds.ts`,
   `ThresholdRow` rebuilt with local draft state so a drag writes **once on release** instead of
   per pixel, both inputs bounded, `thresholdLabel` used for `aria-label` and `aria-valuetext`, and
   the cascade description surfaced in place of a bare `default N`. Tests:
   `web/src/pages/BehaviourPage.test.tsx` (9) pins bounds/no-slider-without-bounds/drag-writes-nothing/
   NaN-safety; `luna-thresholds.test.ts` (+8); `test_api_models.py` (+5) pins every key carries a
   real range containing its default.
2. ~~**B2 — unsaved changes.**~~ **✅ shipped.** Four pieces, framework-free where possible:
   `lib/dirty-registry.ts` (`UnsavedRegistry` + `PendingNavigationStore`, both with referentially
   stable snapshots for `useSyncExternalStore`); `lib/guarded-history.ts`; `hooks/useUnsavedChanges.ts`
   (`useUnsavedChanges`, `useUnsavedChangesGuard`, `isDraftDirty`); `components/DirtyBar.tsx` +
   `contexts/UnsavedChanges.tsx`. `beforeunload` is installed **only while dirty**, derived from the
   registry snapshot rather than mounted unconditionally.

   **P1's DirtyBar primitive was pulled forward, not waited for.** P1 §5 lists `DirtyBar` among the
   shared primitives, but that list is dependency-ordered behind `Skeleton`/`EmptyState`/`Modal`/
   `Table`/`Field` — 2–3 days of work — and B2 is the phase that destroys user work. So `DirtyBar`
   shipped standalone as `components/DirtyBar.tsx`, self-contained (no `Page`, no `Field`, no token
   work) and using today's vocabulary rather than the P1 vocabulary P1 will introduce. **P1 should
   adopt this component as-is and restyle it in place**, rather than writing a second one — it is
   already the shape P1 asks for (`labels` / `pending` / `onSave` / `onDiscard` / `onStay`).

   **The guard is on the history object, not `useBlocker`.** `useBlocker` needs a data router and the
   shell is declarative `<BrowserRouter>`, so `main.tsx` swaps it for `HistoryRouter` over a guarded
   history. Every `navigate()` / `<Link>` / `<NavLink>` / browser-back runs through `push`, `replace`,
   `go` or `popstate`, so wrapping those covers in-app navigation without touching routing. `POP` is
   handled by walking the history back with a counter-`go` and never forwarding the update to the
   router, so React keeps rendering the page the user is on; a held resume replays the original `go`.
   Two classes of navigation never reach `history.push` and use `useUnsavedChangesGuard().requestLeave`
   instead: **a profile switch** (`ProfileKeyedRoutes` remounts the tree) and **a modal close**. Cost
   of this choice, recorded so it is not a surprise: two `unstable_`/`UNSAFE_`-prefixed react-router
   imports in `main.tsx`. The alternative was migrating the shell to a data router, which is a
   redesign rather than a guard.

   Applied to all five, plus the profile switcher: `ConfigPage` YAML (baseline = text last read from
   or written to disk, so a save clears the bar without a reload, and switching to the form view
   releases the guard); `CharacterPage` persona; `BehaviourPage` `WakePolicyCard` (**4 Save buttons
   collapsed to 1** — each used to write only its own slice, so "Save budget" silently dropped the
   room-voice textarea above it); `CronPage` create **and** edit modals (Escape, backdrop and X all
   previously discarded a composed job); `ProfileBuilderPage` wizard (no `onSave` — nothing is
   persisted until Create and Create needs a valid name, so Discard is the only honest action).

   Tests: `useUnsavedChanges.test.tsx` (22) is the gate — end-to-end hook → registry → guarded history
   → DirtyBar → decision, including *a failed save must not navigate* and *beforeunload prompts only
   while dirty*; `guarded-history.test.ts` (13) drives a fake history, since jsdom's `history.back()`
   is async and would make the POP assertions flaky; `dirty-registry.test.ts` (17) covers replace-by-id
   and the stale-unregister trap. Per-surface baselines get their own files — `ConfigPage.test.tsx` (7),
   `CharacterPage.test.tsx` (12), `CronPage.test.tsx` (10), `ProfileBuilderPage.test.tsx` (13) —
   because the baselines differ (a stored cron job is its own baseline; the wizard's is
   `EMPTY_DRAFT`), and `BehaviourPage.test.tsx` (+7) pins the collapsed save.

   **Post-review fix (commit `3095047`).** An independent review found the mechanism sound but the
   contract violated at every call site: `saveAll` treated "did not throw" as success, and every
   handler catches its own error to show a toast — so **"Save and leave" navigated even when the write
   failed**, killing 40 lines of typed YAML behind an error toast. The test for this proved the
   registry contract using a *throwing* fake, so it passed while every real caller violated it. Fixed
   by making `false` a first-class save result and having all five handlers report it. Also fixed and
   pinned: the wake-policy save was not awaited; `DirtyBar` offered Save on the save-less wizard; the
   collapsed save silently deleted `endpoint`/`instructions`/`tier` from `jev.providers` (**a
   regression this change introduced** — the backend replaces that map wholesale and the form renders
   three of six keys); partial writes reported success; `restoring` behaved as a time window, so two
   fast back-presses escaped the guard; a delta-0 POP became `go(0)`, i.e. a reload; the wizard
   blocked its own post-Create navigation; and a locale change refetched over the typed YAML.

   **Read this before adding a surface.** A save handler must return `false` when it did not write.
   A handler that catches its own error and returns `void` will be read as success, and the guard will
   navigate away having persisted nothing.
3. ~~**B3 — confirmations.**~~ **✅ shipped** (commit `da14276`). Persona preset apply and SOUL.md
   import now confirm with what will be replaced (file, both line counts, "cannot be undone"); applying
   the persona you already have is skipped rather than confirmed, since a dialog that fires on a no-op
   is one people learn to dismiss without reading. Identity merge states that the two ids become one
   and the alt row is *deleted*, with no un-merge in the dashboard. `PairingPage`'s `window.confirm`
   replaced with the shared dialog, stating how many pending requests are dropped.

   **`exportSoul` was the real find.** It wrote `bundle.soul.raw` — the last *saved* text — from a
   page whose textareas hold unsaved edits, so exporting mid-edit silently discarded that work and
   handed back the previous file: the worst possible outcome for the one action meant to be a backup.
   It now renders the draft. That needed a client-side port of `render_soul` from
   `luna/lib/luna_cli/character.py`, so `lib/soul-render.ts` carries golden tests generated from the
   Python's own output. If the two drift, an exported persona re-imports as a *different* persona,
   which is worse than the bug it replaces — hence the golden file, not hand-written expectations.
4. ~~**B4**~~ **✅ shipped.** `PluginsPage`'s hub-load failure showed "Loading…" as an *error*, naming
   neither what broke nor where, leaving the memory selector silently empty behind an error toast that
   read like a status message. Now names the failure and includes `errorMessage(e)`.
5. ~~**B5 — the rest of the compose modals.**~~ **✅ shipped** (commit `e77a977`). Every other dialog
   built on `useModalBehavior` had the same Escape-discards-draft hole: `WebhooksPage`, `McpPage` ×2
   (add server + catalog install), `ProfilesPage` ×2 (create + the SOUL/description editor),
   `ChannelsPage` (credentials), and `ModelsPage`'s MoA dialog. Each close path — Escape, backdrop,
   X — now routes through the prompt, and each handler reports success per the contract above.

   `ChannelsPage` was the sharpest: it collects bot tokens and API keys, so a lost draft means
   fetching and pasting the secret again with no undo. `McpPage`'s catalog install collects required
   env values for the same reason. And `ProfilesPage`'s editor needed a *loaded-content* baseline —
   against the empty string, every opened editor would have read as edited and armed the prompt on
   arrival.

   **Checked and deliberately left alone:** `ModelsPage`'s `AuxiliaryTasksModal`. Each task assignment
   writes through immediately, so Escape has nothing to discard. Worth stating because the instinct is
   to guard every modal for uniformity — a prompt with no work behind it trains people to dismiss
   prompts without reading, which then costs them the confirmation that mattered. Same reasoning left
   B2's `beforeunload` conditional on dirty.

   Covered by `ComposeModals.test.tsx`, which renders the real pages and asserts the one thing that
   matters: a populated draft keeps the modal open on Escape, an untouched one does not. Wrap persona preset apply and SOUL import in a `ConfirmDialog` that shows
   **what will be replaced** (line count, and a diff of the current vs incoming SOUL if cheap).
   Confirm identity merge with a consequence statement ("these two identities become one; this can't
   be undone"). Fix `exportSoul` to export the textarea's current value, not the last-saved one.
   Replace `PairingPage.tsx:74`'s `window.confirm` with the shared dialog.

   **Read B2's guard first — B3 overlaps it and the two interact.** B3 is "confirm the destructive
   click"; B2 is "don't lose the work". Applying the preset overwrites `SOUL.md` *server-side*, so the
   DirtyBar is in the wrong place to catch it: the persona draft it is guarding is about to be
   replaced by the response, and the user is not navigating away. B3 needs its own dialog regardless.
   The one genuine interaction to get right: **`exportSoul` must export the textarea's live value**
   (B3's fix). After that, exporting on a dirty persona no longer silently discards the draft, and
   B2's Discard has a coherent meaning for it. Do not add a "you have unsaved changes" precondition
   to export — exporting is not destructive, and B2 already protects the navigation case.
   While in there, prefer B3's dialog over the local `ConfirmDialog.tsx`; §2.1 notes the local one is
   one of three competing dialogs for the same job, and adding a fourth use of it deepens that.

Gate: a test that no threshold write can produce a value outside its schema range, and a test that
dirty forms block navigation. **Both halves have now shipped** — the first with B1, the second with
B2 (`useUnsavedChanges.test.tsx`, "dirty forms block navigation").

> **Environment note:** `psutil==7.2.2` is a declared dependency in `pyproject.toml:122` that was not
> installed in `.venv`, which made 4 tests in `test_luna_api_hardening.py` error on collection
> (`hermes_cli/local_runtime/processes.py:11`). Pre-existing, not caused by this work; installing it
> took the Luna suite from 470 passed/4 errors to **474 passed, 0 errors**.

### P0 — Stop lying about the brand (½ day, no UI risk)

Smallest phase, highest visible return, zero design decisions.

1. `locales/*.yaml` (17 files) → Luna voice. `/help` and `/status` headers, `/update` copy,
   `hermes config set`/`hermes debug share`/`hermes kanban` command examples, `~/.hermes/logs/`
   path. Keep every key; change values only.
2. `_parser.py:77-125` epilog → `luna …`; `:152` subparser help.
3. `completion.py` → emit `luna`/`_luna_completion`/`complete -c luna`, and read `LUNA_HOME` →
   `HERMES_HOME` → `~/.luna` for the profile dir. Add a test asserting the emitted script binds
   `luna`.
4. ~~**Serve theme ids only; `presets.ts` is the single label authority.**~~ **✅ shipped**
   (commit `05ca86d`). `_BUILTIN_DASHBOARD_THEMES` (label + description per theme) is now
   `_BUILTIN_THEME_IDS` — ids only. `/api/dashboard/themes` sends a bare `name` for each built-in;
   the client's new `theme-list.ts::buildThemeList()` reads labels off `BUILTIN_THEMES` and **ignores
   any label the server sends for a name it owns**, so a re-vendor cannot reintroduce the split.

   The id sets are pinned equal from both sides through `web/src/themes/builtin-theme-ids.json` rather
   than by having one language read the other's source — `web/AGENTS.md` forbids Python tests
   asserting on `.tsx`, and `presets.ts` is where the labels now live. `presets.test.ts` asserts
   `BUILTIN_THEMES` equals the manifest; `luna/tests/contract/test_dashboard_theme_ids.py` asserts
   `_BUILTIN_THEME_IDS` does.

   Two `ast`-level guards fail if a module-level `{name, label}` table ever returns, because the
   behavioural tests would happily pass on a re-added *matching* label and only drift on the next
   rename. Scoped to module level on purpose: inside a function, `name` + `label` is legitimate and
   necessary (`_normalise_theme_definition` builds exactly that for a *user* theme). All three guards
   were verified to fail against the reintroduced bug.

   *Audit follow-up:* startup and launch guidance now use Luna; backend copy helpers are in the
   expanded brand gate.
5. ~~**One `lunaHome()` / `lunaBin()`, backend-sourced; no path literals in JSX.**~~ **✅ shipped**
   (commit `e8e689c`). `web/src/lib/luna-paths.ts` is the only place allowed to name a Luna path.
   The server injects `window.__LUNA_BRAND__` into `index.html` at serve time, using **the same
   resolver the `luna` CLI uses for its own home** (`luna_cli.main.luna_home`), so the dashboard and
   the terminal cannot disagree. `</` is escaped — `LUNA_HOME` is operator-supplied.

   Injected rather than fetched because these strings render on first paint; a fetch would show a
   fallback and then correct it, which is the wrong-first-paint problem `_render_active_theme_bootstrap_css`
   already exists to solve.

   **The update-confirm copy was a second, subtler lie** and worth calling out: it read
   *"This will run 'hermes update' (`<cmd>`)"* where `<cmd>` is the deployment's real update path
   (`docker pull …`, `pkg upgrade …`). On any install where those differ it contradicted itself, and
   it named the engine rather than the product. `SystemPage` and `App.tsx` now name only the command
   that will actually run.

   The guard is a contract test, scoped deliberately: a `.tsx` may still say `hermes` in a comment
   explaining the history, in `X-Hermes-Session-Token` (a wire contract), in a localStorage key, or
   in an internal DOM id. Test fixtures are **excluded** — several accurately echo backend strings that
   still say `hermes` (`gateway_start_command`, `cli_command`), and fixing a fixture before the router
   producing the value would make the test lie. Those belong to item 6.

   *Audit follow-up:* backend-sourced gateway/OAuth command guidance now uses Luna; execution and
   wire identifiers remain compatible.
6. `chat_ws.py:157` `_CONSOLE_PROMPT` → `luna> `; the 19 router strings; the 24 platform descriptions.
7. `DocsPage.tsx:8` + `PluginsPage.tsx:923` → repoint at in-dashboard `/help`; if an external link is
   wanted, make it a configurable `luna.docs.url` with an empty default.
8. Telegram quick-setup service (`web_server_messaging.py:376-395`, `telegram_managed_bot.py`) —
   **decision locked, see §0.** At minimum: relabel the UA, and stop calling a third-party-hosted
   endpoint a "recommended" Luna path without saying who operates it.
9. `en.ts:59` `brandShort` → `"L"`; `SidebarFooter.tsx` → drop the Nous Research link or make it
   configurable attribution.
10. **Truth pass on the docs.** Rewrite `PRODUCT_PLAN.md:198-208` and `engine-vendor.md:113,119,124-125`
    to describe what is actually rebranded and what is deliberately not. A false checklist is how
    this class of gap survives a re-vendor.
11. Exclude the upstream prose from the runtime: add `README.*`, `CONTRIBUTING*`, `SECURITY*`,
    `Dockerfile`, `docker-compose*`, `cli-config.yaml.example`, `PRODUCT_PLAN.md` to
    `assemble.sh`'s exclude list, or replace them.
12. `pyproject.toml:413-415` — decide: either drop the `hermes*` console scripts from the Luna
    install or document that they exist for engine-internal use. Right now a Luna install silently
    gains a second CLI.

Gate: `grep -rn "Hermes" web/src locales/*.yaml hermes_cli/web_routers/*.py` returns only
contract/comment hits, each with a reason.

### P1 — Foundations: tokens, type, state, layout, a11y (2–3 days, unblocks everything after)

1. **One token vocabulary.** Pick DS-native (`text-text-primary/secondary/tertiary`,
   `border-current/20`, `bg-background-base`) or shadcn (`text-muted-foreground`, `border-border`,
   `bg-card`). Recommendation: **DS-native**, because the shadcn shim in `index.css:154-187` is the
   thing that has to be maintained forever, and the DS tokens are what the components actually read.
   Then: `rg` the other vocabulary, migrate mechanically, delete the shim block, add a lint rule
   (eslint `no-restricted-syntax` on the banned class names) so it can't creep back.
2. **Semantic status colours on the theme.** Today every theme gets `#fb2c36` / `#4ade80` / `#ffbd38`
   hardcoded (`index.css:172-174`) — a red that fights the blossom palette. Promote `success` /
   `warning` / `destructive` to first-class palette slots with per-theme values, keep the hardcoded
   hex as the fallback. Kill the 37 off-token `amber-500` / `red-500` / `blue-600` utilities in 10
   files, including the whole-banner colors in `ProfileScopeBanner.tsx:17`.
3. **Six-step type scale** as CSS vars + a `<Type>` primitive (`display|title|heading|body|meta|micro`).
   Migrate the 50 `tracking-[…]` and 22 `text-[0.xxrem]`. Reserve `uppercase` for `micro` — which
   also retires the `font-mondwest normal-case` hack at `SessionsPage:1980-2071`.
4. **One page layout.** A `<Page>` component carrying the content max-width (§2.2), the standard gap,
   and the scroll container. Replace all 24 wrappers and the 7 gap values. **Set `main` to
   `overflow-x-auto`, not `hidden`** (`PageHeaderProvider.tsx:130`) so overflow is reachable rather
   than clipped — that one line is what turns six broken pages into merely ugly ones.
5. **Missing primitives**, in dependency order:
   - `Skeleton` (0 today, 6 `animate-pulse`), `EmptyState` (18 hand-copies), `ErrorState`
     (fold `LoadErrorNotice` into it and retire the 60 inline boxes), `PageLoading` (20 blocks in
     **4 different treatments** today), and a `StateBoundary` (`idle|loading|ready|empty|error`) so
     pages stop hand-rolling the branch.
   - `Modal` — one implementation. Port `DASHBOARD_MODAL_BACKDROP` into it, delete the 11 hand-rolled
     shells + 13 literals, pick one z-scale, and **add the focus trap** to `useModalBehavior` so
     `aria-modal="true"` becomes true at all 9 call sites. Retire local `ConfirmDialog.tsx`.
   - `Table` — sortable, searchable, optionally bulk-selectable, with a real mobile story (card
     fallback below `md`, not a `min-w-[42rem]` scroll). Replaces the 5 real tables and gives the
     5 card-stack "tables" one consistent form.
   - `Field` — `<Field label hint error required>` replacing ~40 hand-rolled label+input pairs across
     4 files and the local `inputClass` strings. **This is where `AutoField`'s missing
     `htmlFor`/`id`/error prop gets fixed** (§2.5).
   - `SearchInput`, `FilterRail`, `StatRow`, `ResourceRow`, `DirtyBar`, `Toaster` (one, in `App.tsx`,
     not 21 mounted mid-tree).
   - `DataBar` — replace the 100-line hand-rolled chart; use DS `graphs/bar-chart` and drop the
     unused `@observablehq/plot` dep.
6. **Durable error + progress, replacing toast-as-error (§2.4).** Apply `LoadErrorNotice` to the 8
   pages that currently toast a load failure, so a late-arriving user gets an error and a retry. Then
   extract `SessionsPage:1766-1828`'s live action log into a shared `<ActionLog>` and use it for
   replay, gateway restart, Telegram/WhatsApp apply, backup, and update. **Render the replay result**
   instead of toasting it. Add stage output to the 3-minute `honchoUp`.
7. **Breakpoints.** Declare an explicit scale, delete the `max-width: 768px` block in `index.css:132`,
   reconcile `useBelowBreakpoint(1024)`, and add the `md` tier that 9 usages imply but nothing defines.
   Move the page header's stack/inline switch from `sm:` to `lg:` to match the sidebar, and generalize
   `/env`'s bespoke `end`-slot treatment (§2.3) so toolbars wrap instead of overflowing at 640–768px.
8. **Accessibility floor.** Global `prefers-reduced-motion` block in `index.css` (1 place today),
   `motion-reduce:` on the 5 keyframes, roving tabindex + skip link, route error boundary + real 404,
   `aria-live` regions for async results **and for the background polls** (Behaviour 8s, Logs 5s,
   Sessions overview — currently silent to screen readers), `role="toolbar"` on filter bars,
   `aria-pressed`/`aria-current` on every custom selected-state control
   (`CharacterPage:443-452`, `HelpPage:37-45`, Env jump-nav), fix the `PluginsPage:896,949,987`
   `h1`→`h3` skip, and delete the 5 duplicate masthead `H2`s.
9. **Keyboard + wayfinding.** Escape and Enter are the only shortcuts today. Add a command palette
   (the nav manifest in P3 feeds it) with `/` to focus, `?` for help, and `g`-prefixed jumps; add
   breadcrumbs; make `/profiles/new` non-dead (it currently discards 5 wizard steps on browser-back
   *and* on profile switch).
10. Add `jsdom` + `@testing-library/react` to `web/package.json` (currently hoisted from
    `apps/desktop` — the 5 DOM tests are one clean install from failing), and add the Playwright
    screenshot harness for 24 routes × 3 widths × 2 themes.

### P2 — Sakura Dusk theme (1 day)

1. `themes/presets.ts`: new default `sakura-dusk` (the six values in §3.2 + full `colorOverrides` +
   `seriesColors` + terminal colours + swatches). Add `THEME_NAME_ALIASES` for `default` and
   `luna-teal` so saved prefs resolve. Replace `default-large` with a *scale* variant that shares the
   palette rather than duplicating it.
2. Light counterpart `sakura-day` (the image's palette inverted: `#FBF0F8` canvas, `#1E1830` text,
   `#B96A84` accent) so light mode exists as a first-class citizen, not the odd `nous-blue` out.
3. Extend `themes/presets.test.ts`: every built-in theme must pass contrast on
   text/canvas **and** accent/canvas, and each semantic colour must clear 3:1 on the canvas. Today
   the test only checks 4 of 8 themes and only one ratio.
4. **Ship 3 themes, not 8** (decided): `sakura-dusk` (default), `sakura-day`, `mono` (retained as a
   real accessibility affordance). Retire `cyberpunk` (acid green on black — the opposite register),
   `ember`, `nous-blue`, `rose`, and `default-large`. Alias every retired id in
   `THEME_NAME_ALIASES` → `sakura-dusk` so saved preferences resolve instead of silently resetting.
5. Add `colorScheme` to the theme model (`dark | light`), emit it, and set `color-scheme` on
   `:root` so form controls, scrollbars and `::selection` follow. Then the 5 stray `dark:` utilities
   become meaningful instead of dead.
6. Update `luna/config/skins/luna.yaml` + `web_server_dashboard.py` so the **skin and the dashboard
   theme are demonstrably the same palette**, and fix `help.ts:172`'s claim to match reality. This is
   the single change that makes the product feel like one thing.

### P3 — Shell, IA, and layout (2 days)

1. **One nav manifest.** Collapse `App.tsx:209-252` + `resolve-page-title.ts` into a single
   `web/src/nav.ts` exporting `{ path, labelKey, icon, section, order }`. It becomes the
   source for: sidebar render, page titles, `document.title`, breadcrumbs, the command palette,
   and search. Deletes the hand-sync comment that admits the duplication.
2. **Sectioned nav** per §3.4, collapsible, persisted, RTL-aware, plugin tabs in their own group.
   Active state becomes the blossom glow from the one-ornament budget — and it gets a **background
   fill**, not just the current 1px left border, so the active page is obvious without relying on a
   colour difference.
3. `/onboarding` leaves permanent nav once complete (drive it off the existing
   `needsFirstRun(r.steps)` check in `lib/luna-onboarding.ts`) and becomes a Setup entry in System
   instead. `/analytics` gets hidden from nav *and* route when its flag is off, and its
   "edit `dashboard.show_token_analytics` in Config" copy (§2.9) becomes a real toggle. `/profiles/new`
   gets breadcrumbs and a dirty guard.
4. **Page header rework.** One `h1`, one toolbar slot, no `font-expanded text-sm` shouting. The
   current `h1` and the sidebar links share a class family (`PageHeaderProvider.tsx:84` vs
   `App.tsx:914`) so the page name and the nav items look alike — differentiate them. **Move the 5
   wasted Refresh buttons** (`CharacterPage:103`, `BehaviourPage:429`, `PeoplePage:123`,
   `OnboardingPage:84`, `HelpPage:14`) out of the header into the page body, and make the header's
   real primary action consistent (there are currently three vocabularies for "the main action").
5. **Tame the three worst structural offenders**, which are structural, not cosmetic:
   - `SystemPage.tsx:713-1649` — 936 lines, 11 sections, no nav. Split into sections with an anchor
     rail, matching the pattern `ConfigPage.tsx:554-604` and `SkillsPage.tsx:405-484` already use.
   - `OnboardingPage.tsx:216-407` — make it an actual wizard (one step visible, progress persisted)
     instead of five stacked forms.
   - `BehaviourPage.tsx:112-316` — split `WakePolicyCard`'s 11 fields into named groups with one
     dirty-aware save.
6. **Wordmark.** `☾` in Fraunces with the sakura tint; the `Luna` string at `App.tsx:645` becomes
   `t.app.brand`-driven so renaming the product is one i18n edit, not a JSX edit. Add a
   collapsed-rail monogram.
7. **Chat page** (`ChatPage.tsx`) — four specific fixes, not a rewrite (the embedded-TUI rule in
   `web/AGENTS.md` still holds):
   - Unify `chatPanelCollapsed` and `narrow` into one collapse state so the panel can never become
     unreachable (§2.11).
   - Fix the dead `showReconnectOverlay` branch (`:1803-1804`) so a hard close shows "Reconnect now"
     instead of a dead terminal.
   - Replace the `<Button>` scrim (`:1817-1826`) with a non-focusable backdrop so a full-screen
     control leaves the tab order.
   - Reclaim the side rail's wasted collapse row (`:2070-2081`) and add a terminal font-size control
     (currently auto-only, and drops to 7px below 300px). Use the already-computed
     `isViewportPinnedToBottom` to render a "jump to latest" affordance.
8. **Login page** (`login_page.py`) re-skinned to Sakura Dusk, off the Hermes display fonts, with the
   configurable attribution replacing the hardcoded "Nous Research" wordmark. It's server-rendered
   CSS — keep it that way, but make it a designed page rather than a restyled DS imitation.

### P4 — Page-by-page migration (4–5 days, the bulk)

Order by user-facing weight, not by line count. Each page: the type scale, the state vocabulary, the
token vocabulary, the `<Page>` layout, semantic colours, **plus the non-color items in the right
column**. Mechanical after tier 1.

| Tier | Pages | Why first | Non-color work they carry |
|---|---|---|---|
| 1 | `CharacterPage`, `BehaviourPage`, `PeoplePage`, `OnboardingPage`, `HelpPage` | The Luna product surfaces. Set the pattern, get the Fraunces voice. | Fix the 6 fixed-width/mobile breakpoints; rebuild the Behaviour threshold UI around the P-1 fix; make the onboarding wizard real; give Help a TOC + scroll-spy + working hash; de-jargon `weighted fit/msgfit/openq` and the regex prompt; split the stacked cards |
| 2 | `SessionsPage`, `ChatPage`, `ChannelsPage`, `PairingPage` | Daily-use surfaces | `SessionsPage` is the reference — extract its filter bar, bulk-select bar, pagination and action log into shared components and reuse them here; `ChannelsPage` gets the masked-secret reveal toggle |
| 3 | `ModelsPage`, `EnvPage`/`Keys`, `SkillsPage`, `McpPage`, `PluginsPage`, `FilesPage`, `WebhooksPage` | Operator surfaces | Fix `FilesPage`'s `min-w-[42rem]` with a card fallback; **mask `McpPage`'s env-var inputs**; label "env var name" vs value; table primitive; `PluginsPage` heading hierarchy |
| 4 | `SystemPage`, `ConfigPage`, `ProfilesPage`, `ProfileBuilderPage`, `CronPage`, `LogsPage`, `AnalyticsPage` | Densest tables | `AutoField` labels + inline errors + required marks (the Config page is currently unlabelled for AT); sectioned `SystemPage`; sortable/searchable tables; the new chart primitive |

Per-page acceptance: type scale only, zero literal `tracking-[…]`, zero hand-rolled
empty/loading/error states, `focus-visible` on every interactive element, a11y names on icon buttons,
keyboard reachable, **no fixed-width row that overflows at 390px**, every multi-field form
dirty-guarded, **no irreversible action without a confirm that states the consequence**, and a
screenshot at 390px / 768px / 1440px reviewed against §3.

### P5 — i18n and copy (2 days, do it *with* P4 not after)

Doing this last would mean touching every migrated page twice. §2.9 is the evidence that copy is a
real workstream here, not a translation afterthought.

1. Convert `content/help.ts` (184 lines, 9 sections) into the `i18n` system and re-voice it. It is the
   largest untranslated surface and it is the product's own documentation of record. Rebuild `HelpPage`
   around it: TOC rail, scroll-spy, working `location.hash`, search, and prev/next — the prose is
   already good, the page around it is not.
2. Move all `<Label>` literal children, 79 `placeholder=`, `title=`, and the hardcoded `<H2>`s into
   `t()`. Add the 9 missing `app.nav` keys so nothing is hardcoded English.
3. **Fix the locale workflow.** 16 exhaustive locales make every new key a 16-file chore. Convert the
   set to `defineLocale` partials with a compile-time check that *keys are complete in `en`* but
   *missing translations fall back*, and convert `ar.ts` (currently the only partial, and the shortest
   — Arabic falls back to English for most of the UI).
4. `en.ts:172-173` (`luna → "Luna"`, `AGENT → "Luna"`) is an accidental find/replace artifact.
5. **De-jargon the five product pages.** Define or remove `jev`; expand
   `fit/msgfit/openq/addressed/emojiconf/wait` into words with a direction ("higher = more likely to
   speak"); stop rendering `unknown key` raw; replace the `Action=… value=… route=…` dict dump; and
   **replace the regex prompt with a plain-language control** — asking a non-technical user to author
   regexes on an onboarding surface is the single worst copy failure in the app.
6. **Add the missing "why".** Every threshold needs one line on what lowering it does and why the
   shipped default was chosen. `config_schema.py:69-94` already has 26 good `description` strings —
   surface them in the UI instead of re-deriving labels from key names.
7. **Make the UI do what the copy tells users to do.** Wire "restart the gateway" to the existing
   action; turn `AnalyticsPage`'s config-key instruction into a real toggle; link the cross-page
   pointers instead of naming them; and have `OnboardingPage` link to `ChannelsPage`'s existing guided
   BotFather list instead of re-explaining it as prose.
8. **One label style** across the app — sentence case, sentence-terminated, consistent. Retire the
   three competing styles (§2.9). Active voice, no apologizing errors, empty states that invite an
   action. Product name from the persona.

### P6 — Assets, packaging, docs truth (1 day, parallelizable)

1. **Design the Luna mark.** ☾ as the seed is fine; it needs to be an actual asset — SVG favicon,
   `.ico`, PWA icon, tray/desktop variants, an OG image. Replace `web/public/favicon.ico` (currently
   the upstream Hermes mark) and wire `web/index.html:5`.
2. **Retire the vendored Hermes display fonts** (`web/public/fonts/Collapse-*`, `Rules*`, `Mondwest*`)
   once P3 lands, and drop the `/fonts/` allowlist entries from the pre-auth gate in
   `login_page.py` if nothing references them.
3. Add the brand-asset checklist to `AGENTS.md` §6 so a future surface can't ship with an upstream
   asset again.
4. **Fix the `web_dist` coupling.** The built SPA is ignored, and `assemble.sh` copies whatever local
   output exists while excluding `web/`. Build during packaging or provide a reproducible artifact
   step with a freshness check. Verify a clean checkout produces the current dashboard; rebuilding
   locally alone does not close this item.
5. Record the Chat-tab TUI gap in the threat model / known issues.
6. Update `luna/docs/engine-vendor.md` with every engine file this work touches, per AGENTS.md §4.

---

## 5. Sequencing and risks

```
P-1 bugs ──────────────────────────────────────────────┐
                                                        ├──► P1 foundations ──► P2 Sakura Dusk ──► P3 shell/IA ──► P4 pages
P0 brand truth ──┐                                     │                                                          │
                 ├──► (parallel) ──────────────────────┘                                                          │
P6 assets ───────┘                                                                                                │
                                                                                                    P5 i18n/copy
                                                                                              interleaved with P4
```

- **P-1 first, on its own.** The threshold-slider bug corrupts the wake cascade and the missing
  dirty-guards destroy user work. Nothing about visual polish matters until those are fixed, and
  they're small.
- **P1 before P2 before P3 before P4.** Migrating pages before the token/type/state/layout foundations
  exist means every page gets migrated twice.
- **P5 interleaved with P4**, not after: a page migrated without its strings moved through i18n is
  a page that has to be opened again.
- **P0 and P6 are independent** and can run in parallel with everything else.
- **Screenshot review is mandatory.** `web` has no visual regression harness. Add Playwright
  screenshots for the 24 routes × 3 widths × 2 themes as part of P1, otherwise P4 is unverifiable
  and "polish" is a claim rather than an observation. The 390px width matters most — six pages are
  currently unusable there.

Risks:

| Risk | Mitigation |
|---|---|
| Threshold-slider fix changes the wake cascade's behaviour | This is the point — it stops unguarded writes. P-1's tests must assert bounds come from `_RANGES`, and per AGENTS.md §3.4 any threshold *value* change still needs replay evidence (we're not changing values, only fixing the control) |
| Dirty-guards add friction to casual navigation | Guard only *dirty* forms; `beforeunload` only when dirty. Verify no regression in the 4 genuinely read-only pages |
| Focus trap in `useModalBehavior` changes focus behaviour in 9 portals | Land it, then re-test `ChatPage` + `ModelPickerDialog` + the OAuth modal first; they are the only keyboard-critical overlays |
| `main` switching to `overflow-x-auto` reveals latent overflow bugs | That's the point — but sweep for zero-height scroll containers and double-scrollbar artifacts during P1 |
| One `<Toaster/>` replacing 21 mid-tree hosts changes toast positioning | Single source for stacking; verify no page depends on a toast being positioned relative to itself |
| `Table` primitive forces a redesign of 10 surfaces at once | Land it on tier 1–2 first, retrofit the rest during P4 |
| i18n conversion breaks 16 exhaustive locales | P5.3 flips them to partials with a completeness assertion in the other direction |
| New `colorScheme` field breaks the theme contract | Extend the model additively; all fields are already optional, so old user themes still load |
| Palette contrast regression on the light theme | Extend `presets.test.ts` before shipping Sakura Dusk, not after |
| Engine re-vendor reintroduces gaps | P0.10 makes the docs truthful; the contract test in `luna/tests/contract/` stays the gate |
| Scope creep into `lib/api.ts` (2,747 lines, ~548 members) | **Out of scope for this pass.** File a follow-up; do not let a rebrand become an API rewrite |

Explicitly **not** in scope, so it doesn't creep: `HERMES_HOME`/`~/.hermes`/wire-contract renames,
Python import-path renames, `lib/api.ts` restructuring, the `ui-tui` slim-runtime gap, `apps/desktop`,
`website/`, and rewriting the embedded TUI chat (the `web/AGENTS.md` rule stands — ChatPage gets
layout and state fixes, not a new transcript).

---

## 6. Success criteria

**Correctness and safety**
1. No threshold write can fall outside its schema range; the wake cascade is no longer editable by
   dragging a slider to zero.
2. Every multi-field form is dirty-guarded, with a beforeunload and in-app navigation guard.
3. Every irreversible action (persona overwrite, SOUL import, identity merge, clear-all-pairings)
   has a confirmation that states the consequence.
4. No page surfaces a load failure as a toast; all 24 have loading, empty, error and retry states.

**Brand**
5. Zero user-visible "Hermes" outside the documented do-not-touch list, verified by grep with a
   stated reason for each survivor.
6. `PRODUCT_PLAN.md` and `engine-vendor.md` describe the rebrand accurately — no false checkmarks.
7. The CLI skin and the dashboard theme are demonstrably the same palette.

**Design system**
8. One token vocabulary, one type scale, one state vocabulary, one layout, one modal, one table, one
   toaster, one nav manifest — each with a lint rule or test preventing regression.
9. Sakura Dusk and Sakura Day ship as the defaults; 3 themes total, every one passing a contrast
   test on text, accent and each semantic colour.

**UX**
10. Every page meets the per-page acceptance bar in P4; no fixed-width row overflows at 390px, and
    overflow is reachable rather than clipped. Screenshots reviewed at 390 / 768 / 1440.
11. Every page has a content max-width; no page is a 900-line single column.
12. Every table is sortable and searchable; list surfaces have pagination or a stated bound.
13. Long operations show progress, and the replay result is rendered rather than toasted.
14. Command palette, breadcrumbs, and a `/profiles/new` flow that doesn't silently discard work.

**Accessibility**
15. Focus trap in every modal; `prefers-reduced-motion` honored globally; skip link; route error
    boundary; heading hierarchy valid; every control has an accessible name; `aria-live` announces
    async results and background polls.

**Content**
16. All 17 locales complete, `content/help.ts` fully translated, no hardcoded English in nav, labels,
    placeholders or headings, no unexplained internal jargon (`jev`, `msgfit`, `openq`) in any string
    a user reads, and no regex authoring prompt on an onboarding surface.

**Process**
17. `web` typecheck + its full test suite green; `scripts/test.sh` green; every engine edit recorded
    in `luna/docs/engine-vendor.md`; dashboard artifacts reproducibly built and included in packaging
    from a clean checkout, with freshness verification.
