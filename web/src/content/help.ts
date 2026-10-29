/**
 * In-dashboard Help content (PRODUCT_PLAN P5 — distilled from the retired luna/docs/ user docs).
 * Plain markdown per section; rendered by HelpPage. Keep it product-facing: no engine paths,
 * no patch numbers, no dev workflow.
 */

export interface HelpSection {
  id: string;
  title: string;
  body: string;
}

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: "overview",
    title: "What Luna is",
    body: `Luna is the self-hosted harness that runs your personal AI companion. You choose your
companion's name, character and voice. Luna is the software's name; it does not name your character.

In groups your companion is a member of the room: short replies, the room's voice, memory of the
people in it, and mostly silence. In your DM the companion can use files, terminal, search,
scheduled tasks and skills, subject to your permissions.

Everything runs self-hosted: your model provider key, your server, your chat history. The only
outside services you need are the model itself and your chat platform.

Character sets who your companion is and how they talk. Behaviour sets when they speak up.
People keeps one identity per person, with group-specific names and roles. Groups brings each room’s people and notes together. Memory controls file maintenance and conversation recall. Fresh profiles use the placeholder Companion until you name
your character. The optional Luna example persona is one character, not the harness's fixed identity.`,
  },
  {
    id: "free-models",
    title: "Free models",
    body: `Choose OpenCode (free models) in Setup, or open Models and find OpenCode free models.
Install OpenCode if prompted, choose a model, press Test model, then Use this model. No chat API key
or terminal configuration is needed.

The list comes from OpenCode and only includes public models advertising zero input, output and
cache prices. Luna checks those prices again before each turn. OpenCode sets quotas and model
availability; if a test reports a usage limit, select another free model or try again later.

Luna still controls tool permissions, file approvals, identity, memory recall and group reply rules.
Free chat does not supply an embedding endpoint for memory or a Jev route for wake judgments.
Configure those separately in Setup and Behaviour. Existing API providers are also available.`,
  },
  {
    id: "wakes",
    title: "How waking works",
    body: `A wake is any moment your companion considers acting unprompted: a reply, a reaction, or a judgment
to stay quiet. Silence is the default, since most messages are not worth waking for.

Each new group message passes local gates first (enough new messages since the companion last spoke,
minimum substance, not a direct ask). Candidates that pass go to a small jev model over the route
chain you configure on the Behaviour page (free tier first, fallbacks when it is down). The
judgment scores the message: is there value in speaking, is it welcome, is it timely, is it
sensitive.

Cooldowns and daily/weekly caps sit between "the companion had something to say" and "the companion sent
it" (Behaviour, Budget and cooldowns). A reaction costs less than a message and is braked harder
against bunching.

With dry-run on (the shipped default), the whole pipeline runs and records its decision without
sending. Review the verdict feed on the Behaviour page; when the calls look right, turn dry-run
off. The feed records what was judged and how it scored, never the message text: tuning needs the
weights, not the room's words.

Every gate and score threshold is a slider on the Behaviour page with its code default marked.
The wake ledger records every wake (what, when, why). What-if replay re-judges recent history
offline so you can see what different thresholds would have done.`,
  },
  {
    id: "surfaces",
    title: "Surfaces and output",
    body: `Group and DM output follow different rules, enforced in code as well as in the persona.

Group replies are clamped: line cap, emoji policy (allowlist or strip), no markdown, no
AI-sounding tells, no personal details of other members. The hard limits are on the Character
page. The persona's style section shapes the voice inside them.

DM replies keep their length and formatting. Casual chat rewrites are optional in Character.
Within that style, Sentence line breaks replaces sentence punctuation with chat lines. Turn it
off to keep periods, semicolons and the model's layout. Emoticons, quotes, code and links are
protected; a trailing face stays with its sentence.

Non-conversational output (status cards, warnings, approval prompts raised while serving a group
turn) goes to your operator DM instead of into the group. The group only sees the conversational
reply. Set the operator chat id in Config, companion section.

Cron deliveries to a group get the group rhythm and no management envelope. DMs keep the full
job header and stop controls.

Groups take turns: one selected person gets an answer at a time in each topic. Nearby fragments
from the same person and reply chain can combine; different people's questions stay separate.
By default a burst gets at most three answer attempts, with a short pause between them. Older,
duplicate and excess requests are skipped, so ten mentions do not become ten late replies.
If yours was missed, tag again in a new message. One brief busy acknowledgement can appear.

Behaviour → Group conversation controls the limits and shows recent decisions. Topics and
groups stay separate, and your DM can proceed while a group is busy. In your DM, follow-ups
keep the configured interruption behaviour.`,
  },
  {
    id: "profiles",
    title: "Move a character and its settings",
    body: `Open Profiles and choose Export profile to download your saved persona, model choices,
behaviour, appearance and memory tuning together. Character's Export persona downloads just the
persona text, including edits you have not saved yet.

Import profile file shows a preview and asks for a new profile name. It never replaces your current
companion. Select the imported profile and open Setup to connect its model and chats. Memory and
proactive wakes stay off until you enable them.

Keys, sign-ins, chat connections, people, messages and local services are not shared in profile
files. Review persona text before giving a file to someone else. Additional skills may need to be
installed separately. Use a private data backup when you need to recover history and people too.

A fresh profile starts with a neutral character, balanced reasoning and text replies. Voice,
memory, wakes and automatic startup are choices you make during setup.`,
  },
  {
    id: "people",
    title: "People and identity",
    body: `Luna identifies people by their transport ids (a Telegram user id, for example). It never
guesses identity from display names or message text.

The People page starts with shared basic details for everyone. Choose a group to view or edit the
name, aliases, pronouns and short role used in that room. Each row links to the groups where that
person has been observed. Saving a group entry changes that room only; shared basics remain
available elsewhere. Use shared basic details removes a group override.

PEOPLE.md is a local directory that works without Honcho. The companion can maintain it during
conversation and periodic memory reviews. Model updates stay in the group or DM where they were
learned. It contains basic reference data, not biographies or secrets. The Memory page controls
whether people maintenance is enabled. Basic entry updates do not require approval.

Identity tools are under Local directory and identity tools. Merge accounts only when you know
both verified platform IDs belong to one person. Recovery requires a private data backup.
Sync basic identity cards to Honcho updates the memory layer’s identity references.

People and group notes are included in private data backups and excluded from shareable profiles.`,
  },
  {
    id: "memory",
    title: "Memory",
    body: `Your companion has saved Markdown files and optional Honcho conversation recall. They are
controlled independently on the Memory page. Turning Honcho off leaves saved files and their
maintenance settings intact.

In your owner DM, USER.md holds your profile and MEMORY.md holds private durable notes. Each group
and topic has its own public MEMORY.md and scoped PEOPLE.md entries. Group notes, people and
private files use the same file-memory flags, character limits, review interval and
background-review model settings. The companion can save useful facts during conversation and
review them periodically. With file-write approval off, it can add, replace, remove and consolidate
notes without approval. A zero review interval or disabled background reviews stops periodic reviews;
conversation-time updates can still happen.

Honcho runs locally in Docker and recalls relevant conversation knowledge. Attribution comes from
verified platform IDs. Public group recall can span topics; the current conversation and saved note files stay topic-specific. Recall is bounded per turn.

Open Groups to read or edit a room’s notes and people. Dashboard saves detect concurrent companion
updates and ask you to reload rather than overwrite them. Retention controls apply to the raw
message index; durable notes remain until edited or removed.`,
  },
  {
    id: "groups",
    title: "Groups, DMs and private reads",
    body: `Groups is the home for each room’s public notes and people. Topics are separate scopes.
Channels manages chat connections and admission. Behaviour manages when your companion speaks.
Memory holds the shared maintenance and recall controls.

A group automatically receives only its own notes and observed people. Your owner DM can look up
any saved group’s notes and people when needed, without automatically loading them into DM context.
Private reads in your owner DM need no approval.

To read your private USER.md or MEMORY.md from a group, the companion must request one-read
approval in your owner DM. The card shows the exact excerpt and destination group/topic. Share this
excerpt permits that snapshot only. Keep private, no response or an expired request shares nothing.
There is no always-allow option, and a group’s own approve command cannot unlock this request.
An approved excerpt may remain in the group conversation or be saved in its memory.

Setup makes the designated Telegram owner an admin in DMs and groups. Managed-bot setup uses the
owner verified by Telegram. Starting a DM alone does not grant ownership or admin access. Private
memory approvals always use that owner’s DM, regardless of the notification destination.`,
  },
  {
    id: "privacy",
    title: "Privacy",
    body: `Chat history, memory, identities and logs live in this installation's local data directory.
The optional memory stack runs in local Docker. Your configured chat, memory-reasoning and wake
providers receive the context needed for their requests. Self-hosting the harness does not make
a hosted model private to your machine.

Before connecting a group, review those providers. When you enable proactive wakes, the judgment
model (Jev) receives recent room lines. Behaviour shows its route chain and fallback providers.
Choose local endpoints if you want inference to stay on your machine, and review the chat platform's
own data handling. Memory and proactive wakes start off for new users.

The messages themselves are also carried by your chat platform, and model replies go to whichever
provider serves the conversation.

What gets stored, widest first:

• The room log. With observe unmentioned messages on (Config, telegram section), every message in
a watched group is recorded in full so the companion has room context for deciding when to speak.
Turn observation off to stop collecting unmentioned messages and the related proactive wakes.
• Message history and memory: the indexed room log, session transcripts, and the Honcho memory
store (people, commitments, preferences — small talk is not promoted to fact).
• Saved files: private USER.md and MEMORY.md, scoped group MEMORY.md notes and PEOPLE.md entries.
• Identities: a per-peer record derived from Telegram ids, plus names, pronouns, and roles you set
on the People page.
• Operational logs: wake verdicts, provider usage, errors. Wake logs record ids, reasons, and
weights — never message or reply text.

Retention is enforced, not aspirational: the window in Config (companion, data) is applied
automatically from the running gateway, so the room log above is bounded rather than growing
forever. Set retention to 0 to keep everything.`,
  },
  {
    id: "security",
    title: "Security posture",
    body: `Group access is limited to the configured chats, and user allowlists gate who may talk
to the bot at all (Config, telegram section). Privileged commands (admin slash commands) are
gated to configured admin ids, in the group and in the DM separately.

Approving an action is gated separately, and more strictly. When your companion needs approval, Luna
raises an approval prompt with Allow once / Always buttons. Only a Telegram id listed in Config →
telegram → allow from (or allow admin from) can press them — being a member of an allowed group is
not enough. The group allowlist answers "may this chat talk to my companion"; the approver list answers
"may this person authorise a command on this host", and only the second one unlocks approvals.

This is fail-closed: with no id listed, nobody can approve anything, including you. If approvals
ever stop working, put your own Telegram id in allow from. Using "*" there allows any member of the
group to approve commands, so only do that in a single-operator chat you fully control.

Set operator chat (Config → companion → notify) to your DM chat id and these prompts are delivered
there instead of in the group, so approval never depends on a group member seeing them.

The toolsets per surface are an explicit allowlist (Config, toolsets). Fresh group defaults allow
web tools, scoped people and group memory. Private-file requests require separate owner-DM approval. The owner's DM supports the broader assistant toolkit.
Actions requiring approval
raise an approval prompt that routes to the operator DM, and chat surfaces can never create
shell-backed cron jobs.

File writes go through the edit-approval guard. The terminal runs in a sandboxed policy with
command allowlists per surface.

All of this is a config edit on the Config page, so you can see and change it without reading
code.`,
  },
  {
    id: "appearance",
    title: "Appearance",
    body: `Skins are named colour palettes shipped as data. The product default is luna (the
Sakura Dusk palette); pick another on the Character page. A missing skin key inherits from
the built-in default skin, so a skin file only needs the colours it overrides.`,
  },
  {
    id: "credits",
    title: "Credits and licenses",
    body: `Luna is an independent harness for personal AI companions. Its vendored engine is
[hermes-agent](https://github.com/NousResearch/hermes-agent), by Nous Research, under the MIT license.
The repository's LICENSE and NOTICE preserve the engine and dependency attributions.

OpenCode, Honcho, model providers and chat platforms are separate projects or services. Their names
identify the integrations you configure; they do not name your companion or operate this installation.

The crescent-and-blossom mark identifies the Luna harness. Sakura Dusk is the default dashboard
and launcher theme. You can choose another theme without changing your character.`,
  },
  {
    id: "authentication",
    title: "Dashboard authentication",
    body: `The dashboard binds to loopback by default, reachable only from the machine it runs on,
with a session token generated at startup. If you expose it beyond loopback, an OAuth gate is
required before it will serve (the sign-in page tells you which mode you are in). The session
token is printed by \`luna dashboard\` and can be rotated from the System page.`,
  },
];
