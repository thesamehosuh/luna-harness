# Desktop polish

## Direction

Keep Sakura Dusk: night `#17132b`, raised violet `#211b35`, blossom
`#eeafce`, lavender `#b8a8dd`, warm gold `#f3d6ab`, text `#f6eefa`.
Manrope handles controls and reading; DM Serif Display is reserved for page
titles and the launcher welcome. JetBrains Mono stays inside the terminal.

The launcher has one primary action and a short, truthful setup checklist.
Download progress uses bytes from the network; installation steps have names,
elapsed time and recovery actions. Startup preferences live in a disclosure.
Remove the native menu strip on Linux and Windows. Keep normal window controls.

The dashboard starts its navigation with Control Center and Chat. Everyday
companion pages stay visible. Files, schedules, extensions and diagnostics live
under a collapsible More section, retaining their existing routes. Control
Center puts model selection, account login, API keys and connection shortcuts
in one place, with search over all settings pages.

Chat keeps the shared Ink transcript and composer. Give text a readable minimum
size, remove the startup tools inventory from embedded chat, keep actions in a
toolbar, preserve the terminal across navigation, and keep session switching
and model changes explicit. No changing model context or prompt-cache policy.

## Performance evidence

Before changes, the installed dashboard in Chromium measured 60 fps at rest
and through navigation, with no frames over 50 ms. Native WebKitGTK rendering
must be checked independently; this browser result does not establish native
performance. Record native findings and final validation here before delivery.

## Implemented and checked

- Launcher settings open in an anchored drop-up, with outside-click/Escape dismissal and keyboard
  focus containment. The decorative circle is removed; the corrected crescent position remains.
  All dashboard marks, favicons and native icons come from `luna/assets/ui/luna-mark.svg`.
- Setup uses a compact step rail and one decision card. Free model selection and its action share
  a row. Telegram's bot token, owner/default-admin user ID and group ID are visible together.
  Memory separates model and effort rows. Persona cards show voice samples instead of initial
  tiles; Setup and Character share Easygoing, Warm friend, Dry wit and Curious mind templates.
  Prompts describe the character, with no dashboard/harness instructions. Existing custom personas
  remain available and are never overwritten automatically.
- System status, restart and update stay outside More. Control Center → Preferences owns chat
  palettes; individual colors are advanced. Model selection retains price confirmation and puts
  connected providers first, with account/key setup links inside the dashboard.

An isolated WebKitGTK 2.52.6 probe on the development machine measured the built Chat page at
60.05 fps (181 frames / 3 seconds, zero frames over 50 ms), using the native DOM terminal renderer.
The released baseline on the same idle probe also measured 60.15 fps. The original 5 fps report
was not reproduced; these measurements do not establish performance on every GPU or during a long
conversation. The changes remove root-wide style mutations, document crossfades, translucent
canvas backgrounds and the native terminal's additional WebGL layer.

Validation: dashboard typecheck/build and focused regression suites, launcher typecheck/lint/build,
native Rust build and cancellation tests, Luna unit/component/contract/replay suite, and the bounded
engine gateway contract subset. Native installation and connected-provider acceptance remain the
next user test. The operator approved publishing this pass as 0.1.0-alpha.4 after the release gates pass.

Final regression totals (2026-10-26): 572 dashboard tests; 830 Luna tests with 2 skips;
147 engine gateway contract tests; 31 native launcher tests with 1 pre-existing release-fixture skip.
Web and launcher builds, TypeScript checks, native Rust build and lint complete (zero lint errors).
The installed app/data reset is operator-specific and is not part of the product runtime.
