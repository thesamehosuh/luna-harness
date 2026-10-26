# Beginner setup and managed memory

Status: implemented locally with isolated validation; public release and native OS acceptance remain pending. The operator explicitly
wants to perform the normal installation personally. Do not install a new runtime, enable their
services or populate their setup while developing this work.

## Accepted requirements

- Automatic Docker setup: detect and reuse a working supported engine/Compose installation. If
  prerequisites are missing, the graphical installer manages platform-specific installation and
  readiness checks, using ordinary OS permission dialogs. Never send users to a terminal. Preserve
  existing Docker contexts and unrelated containers; no machine-wide daemon reset as a repair.
- Bundled local embeddings: ship weights, tokenizer, runtime and license notices with the supported
  release artifact/image. Pin revisions and checksums. Do not depend on an API key, account, GPU,
  LM Studio, Ollama, a model marketplace or a first-inference download.
- Simple Honcho setup, especially for groups: one user-facing **Set up memory** action must
  configure, start and verify the complete managed stack. No manual hostnames, dimensions, ports,
  database credentials, workspace ids, Compose commands or key environment-variable names.
- The product owns compatibility and repair. An embedding-model update must not silently change
  the vector space of an existing memory database, even when dimensions happen to match.
- A small Rust desktop launcher downloads Luna and opens the existing dashboard inside its own
  webview. The launcher contains bootstrap/progress/recovery UI, not another full dashboard or
  the complete repository. Onboarding remains in the dashboard.
- OpenCode free chat is the immediate first-use option. Memory and Jev are independently optional
  onboarding steps with persistent **Skip for now** choices. Skipping memory does not install
  Docker or start memory containers; skipping Jev does not block reactive chat or enable self-wakes.
- Honcho reasoning defaults to **Use my companion's model**. This follows the current model,
  provider and scoped credentials by reference; it does not copy a model name once and drift later.
  **Choose another model** exposes a normal picker, with raw endpoint configuration under Advanced.

## Audit baseline and remaining acceptance

The original setup expected an existing Docker installation and external embeddings. The reused
bootstrap was still branded as Hermes, and optional memory/wake setup counted toward one overall
completion state. The implementation below addresses runtime installation, memory provisioning,
bundled embeddings and independent skipped choices. Telegram's setup form still exposes group/admin
ids; the Channels page provides the existing pairing surface. A complete unassisted group setup
remains part of clean-machine acceptance, along with native platform installers and OS prompts.

## Proposed first-use flow

1. Open the Luna installer. It prepares the supported runtime and shows meaningful progress,
   resumable downloads and an actionable retry if anything fails.
2. Pick a character or accept the example, choose a tested chat connection and send a browser
   test message. Do not start by showing the whole model catalog or advanced provider fields.
3. Connect Telegram using a guided bot-creation/pairing flow. Detect the owner's transport id
   and selected room from verified messages; keep the gateway as the sole Telegram poller.
4. Choose **Set up memory** or **Skip for now**. Enabling memory prepares container prerequisites,
   the private Honcho stack, local embeddings and database schema, then performs real checks.
   Reasoning defaults to the companion's selected model; a different model is optional.
5. Offer proactive group participation with **Set up Jev** or **Skip for now**. Silence remains
   the default; no wake threshold changes without the existing replay evidence requirement.

The initial view should expose Character, Chat, Telegram and Memory. Move raw config, MCP, profiles,
provider environment names and developer diagnostics under Advanced. Keep a single clear state
such as **Chat ready**, **Memory preparing**, or **Needs attention**, with a concrete next action.
Explain that a self-hosted bot is available while its host is running. Background operation and
start-on-login are explicit user choices, separate from closing the dashboard window.

## Thin Rust launcher

Use Tauri 2 as the proposed shell: native Rust process/download management and the platform's
webview for the existing local dashboard. A vendored foundation already exists at
`apps/bootstrap-installer/`, currently branded/configured for upstream Hermes. It can inform
bootstrap progress, cancellation and platform process handling, but it is not a Luna launcher.
Xratu is a VS Code extension, not a Rust desktop shell; reuse its OpenCode installation/discovery
behavior rather than assuming its host startup is interchangeable.

