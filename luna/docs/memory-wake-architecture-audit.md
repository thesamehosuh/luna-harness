# Memory and wake integration audit

The product has two independent memory systems: the companion maintains Markdown files, while
Honcho stores and recalls conversation knowledge. Jev judges whether to speak; it neither owns
identity nor changes the delivery policy. Public cross-group recall is acceptable to the operator;
write attribution and profile isolation still need deterministic transport scopes.

## Concrete defects corrected

- The Honcho bridge rejected function-tool requests used by Honcho's own reasoning loop. It now
  forwards function calls to compatible providers, and describes validated calls as JSON through
  native OpenCode. These are Honcho memory functions, never companion host tools.
- Public group recall was not wired to Honcho at all. It now reads public session conclusions and
  summaries. Stable group sessions and the durable outbox cover every admitted group, instead of
  syncing only the legacy main room. Existing group history keeps its identity. Public recall may
  span topics; each message retains its topic metadata. Notes, live context and wakes remain scoped.
- Named profiles read a different Honcho host block than the alias writer updated. Client reads,
  connection resolution and locked atomic alias writes now agree, including legacy local seeds.
- A cloned profile could retain a source workspace, endpoint and worker lease. Clones now keep
  their note choices but start Honcho disconnected with a separate workspace and fresh worker state.
  Copied proactive wake settings start disabled with no watched groups, so copied history cannot
  start unrequested judgments or posts under the new profile.
  This does not silently remap existing profiles or erase their remote data.
- The Luna provider hid Honcho's recall tools, making tools-only recall unusable. Private DM
  tools are forwarded; public group history has an explicit lookup. Cached providers honor the
  current on/off switch. Group automatic recall respects mode, cadence and injection frequency.
- The provider identity probe was uninitialized and hid configuration changes; its gateway cache
  also used only the provider name across profiles. It now fingerprints configuration and caches
  instances by profile home and provider name.
- Group file memory had no regular writer/reviewer. Its store now uses the existing memory flags,
  character cap, nudge interval and background-review route, with the same consolidation behavior.
  Notes are refreshed in the user sidecar, never in the cached system prompt. Group PEOPLE entries
  remain scoped in the local directory; they can be maintained with note memory disabled.
- Detached compression agents lacked the source chat scope. They now retain group/private
  boundaries. Private pending-write review is confined to owner DM.
- Jev could retain an old route's cooldown after a connection change. Route/key changes now clear
  that obsolete cooldown. Decisions are invalidated after persona changes. Canonical configuration
  loading preserves legacy watched-room and threshold-alias behavior.
- Offline replay ignored custom wake conditions. It now applies saved custom answers and reports
  where a changed rubric or missing answer cannot be re-judged offline. Wake thresholds are unchanged.
- Setup did not ask for a name and used a persona writer that could leave the configured identity
  stale. Setup now asks explicitly; persona saves update SOUL.md and the name together. Preset
  changes preserve the companion name. Internal compatibility IDs are not renamed.
- Behaviour slider writes could strand unsaved policy drafts by changing their revision. The API
  and page now carry the resulting revision and reject concurrent stale writes.

## Access and maintenance

Owner DM can look up group notes and people without automatic injection. Private USER.md and
MEMORY.md reads there require no approval. A group request for private files previews the exact
sanitized excerpt and destination in the configured owner's DM. Approval grants one snapshot;
no response, denial, expiry, interruption or a different approval scope grants nothing. Group
approval commands cannot resolve that independent queue. An approved excerpt may remain in the
conversation or saved group memory.

Group notes and private file updates are approval-free with memory.write_approval off, including
background consolidation. Basic PEOPLE edits are approval-free. Turning Honcho on/off does not
change those file choices. Verified owner setup already grants both DM and group admin access;
merely starting a DM grants neither ownership nor administration.

Groups is the room workspace. People is one directory with explicit group views and overrides.
Memory owns the shared file controls and Honcho service/recall controls. Channels handles admission,
Behaviour handles wake policy. Dashboard note and group-entry saves detect concurrent model edits.

## Validation

Regression coverage includes isolated files/topics, profile clones, named-host aliases,
profile-keyed provider caches, independent memory toggles, background consolidation, explicit
lookups, approved disclosure snapshots and owner-only notification destinations, new-route
cooldowns, stale persona decisions, custom-condition replay, naming and concurrent dashboard edits.
The final validation and installation results are reported in the conversation.

A subsequent real group conversation exposed gaps in the initial verification: successful memory
injection did not imply useful retrieval. The representation limit selected frequent explicit
observations before derived names/background, and paragraph token-overlap ranking promoted mentions
of the companion's name. Public recall now searches session-filtered conclusions across levels,
with separate bounded names/background/query sections. Explicit lookup also searches public
messages, resolves the current transport sender or an observed group member, and is directly
visible alongside the people tool. It never imports a global peer card into group context.

The Telegram observe path also stripped the live sender, overriding the configured session policy.
Commands retained their author, so `/new` reset a different conversation. Luna now preserves the
author for live turns and keeps observation storage separate. Configured per-person/topic lanes
therefore apply equally to replies and session controls.

The full vendored profile suite also contains four upstream assumptions that do not match Luna:
fresh profiles inherit the previous model/provider, and only upstream skills are seeded. Those
unrelated default-policy expectations remain unchanged. Clone-specific engine regressions and
Luna's own profile/transfer tests are the gates for this change. No live chat or model messages are
sent by the automated regression suite.
