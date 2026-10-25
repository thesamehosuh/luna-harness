![LUNA-HARNESS](assets/luna-ascii.svg)

A self-hosted AI companion for Telegram groups and DMs, configured through a local dashboard.

- Custom characters, voices and model providers, including free models through OpenCode.
- Group turn-taking with bounded replies and separate recipients/topics.
- Optional Honcho memory with bundled multilingual embeddings and an editable `PEOPLE.md`.
- Optional ambient wakes, with adjustable behavior and offline replay.
- Profile import/export, background mode and launch-at-login controls.

## Install

1. Download your platform's launcher from [Releases](https://github.com/thesamehosuh/luna-harness/releases).
2. Open Luna and let it install the runtime.
3. Finish Setup in the dashboard. Telegram, memory and ambient wakes are optional.

On Linux, an AppImage may need **Properties → Permissions → Allow executing as a program**.
macOS requires version 14 or newer. macOS and Windows installers are unsigned alpha previews;
see the release notes for tested platforms and limitations.

Memory setup manages Docker/Compose and a local Honcho stack. Its reasoning model can follow
your companion's model. OpenCode's free model availability depends on its providers.

Existing installations are preserved. Use one running gateway per Telegram bot token.

## Development

See [Contributing](CONTRIBUTING.md) for setup and checks, [AGENTS.md](AGENTS.md) for repository
conventions, and [PRODUCT_PLAN.md](PRODUCT_PLAN.md) for the roadmap.

- [Desktop builds and releases](luna/docs/desktop-release.md)
- [Profiles, defaults and people](luna/docs/profiles-and-people.md)
- [Release verification and cutover](luna/docs/release-readiness.md)
- [Security reports](SECURITY.md)

Luna includes the vendored [Hermes Agent](https://github.com/NousResearch/hermes-agent) engine.
Product code lives under `luna/`; the dashboard is in `web/` and the Rust launcher in
`apps/bootstrap-installer/`.

## License

MIT, with Apache-2.0 portions in the native OpenCode integration. See [LICENSE](LICENSE),
[NOTICE](NOTICE) and the [OpenCode notices](luna/lib/luna_core/OPENCODE_NOTICES.txt).