Recommended startup:

1. Check the active runtime and the versioned release manifest. On first launch, download the
   checksummed release bundle, including prebuilt dashboard/chat assets, instead of cloning a
   moving branch and building on the user's machine. A release contains the runnable repo code;
   users do not need Git, npm or a compiler. Keep development source installs as a separate path.
2. Provision the supported Python/Node/OpenCode runtime with progress, cancellation and retry.
   The small desktop download is a bootstrapper; it does not make backend/model downloads vanish.
3. Start the backend on loopback using an available port, bound to the launcher's owned home.
   Wait for an authenticated readiness handshake identifying the expected Luna release/home.
   Never attach to an unrelated Hermes/Luna process just because a port answers.
4. Load the local dashboard's onboarding route in the webview. Keep all configuration there.
   Restrict any native IPC/download/process capability to the local bootstrap UI; external pages,
   model output and navigation to arbitrary web content must not acquire that authority.
5. Manage backend lifetime and show clear connection/restart progress. Closing the window and
   stopping the companion are separate, explicit choices; background/start-on-login is opt-in.
6. Update through staged verified releases and keep a recoverable prior version. Uninstall can
   remove application code while offering to retain or export personal data.

The vendored engine already supports native Windows, including a Tauri bootstrap installer,
managed PowerShell runtime stages, ConPTY dashboard chat, named-pipe gateway control and process
tree cleanup. Reuse those components. Luna's added release installer and locking/resource helpers
still need portable adaptation and native platform tests. See [the concrete reuse audit](windows-launcher-reuse.md).
Linux webview prerequisites and Windows WebView2 provisioning belong to the native installer.
Do not advertise untested backend support because a window compiles.

Build a Linux proof of the complete flow first, then native macOS/Windows CI and installer tests.
This is a launcher/runtime project; the existing dashboard remains the product UI.

## Reasoning model selection

The ordinary memory screen should have one default selector:

- **Use my companion's model (recommended)** — show the effective provider/model and reuse its
  existing scoped connection. No extra key/model-name field.
- **Choose another model** — list compatible configured connections and models. New-provider
  login/key setup should use the existing Models/Keys flow.

Changing the companion's model refreshes the effective memory route for the default selection.
An explicit memory override stays pinned. Test capability and credentials before declaring memory
ready, and report if the shared provider is busy or unavailable. Never fall back to a paid route
without the owner's configured choice. Explain that background memory tasks share that route's
quota/cost; local embeddings remain independent of those calls.

For a native OpenCode connection, add an OpenAI-compatible reasoning adapter owned by Luna.
Honcho requires an actual structured reasoning/derivation round trip, not just a successful text
probe. Keep those tasks separate from companion persona/history and host capabilities. Adapter
calls must use the selected profile/model and respect its auth/free-route and resource limits.
Validate the pinned Honcho image's response formats and retry behavior against the real native
engine before considering **Use my companion's model** supported for OpenCode.

## Bundled embedding design

A single profile-owned CPU worker serves OpenAI-compatible embeddings. Weights, tokenizer,
license and checksummed model contract ship in the runtime bundle; inference never fetches model
files. The same worker routes memory reasoning to the selected configured connection, without
persona history or tools. Its generated credential is private to the home/stack.

The current candidate is multilingual MiniLM with a generic int8 ONNX export, 384 dimensions and
128-token chunks. Longer messages are pooled across chunks with explicit token/size limits instead
of silent truncation. The worker uses the bundled tokenizer and rejects another tokenizer's ids.
Honcho sends strings and uses one endpoint for both queries and passages; this is why the initial
E5 candidate (with asymmetric query/passage prefixes) was not selected for this adapter.

Readiness checks include real English/Persian retrieval examples and CPU-only offline startup.
An existing different model contract fails closed even if vector dimensions happen to match.
External embedding stacks retain their existing advanced configuration; automatic re-embedding
of populated data is deliberately not part of the guided bundled-model setup.

## Managed Honcho bootstrap

1. Check engine/Compose availability, disk/RAM, private project identity and owned ports. Reuse
   existing working infrastructure without taking over another product's stack.
2. Generate private database/cache credentials and per-home workspace settings. Persist progress
   so a retry can resume safely rather than creating duplicate stacks or rotating live passwords.
