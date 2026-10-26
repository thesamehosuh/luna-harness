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
