# Luna 0.1.0-alpha.1

First public alpha of Luna, a self-hosted harness for your own AI companion.

## Install

Download the launcher for your system below. It downloads the exact checksummed runtime from
this release and opens Setup inside the app. No Git, Python, Node or terminal is required.

- **Linux x64/ARM64:** AppImage, Debian and RPM packages. For AppImage, enable “Allow executing
  as a program” in the file's Properties if your desktop requires it.
- **macOS 14+ Intel/Apple Silicon:** unsigned DMG preview. Publisher signing/notarization is pending;
  this is not yet a frictionless beginner installation on macOS.
- **Windows x64:** unsigned installer preview. Windows remains preview while clean-machine
  Docker/restart and full chat acceptance are completed. Windows ARM is not supported.

Existing Hermes/Luna homes are preserved. Start with a clean setup; importing connections and
persona is a separate dashboard choice. Please keep your working installation until your trial
succeeds. Use one running gateway per Telegram bot token.

## Included

- Dashboard onboarding, character editing, profile import/export and Sakura Dusk default theme.
- OpenCode model discovery, including provider-offered free choices; paid APIs are optional.
- Optional local Honcho memory with a bundled small multilingual CPU embedding model, dashboard
  reasoning/cadence controls and a basic editable PEOPLE.md fallback.
- Bounded group turn-taking, pinned recipients/topics and privacy/output enforcement.
- Optional ambient wakes, disabled by default. Strict Jev responses, explicit routes, offline
  stored-score replay, attempt accounting and transport-confirmed delivery receipts.
- Launcher start/stop, background mode and opt-in launch at login.

## Alpha limits

CI exercises native builds and archive installation on the listed platforms; Linux additionally
runs the real launcher through a native webview. Signing certificates are not configured. Real
Telegram/model behavior, crowded-room judgment quality, and Docker installation on a fresh OS
still require user acceptance. Free model availability and rate limits belong to providers.
Memory is optional; Docker installation can need administrator approval or a restart.

Report issues at https://github.com/thesamehosuh/luna-harness/issues. Include your OS and the
step that failed; do not upload credentials or personal chat history. SHA256SUMS and GitHub build
provenance accompany these exact artifacts. They do not replace OS publisher signing.