3. Verify the bundled embedding service and expected model revision/dimensions.
4. Provision the database and run compatible schema/embedding setup before accepting memories.
   Validate against the pinned Honcho image, not only current upstream documentation.
5. Start Honcho API/deriver only after their dependencies are ready. Reuse compatible configured
   reasoning credentials where possible. Embeddings do not replace Honcho's reasoning model;
   native OpenCode chat is not automatically an OpenAI-compatible reasoning endpoint.
6. Verify write/read, real semantic search, derivation, multi-author attribution, room boundaries
   and cleanup. Report each result and retain resumable progress on failure.
7. Check persistence after restarting only the managed test stack. Offer retry/repair from the
   same dashboard flow, and never erase volumes as a default repair.

Existing memories require explicit compatibility checks. Honcho's upstream embedding configuration
script refuses populated vector tables; changing a populated deployment requires a separate
re-embedding/cutover plan and a recoverable backup. Preserve the old database until the new index
is verified. Same dimensions with different model weights also require a new index.

## Implementation now in the tree

- The existing Tauri bootstrap is adapted into the thin Luna launcher. It consumes a release
  URL/checksum baked at build time, downloads prebuilt runtime assets, provisions managed Python
  and Node, and opens the authenticated local dashboard. It never clones the source repository.
  The versioned public `thesamehosuh/luna-harness` Releases URL is supplied to the release build.
- Portable settings/native-worker locks use the engine's flock/msvcrt protocol. Desktop installs
  publish an atomic JSON release pointer, retaining the previous compatible runtime and data.
  Existing legacy homes are detected and kept separate from a clean desktop setup.
- Windows keeps the vendored ConPTY chat and reuses the PowerShell Git stage, with a scoped flag
  that suppresses global PATH/environment changes. Windows x64 is the initial native target;
  native Windows ARM is gated on binary backend dependencies (including pywinpty).
- Setup persists separate memory, Jev and Telegram skips. A skip gates the corresponding worker;
  fresh skipped memory performs no Docker setup. Chat can start before those optional steps.
- The Memory page exposes effective Honcho client tuning and status, including dialectic turns,
  effort/cap, passes, context budget/cadence, writes, recall and observation. Luna's YAML controls
  now feed the existing Honcho parser and override old JSON tuning defaults. Identity entries are
  preserved. Groups still recall only room-public material; conversational dialectic and Honcho's
  background derivation are separate operations.
- Honcho reasoning resolves the configured companion route per request, or an explicit configured
  override. The adapter rejects tools and validates JSON schema, including native OpenCode results.
  Provider credentials remain in the home; containers receive only a generated bridge credential.
- Release builds include a generic int8 multilingual MiniLM model, tokenizer, hashes and Apache
  license/notice. The embedding runtime loads only local ONNX/tokenizer files, uses CPU threads,
  preserves long input through chunk pooling, and rejects foreign token-id arrays.

The selected implementation candidate is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
with Xenova's pinned generic ONNX export (384 dimensions). Honcho uses the same embedding endpoint
for queries and passages without a role flag; MiniLM avoids E5's asymmetric prefix requirement.
Model plus tokenizer are **135,391,039 bytes** before compression. A local Linux x64 offline probe
measured approximately **1.03 s** cold load, **30 ms** for seven short English/Persian examples, and
**554 MiB** peak process RSS. Matching English/Persian pairs scored 0.78–0.98 versus lower unrelated
scores. These are development-machine observations, not an ARM or minimum-hardware certification.

The host memory worker uses a private generated credential and accepts no companion tools/history.
Honcho reaches it through Docker Desktop's built-in host DNS or the native Linux host gateway.
If the native Linux bridge cannot reach host services, setup uses Docker's existing host-network
mode for only the owned API/deriver and loopback-only random Postgres/Redis ports. It does not alter
host firewall rules. macOS/Windows may require approving the OS network-permission dialog.
Readiness includes real write/search/derivation, two attributed authors, private-session isolation,
owned-service restart and synthetic-workspace cleanup. Existing model contracts block automatic
reconfiguration of a different or populated index.

