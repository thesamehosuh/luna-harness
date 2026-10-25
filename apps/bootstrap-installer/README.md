# Luna desktop launcher

[Download Luna](https://github.com/thesamehosuh/luna-harness/releases). End users open the app;
setup and configuration happen in its embedded dashboard. No repository clone or terminal is
required. See each release’s tested-platform list and preview/signing limitations.

The Rust/Tauri launcher downloads one versioned runtime over HTTPS, checks its SHA-256 and installs
managed Python/Node runtimes in an owned home. The runtime includes the compiled dashboard and
pinned CPU embeddings. OpenCode, Telegram, memory and Jev are configured in Setup. Skipping memory
skips Docker setup. Existing personal homes are preserved; a clean sibling home is chosen when
necessary, without copying keys, persona or history.

The Luna menu provides runtime repair, launcher settings, launch at login, background mode,
companion start/stop and explicit Quit. Automatic startup/background behaviors default off.

## Development and publishing

From the repo root, install the npm workspace dependencies, then run
`npm run tauri:dev --workspace apps/bootstrap-installer`. Development builds without a descriptor
cannot download an unpublished runtime. Release builds require `LUNA_RELEASE_DESCRIPTOR` pointing
to the descriptor generated beside the exact runtime archive.

The [desktop release workflow](../../.github/workflows/luna-desktop.yml) builds a runtime once,
checks that archive on each platform, embeds its URL/checksum in the native installers and can
publish an alpha release after all required jobs pass. It generates SHA-256 sums and GitHub build
provenance. Publisher certificates are still required for trusted macOS/Windows distribution;
checksums and build provenance do not replace OS signing.

See [desktop release ownership and checks](../../luna/docs/desktop-release.md).
