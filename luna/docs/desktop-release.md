# Building the desktop release

Luna's small native app is adapted from the vendored Hermes Tauri 2 bootstrap. The application
downloads a **versioned runtime release**, verifies its SHA-256, installs managed runtimes into
its own home, and embeds the existing dashboard. It does not clone `main` or build the dashboard
on an end user's machine. The dashboard owns onboarding and configuration.

## Release channel

[The public repository’s Releases page](https://github.com/thesamehosuh/luna-harness/releases) hosts the runtime archive and native installers.
The native app embeds one generated `luna-launcher-release.json` descriptor. That descriptor
contains the HTTPS archive URL, expected version and checksum. No public URL is guessed in source.
Release-mode Rust builds fail when the descriptor is missing.

The **Luna desktop release** workflow builds the archive once, then tests that exact archive
and builds installers on Linux x64/arm64, macOS x64/arm64 and Windows x64. Its default download URL
uses the workflow's own repository and tag `v<luna-release.json version>`. A workflow input can
select another HTTPS release-assets directory. The workflow uploads reviewable artifacts. Its explicit `publish` option creates a draft prerelease
only after all required native checks pass, attaches those exact archives/installers and generates
checksums and GitHub provenance. Platform certificates are separate; unsigned alpha previews
must remain labeled as such.

Publisher steps:

1. Set `luna-release.json` to a new version and push the reviewed source.
2. Run **Luna desktop release** with `publish` enabled. Publication waits for the complete
   reusable release checks plus every native/platform/data-path job.
3. Alpha previews are explicitly unsigned. Complete OS signing/notarization with the publisher's
   identity before claiming a frictionless beginner installation on macOS/Windows.
4. The workflow collects the exact tested files, verifies their runtime checksum, attests them,
   uploads them to a draft prerelease. Launch the packaged Linux artifact on the acceptance
   machine, then publish that exact draft after successful acceptance.
5. Have a tester install the published artifact on a clean machine without developer tools or help.

Developer-only equivalent:

```sh
python luna/deploy/build-release.py /outside/release-output \
  --download-base https://github.com/OWNER/REPO/releases/download/vVERSION
LUNA_RELEASE_DESCRIPTOR=/outside/release-output/luna-launcher-release.json \
  npm run tauri:build --workspace apps/bootstrap-installer
```

The version/URL are selected by the publisher. Never ship the illustrative OWNER/REPO/VERSION URL.

## Runtime and data ownership

- POSIX default: `~/.luna`; Windows default: `%LOCALAPPDATA%\Luna`.
- A legacy/nonempty unowned home is preserved. The desktop chooses a separate clean sibling home
  instead of importing old persona, keys or history. Explicit `LUNA_HOME` is a developer override.
- Code and dependencies live in immutable `releases/<id>` directories. An atomic JSON pointer
  selects the active and previous runtime without Windows symlink privileges.
- Runtime publication/rollback requires the affected gateways/native turns to be stopped. It does
  not restart a gateway. Personal settings and data remain outside the code release.
- The launcher authenticates a per-spawn identity including home, nonce, product and version.
  A different listener cannot satisfy readiness merely by answering a port probe.
- Only the bundled bootstrap window can invoke native setup commands. Rust checks its label and
  origin, as well as Tauri's capability policy. The dashboard uses ordinary authenticated HTTP.
- By default, closing the app stops its owned dashboard tree. Its stdin lifetime lease also stops the backend
  if the launcher crashes. A separately enabled companion gateway remains an operator choice.
- Repair is available through the native **Luna → Repair runtime** menu. It downloads a verified
  new runtime and retains personal data. A newer launcher offers a verified update; an older
  launcher does not offer a downgrade as an update. System exposes compatible prior-release rollback.

## Startup and background

The native **Luna → Launcher settings** menu and tray expose:

- **Launch Luna when I sign in**, disabled by default. Login starts the installed version quietly
  in the tray; updates/repair never run unattended. The entry pins the installation's home.
- **Keep Luna running when I close its window**, disabled by default. Closing hides the window
  while retaining the owned dashboard and its lifetime lease. Open Luna restores that window;
  Quit Luna stops the launcher/dashboard. If tray creation fails, close still quits safely.
- **Start my companion when Luna opens**, disabled by default, plus explicit **Start companion**
  and **Stop companion** controls. These reuse the authenticated dashboard gateway endpoints and
  verify the resulting running/stopped state. Configure the chat transport in the dashboard first.
  Independently managed gateway services retain the dashboard's existing lifecycle/ownership rules.

Native app preferences are private `.desktop-preferences.json` data in the owned home. Actual login
registration is queried from the OS, so a disabled OS entry is not misreported as enabled. macOS and
Windows reuse Tauri's autostart plugin; Linux writes its standard XDG desktop entry with quoted
arguments, including home paths with spaces. Single-instance activation raises the existing window.
Startup changes are never applied during installation or tests against the operator's real home.

Native validation uses Tauri's own WebDriver against the built application; it keeps startup entries
and runtime state disposable and removes test processes afterward. Native macOS/Windows acceptance
still belongs to their platform jobs and clean-machine tests.

`scripts/verify_desktop_launcher.py` checks the real Linux application, including all three palettes,
bundled typography, startup registration/removal, native permission boundaries, background close,
single-instance reopen and quit. Pass `--screenshot` only when the compositor supports WebKit's
capture endpoint; functional acceptance does not depend on a screenshot.

## Memory

Setup offers OpenCode's current free-model catalog immediately. Memory, Telegram and Jev are
optional and skipped choices persist. Memory setup handles Docker's native installer/OS prompts,
owned containers, pinned CPU embeddings, reasoning, vector schema, group attribution and repair.
The **Memory** page exposes the effective Honcho controls shown by `luna honcho status`, including
dialectic turns, reasoning effort/cap, passes, context budget/cadence, recall/observation/write modes,
workspace, peers and session strategy. Dashboard tuning feeds the actual client parser.

The bundled model is generic int8 multilingual MiniLM, 384 dimensions, with pinned tokenizer,
weights and Apache license/notice. Model/tokenizer total 135,391,039 uncompressed bytes; the current
complete runtime archive is approximately 91 MiB compressed. The native app, Python/Node/OpenCode
downloads and optional Docker/container downloads are separate and vary by platform.

The profile-owned worker loads embeddings offline and routes reasoning to the selected connection
without persona history or tools. A private generated credential authenticates every request.
Docker Desktop uses its built-in host DNS. Native Linux bridge failures can use an automatically
generated loopback-only connection layout without changing firewall rules. Existing Docker
contexts/workloads and incompatible embedding indexes are not taken over or erased.

## Harness branding and assets

Luna names the software. Setup, Character, People and Help describe the user's character as
their companion; new profiles use the neutral placeholder Companion. Existing personas are
preserved. Upstream engine attribution lives in Help → Credits and licenses, LICENSE and NOTICE.
Provider names such as Nous Portal remain visible when identifying an actual configured service.

`luna/assets/ui/luna-mark.svg` is the canonical harness icon. Both React applications import it;
`python3 scripts/generate_luna_icons.py` uses the workspace's Tauri CLI to generate native PNG,
ICO and ICNS files and the dashboard favicon. The public SVG is a generated copy for sign-in and
browser tabs. Regenerate assets before building native installers after changing the mark.

Dashboard and launcher start in Sakura Dusk and then apply saved preferences. Shared control and
panel radii also cover vendor selectors, segmented buttons, dialogs and notifications. Explicit
square-corner overrides on product cards/controls are removed; Mono/custom theme geometry still
comes from its own tokens.

## Evidence and remaining gates

Fresh defaults, portable profile files and the independent basic people directory are documented
in [Profiles and people](profiles-and-people.md). Native installation and the dashboard seed an
empty `PEOPLE.md`; imported shareable profiles do not carry people or connections from the source.

Local Linux evidence: companion/gateway regressions, frontend tests, real isolated Honcho with the
actual embedding model, offline multilingual retrieval, Rust archive/process tests, and installation
of the actual archive outside the checkout. The installed dashboard's identity, memory controls and
launcher-death lease are exercised by `scripts/verify_desktop_release.py`.

Native macOS/Windows/ARM jobs are configured; local Linux mocks do not certify them. Windows ARM
is excluded until all backend binary dependencies are available. Docker prerequisites still need
clean-OS acceptance testing, including declined permission prompts and required restarts. Signing,
publication, provider availability and the unassisted user test remain release gates.

References: [Tauri distribution](https://v2.tauri.app/distribute/),
[Hermes native Windows](https://hermes-agent.nousresearch.com/docs/user-guide/windows-native),
[GitHub runner platforms](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

## Native dependency support

macOS launchers require macOS 14 or newer. Intel Macs use pinned ONNX Runtime 1.23.2,
the last 1.23 patch with an Intel wheel; newer ONNX Runtime releases ship ARM-only Mac wheels.
Other supported platforms use 1.27.0. Every native job installs the actual archive and runs
the bundled multilingual model, so a missing platform wheel blocks publication. CI probes
run through the explicitly selected Python 3.11 interpreter rather than a runner's system Python.

## Linux packaging acceptance

The launcher pins Tauri CLI 2.12.2, including the upstream linuxdeploy/GTK plugin
update ([tauri#16062](https://github.com/tauri-apps/tauri/pull/16062)). Older
bundling could crash before startup when bundled display libraries met newer host
NVIDIA/Wayland drivers. Test the packaged AppImage as well as the debug executable.
Linux CI starts Xvfb before the D-Bus session so activated services inherit DISPLAY,
and retains native driver logs on failure.

The release workflow uploads an attested **draft** after every platform passes.
Publish that exact draft only after launching its packaged Linux installer on the
acceptance machine; do not substitute a locally rebuilt archive or installer.