Local validation passed 684 Luna tests (two live checks skipped), the 145-test gateway contract
subset, 559 frontend tests and 218 dashboard/API tests. Subsequent setup fixes passed focused
regressions. The launcher passed 23 Rust/console/process tests and extracted the actual release
archive. The real Docker memory flow passed writes, embedding search, derivation, per-author
attribution, private-session isolation, restart recall and cleanup, including native OpenCode
against a zero-cost local model fixture. Offline multilingual embeddings and installation of the
actual archive outside the checkout passed. Browser checks confirmed optional-step skipping and
saved dialectic cadence reaching the installed Honcho client. Live free OpenCode checks returned
provider quota limits. No public release or operator-home installation has occurred. Native OS,
signing and clean-machine acceptance gates remain open in `desktop-release.md`.

## Required acceptance evidence

- A nontechnical tester installs the published artifact on a clean supported machine, receives a
  first reply and sets up group memory without terminal commands, edited files or coaching.
- A second installation/retry discovers the correct owned stack and preserves data and secrets.
- Skipping memory and Jev remains skipped after reload/restart, makes no Docker setup attempt,
  and still permits a first chat reply. Enabling either later resumes its own setup path.
- The default memory reasoning selection follows a changed companion model; a custom override
  remains explicit. Native OpenCode performs a real synthetic Honcho derivation without exposing
  persona history/host tools or selecting a paid fallback.
- Missing/denied Docker prerequisites, interrupted downloads, occupied ports, low disk and an
  unavailable reasoning provider each produce one clear repair action rather than a raw traceback.
- Bundled embeddings work offline, without GPU/account credentials, on baseline x64 and arm64
  hardware. Record measured memory and latency before declaring the default small enough.
- English, Persian and mixed-language synthetic retrieval examples beat unrelated distractors;
  returning constant vectors or only checking vector length cannot pass.
- A synthetic room with two distinct transport authors preserves who said what. Another room
  and an owner DM cannot leak private facts through that room's recall. A duplicate delivery is
  reconciled, and restart preserves attributed memory without another Telegram poller.
- A mismatched existing model/schema cannot trigger destructive automatic reconfiguration.
- Installs, repair, updates and uninstall leave unrelated Docker workloads and legacy homes intact.

## Suggested implementation order

1. Bundle and validate the embedding worker, then make Honcho provisioning fully managed.
2. Add the group-memory end-to-end check and actionable repair/progress state machine.
3. Simplify onboarding/pairing around the managed memory path.
4. Package the graphical installer/launcher and run the unassisted fresh-user acceptance test.

## Primary references

- [Multilingual E5 small model card](https://huggingface.co/intfloat/multilingual-e5-small)
- [Honcho embedding configuration](https://github.com/plastic-labs/honcho/blob/main/docs/v3/contributing/configuration.mdx)
- [Honcho embedding-schema configuration script](https://github.com/plastic-labs/honcho/blob/main/scripts/configure_embeddings.py)
- [Docker Desktop Linux prerequisites and engine contexts](https://docs.docker.com/desktop/setup/install/linux/)
- [Native installer packaging](https://v2.tauri.app/distribute/)
- [Tauri platform webviews](https://v2.tauri.app/reference/webview-versions/)
- [Tauri Windows runtime provisioning](https://v2.tauri.app/distribute/windows-installer/)

These references inform the plan; all runtime/image/model versions must be pinned and tested in
the implementation. Development validation downloads model artifacts and uses disposable Docker projects. The operator's stopped legacy services and real homes remain untouched.

## Guided setup update (2026-10-26)

Setup presents one page at a time using the shared Luna theme, with keyboard-focused headings,
Back/Next navigation, completion status and persistent optional skips. The account route embeds
browser subscription login and the live model picker; ChatGPT users choose OpenAI Codex without
an API key. Existing selected accounts count as configured. Advanced terminal, tool, channel,
character and model settings remain linked from Setup.

Honcho can follow the companion connection/model while using an independent reasoning effort.
The effort survives model changes and profile export/import. Provider default is the fresh-user
default; native OpenCode exposes only that setting and rejects unsupported overrides explicitly.
Codex subscriptions map selected effort through the engine's model-supported vocabulary.
