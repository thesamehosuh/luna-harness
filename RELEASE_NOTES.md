# Luna 0.1.0-alpha.3

Guided, page-by-page setup now includes browser subscription login and the live model picker.
Honcho can share the companion’s model while using its own reasoning effort. Linux AppImages
add **Luna Harness** to the application menu and keep a launcher copy for menu/login startup.

This release refreshes vulnerable Python, JavaScript and native dependencies. Security checks
now gate release builds: complete-history secret scanning, all Python/npm locks and native
advisories. The GTK3 dependency includes the upstream pointer-safety fix. Old alphas remain
withdrawn. No personal credentials, personas or memory data are included in release artifacts.

## Install

Download the launcher for your system. It downloads the verified runtime and opens Setup inside
the app. Git, Python, Node and terminal commands are not required.

- Linux x64/ARM64: AppImage, Debian and RPM packages. For AppImage, enable “Allow executing as a
  program” in Properties if your desktop requires it. Its first launch adds the app-menu entry.
- macOS 14+ Intel/Apple Silicon: unsigned DMG preview; publisher signing/notarization is pending.
- Windows x64: unsigned installer preview. Windows ARM is not supported.

Existing homes are preserved. Your previous personal migration can be adopted by the launcher;
new users get clean setup. Keep one running gateway per Telegram bot token.

## Setup

Choose OpenCode’s provider-offered free models, an API connection, or sign in with a supported
subscription account. ChatGPT login uses OpenAI Codex. Pick the model you want; no particular
paid model is hardcoded. Memory, Telegram and self-wakes can each be skipped.

Memory reasoning follows the companion’s connection/model by default. Its effort is independent;
choose provider default or a supported level. Native OpenCode currently exposes provider default
only. Embeddings run locally with the bundled multilingual CPU model. Docker setup is managed
when memory is enabled and can require an OS permission prompt or restart.

Advanced agent, terminal, tool, channel, character and model controls remain available from Setup.
The launcher provides companion start/stop, background mode and opt-in launch at login.

## Alpha limits

Publisher certificates are not configured. Real Telegram traffic, crowded-room judgment and
fresh-machine Docker setup still need user acceptance. Free-model availability and rate limits
belong to providers. The tracked OpenCode cold-start tool-catalog race remains under issue #6.
The native scanner reports four upstream maintenance warnings; the security-gate guide records
these and the narrowly checked GTK3 backport.

Report failures at https://github.com/thesamehosuh/luna-harness/issues without credentials or
personal chat history. SHA256SUMS and build provenance accompany the exact artifacts.
