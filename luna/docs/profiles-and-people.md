# Profiles, new-user defaults and the basic people directory

**Memory → Files** edits private `MEMORY.md`, private `USER.md`, the complete `PEOPLE.md`
directory, and every observed group's `MEMORY.md`. People and Groups link directly to the
relevant file editor. Raw directory edits keep the observed transport IDs and group/DM headings;
the structured People form remains available for editing one entry. Saves reject stale revisions
after another tab or model turn changes a file and preserve the user's draft. The Memory settings
tab keeps file-maintenance switches separate from Honcho. Manual editing remains available when
automatic memory use is off. Private cached notes load in new conversations; group notes and
people updates are read on the next relevant turn.

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

- A neutral, editable companion named **Companion** in `luna/soul/DEFAULT.md`. Luna names
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

Setup and Character share four persona starting points: Easygoing, Warm friend, Dry wit and
Curious mind. Voice samples appear in Setup; the complete prompts are available before applying.
Custom personas remain a separate choice. Selecting a preset is explicit; updates never replace
an existing persona automatically.

## Group MEMORY.md and private lookups

Each profile/group/topic has its own `memories/groups/<scope hash>/MEMORY.md`. It uses the real
Hermes MemoryStore and memory tool: atomic add/replace/remove batches, character limits and the
existing `memory.write_approval` gate. `memory.memory_enabled` enables these notes;
`memory.user_profile_enabled` also controls periodic PEOPLE.md maintenance. The existing
`memory.nudge_interval` and `auxiliary.background_review.*` settings control automatic reviews.
With write approval off, consolidation can update older entries without creating approval proposals.
Background group reviews have only the scoped memory and people writers; they cannot read private files.
Group notes refresh through the user sidecar, never the cached system prompt.

The `group_memory` tool lists and reads saved group files in the owner DM. The `people` tool accepts
`chat_id` and optional `thread_id` for explicit owner lookup/update of scoped group entries. Neither
automatically injects other groups' files into a DM. Ordinary DMs cannot use owner lookup privileges.

The `private_memory` tool reads private USER.md/MEMORY.md directly in the owner DM. In Telegram
groups it selects a bounded, redacted excerpt locally and requests explicit approval in the
configured owner's DM. The approval shows the exact snapshot and destination group/topic/message,
offers share-once/deny only, and uses a separate random request queue that group `/approve` cannot
resolve. Denial, timeout, cancellation or delivery failure releases no private content. An approved
excerpt may remain in the destination group's conversation and saved memory, as the owner preview
states. A changed source file cannot replace the snapshot after approval. File-write approval and
global automatic approval settings do not bypass this disclosure gate.

Honcho room writes and recall use the same stable public group session namespace. The indexer
syncs admitted groups, rather than only the main configured room. Existing group history remains available without a reindex or identity reset. Public recall may
span topics; topic tags remain on messages. File notes, live context and wake dispatch stay
topic-scoped. Private DM sessions are unchanged.
