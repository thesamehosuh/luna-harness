# Profiles, new-user defaults and the basic people directory

Use **Profiles → Export profile** to download a versioned `.luna-profile.json` file. It contains
the saved persona, model selections and credential references, behaviour settings, output limits,
appearance, the selected custom terminal skin, skill selections and Honcho tuning. Character's
**Export persona** downloads only the current persona draft as `SOUL.md`.

Group turn-taking controls and per-person/topic session choices are portable too. Character's
**Sentence line breaks** switch travels with the output settings: with casual chat style enabled,
turn it off to preserve periods, semicolons and the model's line layout. Turning it off does not
disable group privacy or size limits.

Use **Import profile file** to inspect a file, choose a new profile name and create it. Existing
profiles, including default, cannot be overwritten. Missing settings receive the current product
defaults. Import validates the format/version, size, known setting types/ranges and skin names;
publication happens only after the complete new home is ready.

Portable files exclude credentials/login tokens, transport bindings/allowlists, people, messages,
databases, memory contents, local paths, shell/MCP extension commands, Docker/daemon wiring and
setup verification. `${KEY_NAME}` and key-environment names survive without being expanded.
Credential-bearing URLs and loopback model endpoints are cleared. Persona text is user-authored:
review it before sharing. Skills/extensions are not installed from an imported file; missing
auto-loaded skills are reported in the preview. Private data backups are the separate recovery path.

After importing, select the new profile and open **Setup** to reconnect its model/chats and optional
memory. Memory and proactive wakes stay off, setup proof is reset, and the memory workspace is new.
Honcho cadence/context/reasoning tuning and the model choice survive. Nothing registers startup
entries, starts a gateway or brings up Docker during import.

## New users

Defaults come from the product's checked-in new-user template, never a developer's installed
configuration. Fresh homes and fresh named profiles start with:

- A short neutral, editable companion named **Companion** in `luna/soul/DEFAULT.md`. Luna names
  the harness; the user chooses their character's name. `luna/soul/SOUL.md` remains the optional
  Luna example character. Existing custom personas and names are preserved. Room and TUI speaker
  labels follow the selected persona instead of forcing the harness name.
- OpenCode as the immediate provider option, with no fixed model. Setup offers its live catalog
  and checks the model the user selects. Main reasoning effort starts at medium.
- Text first: TTS off, no forced writing skill, casual-style rewriting off. Group output still
  enforces privacy/length/emoji limits in code; users choose their emoji palette in Character.
- Memory and self-wakes off until explicitly configured. Reactions remain opt-in. Honcho reasoning
  follows the companion; dialectic runs every eight turns with medium reasoning/cap initially.
- Sakura Dusk as the default dashboard/launcher theme, isolated profile credentials and workspace, no inherited chat
  connections, and launcher startup/background preferences off.

Fallback loading uses the same product defaults for missing settings. Persisted setup state and
existing `honcho.json` connection/tuning remain presence-sensitive: fallback values must not claim
setup completion or shadow an existing connection. The dashboard's Character/Behaviour views agree
with runtime fallbacks. Explicitly empty tool lists stay empty, including plugin tools.

## PEOPLE.md

Each profile owns a small `PEOPLE.md`, independent of Honcho and available when memory is skipped,
unavailable or rate limited. It is a basic directory: **name, up to four aliases, pronouns and a
short role**. It is not a biography, detailed memory store or source for inferred personal facts.
That limitation appears in the file, the tool description and the model's injected reference.

The model has a `people` tool to list/add/update entries. New people must already have an observed
transport ID; message text, guessed IDs and matching display names cannot create or merge identities.
Directory edits change metadata, never registry peers. The model write path uses the normal file
write guards, writes atomically and is confined to this profile's file. General file access is not
added to group chats. New group defaults allow web tools and this narrowly scoped people tool.

One Telegram ID identifies the same person across groups. Shared transport/dashboard basics form
the base entry. Model updates made in a group or DM are stored under that conversation's scope;
they never appear in a different group, forum topic or DM automatically. Group reads include only
people observed in that room/topic. Ordinary DMs see their own person's entry; configured owner DMs and local
authenticated interfaces may consult the broader basic directory. Accounts across transports
remain separate unless the owner explicitly links them through the identity registry.

Group/wake turns use the existing bounded ephemeral room sidecar. DM and local TUI/dashboard
turns use bounded per-turn reference context. No people facts enter the system prompt, channel
prompt or cached-agent signature. Honcho is never queried to build this reference.

The People page displays the local file. Its identity editor updates shared basic metadata;
model updates retain their conversation scope. Private data/release snapshots include the file;
shareable config/persona exports exclude it and seed an empty directory on import.

Regression coverage includes round-trip export/import into two clean profiles, credentials/history
exclusion, invalid/oversized files, existing-profile refusal, failed-publication cleanup, fresh and
partial-config defaults, Honcho JSON compatibility, guarded model writes, unknown IDs, room/DM/profile
isolation and `luna/tests/fixtures/people/multiple_groups.json` replay.
