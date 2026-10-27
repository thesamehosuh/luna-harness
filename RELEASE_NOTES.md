# Luna 0.1.0-alpha.9

- Rework Behaviour with editable Jev prompts, answer rubrics, reaction palettes and meanings, wake prompts, and custom conditions.
- Add an immediate on/off switch for wake behaviour and controls for model routes and pacing.
- Fix saving watched groups and show the specific reason when a settings save is rejected.

# Luna 0.1.0-alpha.8

- Reset stale context usage after deferred group-chat summaries commit, avoiding repeated compression notices.
- Fix the Memory page's Honcho health-check request so it reaches the data-path verifier.
- Save Telegram owner and group destinations from onboarding; refresh Honcho ports after Docker restarts.
- Enable or stop Honcho from the Memory page.

# Luna 0.1.0-alpha.7

- Telegram setup now saves the owner DM as the notification home and binds the selected group.
- Pairing setup applies the verified owner ID, without guessing from message text.
- Repair same-indent YAML list updates so saved Telegram access lists do not retain stale entries.
- Refresh Honcho's loopback database port after Docker restarts so memory starts with Luna.
- Enable or stop Honcho from the Memory page without opening Setup.
- Send the expected request body when checking Honcho data-path health.

# Luna 0.1.0-alpha.6

- Start gateway works in desktop installations without an OS service.
- Control Center can enable/start or remove an optional background service.
- Gateway actions follow the selected runtime immediately after an update.
- Existing service installations retain their service manager; no extra service is installed.

# Luna 0.1.0-alpha.5

Onboarding and gateway hotfix.

- Current Codex models appear in every picker; Refresh Models updates the catalog.
- Gateway status and Start/Stop/Restart controls sit at the top of Control Center.
- Restart finishes when the new gateway is running, with a bounded failure state.
- Telegram setup saves, enables and connects the bot, then verifies its connection.
- Stable numbered setup steps and dropdown labels that stay visible during save/test.
- A quieter chat canvas with an anchored composer and less terminal status clutter.

Your saved character, accounts, Telegram settings and memories are retained.

# Luna 0.1.0-alpha.4

A redesigned launcher and a simpler dashboard setup flow.

- Clear download/setup progress, cancellable downloads and an anchored launcher settings panel.
- Control Center for models, account sign-in, API keys and appearance. System actions stay visible.
- Compact onboarding, visible Telegram owner/admin and group IDs, and four editable persona presets.
- A cleaner model picker, consistent Luna controls/icons, and chat actions that preserve your draft.
- Rendering changes reduce full-page repaints and keep native chat on one terminal renderer.

Download the small installer for your platform. It downloads the verified runtime, then opens
onboarding inside the dashboard. Telegram, memory and self-wakes are optional.

These alpha installers are unsigned. macOS requires version 14 or newer; Windows remains a preview.
Free-model availability and account limits depend on their providers. The reported 5 fps slowdown
was not reproduced on the release machine; long conversations and additional GPUs need user testing.

Existing settings and memories are preserved during an update. A clean install starts with the
neutral Easygoing companion; persona changes require explicit selection.
