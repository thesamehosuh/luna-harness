# Group conversation: audit and implementation

Implemented in `luna_core.room_dispatch`, before adapter merging, typing or agent creation.
The original probe reproduced ten independent ordinary-group agents and several authors'
questions merged into one shared-topic prompt. Per-session queues did not provide turn taking;
a global gateway limit of one would also block DMs.

## Shipped behaviour

Each profile, bot, platform, chat and topic has a conversation lane with one active selected
turn, including delivery. Other groups/topics continue within a bounded concurrency limit.
DMs bypass room admission. Existing per-person sessions/caches remain. New profiles also use
per-person topic sessions. Explicit existing session-sharing choices are preserved; switching
identity in a shared agent still requires the engine's safe cache rebuild.

Defaults available in **Behaviour → Group conversation**:

| Control | Default |
|---|---:|
| Collect a short burst | 1 second |
| Pause after an answer | 2 seconds |
| Waiting requests per lane | 16 |
| Waiting lifetime, including transport backlog | 60 seconds |
| Selected turn lifetime | 120 seconds |
| Answer attempts per burst | 3 |
| Quiet gap starting a new burst | 8 seconds |
| Attempts per minute per lane | 6 |
| Active groups/topics per bot/profile | 4 |
| Brief busy acknowledgement | Enabled, at most once per minute |

Three attempts is a ceiling, not a promise of three messages: silence and provider failures
also consume attempts. Ten simultaneous mentions do not become ten delayed replies. Skipped
questions need a new message/tag. Selection is local and adds no planning model calls. Ambient
thresholds and Jev budgets are not loosened.

Only fragments from the same transport author and reply parent combine, inside the collection
window and without media. Actual replies to the bot take priority, followed by questions and
age. If someone else is waiting, one author cannot take a third consecutive slot. Waiting edits
replace the request; edits during generation cancel the obsolete answer and require a new tag.
Restarts do not replay previously admitted work. Durable receipts retain 1,000 message IDs;
lanes, pending work, in-memory receipts and question exclusions are bounded too.

Only the selected turn starts typing. There are no per-person queue notices. The dashboard
shows active/waiting targets and recent decision reasons. Its decision ledger stores metadata,
not request bodies or credentials. Expired leases and stopped/replaced gateways show as skipped.

## Recipient, context and cache

Each selected event gets an immutable transport target: profile home, platform, chat/topic,
author, original message IDs, reply anchor and revocable deadline. A ContextVar carries it into
the existing user-message hook. Other questions are explicitly background rather than tasks.
The companion may return `NO_REPLY`; shaping preserves the marker until delivery consumes it.

Other authors' unanswered requests are excluded from the room sidecar and raw room recall.
Room history, reply chains, PEOPLE membership/edits and group recall are topic-scoped. Legacy
rows with unknown topic metadata remain stored but stay out of scoped context until reindexed.
Names and in-band author labels cannot choose identity. A giant roster is discarded before it
can evict the selected request.

Code pins reply anchors and checks source/profile/deadline, including retries and media
preparation. Selected group replies stay out of generic durable delivery: that queue cannot
preserve their short relevance window and anchor across a restart. DM recovery remains intact.
Cancellation uses the engine's generation-safe hard interrupt, not just asyncio cancellation.
Old queued follow-ups re-enter admission with their own targets. Ambient admission yields to
human requests and checks room activity before spending a Jev call.

**Dynamic targets, rosters, pending questions, PEOPLE edits, recall and activity never enter
the system prompt, channel prompt or cached-agent signature.** Real native OpenCode checks
inspect inference payloads: targets vary in user context while the system and resumed user
prefixes stay byte-stable. Existing cache/sidecar contracts continue to gate the implementation.

## Verification and limits

Deterministic tests cover ten authors in a shared forum topic, independent rooms/topics and
a concurrent DM; fragment/author boundaries; priority/fairness; edits; queue/age/rate limits;
provider failure; timeout/shutdown; restart receipts; silence; and stale media/retry suppression.
Topic/indexer/PEOPLE and adversarial in-band identity cases have regression fixtures. Dashboard
controls use the existing atomic revision-checked draft.

The final suite passed 779 companion tests (2 live tests skipped) and 145 gateway contracts;
566 frontend tests, browser save/reload checks and fresh packaged-dashboard checks also pass.
Four real native OpenCode inference payloads confirm targets remain user context and resumed
prefixes stay stable. Character exposes a separate sentence-line-break switch, with emoticons,
links, quotes and code protected from punctuation splitting and whitespace cleanup.

Correct routing cannot guarantee every model's semantic relevance. The selected question is
authoritative, but meaning still needs a live group rehearsal. Telegram bots do not receive a
universal deletion event, so deletion alone cannot always invalidate work. A human answer is
contextual evidence for model silence, not a deterministic already-answered classifier.
Scheduled deliveries and arbitrary external direct sends are separate from admitted companion
turns. Keep the archived deployment until a throwaway bot/group has exercised real edits,
reconnects and model latency. This implementation starts no Telegram poller and changes no
operator runtime configuration.
