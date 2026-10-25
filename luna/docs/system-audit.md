# Luna system audit

This is the pre-remediation audit. See [audit-remediation.md](audit-remediation.md) for the
subsequent implementation, validation and remaining release limits; findings below describe the
behavior before those fixes.

Audit of the current working tree, based on engine commit `3f50ff45d453` plus the uncommitted Luna
product changes. This covers the companion plugins, identity and memory paths, dashboard APIs and
forms, native OpenCode adapter, configuration, retention, installation, migration, rollback and CI.

The current tree should remain a pre-release until the P1 findings below are resolved. The main
problem is inconsistent ownership of profile scope, configuration and durable data across otherwise
working components. The existing suites pass while several important integration failures remain.

This audit added this report. Runtime behavior and the live deployment were left unchanged. The
reproductions used temporary homes, synthetic identities/messages and local fakes. No Telegram
poller, real chat history, provider credentials or cloud model inference was used in this audit.

## Findings, ordered by release risk

### F1 — P1: companion pages and plugins do not honor the selected profile

The dashboard has a global profile selector, but `/api/luna/*` is absent from the frontend's scoped
endpoint list and the companion routes do not accept/apply a profile. Several overlay path readers
also use process environment variables instead of the engine's context-local home.

**Reproduced:** `GET /api/luna/character?profile=second` returned the primary persona. A PUT to the
same scoped URL returned 200, changed the primary SOUL and left the secondary SOUL untouched. Under
a real engine home override for the secondary profile, the memory provider still selected the
primary `luna-state.db`; output shaping used the primary one-line limit instead of the secondary
seven-line limit.

This can mix identity/memory records and change the wrong companion. Fixing the URL parameter alone
will leave the plugin/background-thread side of the bug intact.

**Change:** introduce one profile runtime context and pass it through every application service and
background worker. Use the engine's scoped home and secret readers consistently. A smaller first
release can explicitly support one profile and hide/reject unsupported profile operations.

Sources: [frontend routing](../../web/src/lib/api.ts#L75),
[companion routes](../lib/luna_cli/web_routers.py#L305),
[dashboard home](../lib/luna_cli/tune.py#L20),
[memory home](../plugins/luna-memory/__init__.py#L48).

### F2 — P1: the memory adapter drops lifecycle calls and uses inconsistent connection settings

`LunaMemoryProvider` forwards `initialize`, `prefetch` and `sync_turn`, but its `on_turn_start`,
`queue_prefetch` and session-switch hooks are no-ops. Its identity signature is a constant. The
wrapped Honcho provider uses these hooks for turn/author tracking, refresh cadence and invalidating
pending recall. Its own identity signature tracks configuration/alias changes.

**Reproduced:** after calling the wrapper's turn-start hook for turn eight, the actual bundled
Honcho provider remained at turn zero with an empty author record. A queued prefetch was never
forwarded. The missing refresh hook can leave a cached agent consuming its initial memory context.
The constant signature also omits the backend's alias/configuration invalidation signal. Explicit
`turn_author` still reaches `sync_turn`; this finding does not establish that every written message
has the wrong author.

There is also a second configuration path: room/People sync constructs `HonchoStore` from env-only
defaults. With `honcho.baseUrl` configured as `http://127.0.0.1:18888` and a custom workspace, the
room writer still chose `http://localhost:8000` and workspace `luna`. Health checks and writes can
therefore target different stores.

**Change:** make a complete memory adapter with a tested lifecycle contract and a single connection
resolver. Keep the deterministic identity and recall budgets around that adapter. Add tests using
the actual bundled backend, including several turns and a live alias update. The earlier OpenCode
context checks verified delivery of supplied recall; they did not verify freshness of this backend.

Sources: [dropped hooks](../plugins/luna-memory/__init__.py#L259),
[backend refresh](../../plugins/memory/honcho/__init__.py#L649),
[backend turn tracking](../../plugins/memory/honcho/__init__.py#L719),
[room connection](../plugins/luna-logger/__init__.py#L147),
[People connection](../lib/luna_cli/api_models.py#L490).

### F3 — P1: room-to-Honcho delivery loses backlog and can duplicate writes

Backfill selects the newest N local rows on every pass. It has no durable delivery cursor/outbox.
The logger calls remote sync only when it indexed new gateway rows. A failed remote message-list
request is swallowed, after which the code writes the entire selected window again.

**Reproduced:** with 60 local messages and the shipped sync window of 50, the first pass wrote 50
and the second wrote zero. The oldest ten never reached the fake remote. Failing the remote
deduplication lookup then caused another 50 writes, producing 100 remote rows. An idle indexing
pass made no remote retry at all.

**Change:** use a durable outbox keyed by profile/chat/message, with delivery state, bounded retry,
backlog draining independent of new chatter and idempotency/reconciliation for uncertain writes.
Expose queue depth, oldest pending age and failures in System. A successful local index should not
be treated as a completed remote delivery.

Sources: [backfill window and dedup](../lib/luna_core/honcho.py#L165),
[sync scheduling](../plugins/luna-logger/__init__.py#L199).

### F4 — P1: shipped wake budgets fail validation, and a rejected save can enable wakes

The template uses `1000000000` as its unlimited day/week caps. The Behaviour writer and dashboard
schema accept a maximum of `1000000`. The form sends the whole policy, so changing an unrelated
field also submits those invalid defaults.

**Reproduced using the actual shipped template:** saving `dry_run: false` together with the unchanged
budget rejected `budget.message_max_per_day`, but still persisted `dry_run: false`. The directed
daily cap stayed at one billion. A user can receive a partial-save error while autonomous behavior
has already been enabled. The current frontend does report partial failure; the server has already
made the partial change.

**Change:** validate every proposed field before committing anything. Use an explicit representation
for an unlimited budget, with identical schema/runtime/form semantics. Keep a separate loop/cost
guard even when conversational timing is model-driven. Any change to wake thresholds or shipped
behavior needs replay evidence.

Sources: [template budgets](../config/config.yaml.luna#L431),
[writer bounds and partial commit](../lib/luna_cli/behaviour.py#L54),
[whole-form payload](../../web/src/pages/BehaviourPage.tsx#L291).

### F5 — P1: configuration changes are not one transaction

Companion writers read and rewrite config text without sharing the engine writer's lock or a
revision check. Character updates write SOUL before validating subsequent settings.

**Reproduced:** a paused Behaviour save read the old config; the real engine writer then committed
a new model. Resuming the Behaviour save restored the old model while committing its own change.
Separately, a Character request with a new SOUL and invalid `max_lines: -1` returned HTTP 400 after
the new persona was already on disk.

**Change:** one configuration service should own validation, locking, revision checks, atomic file
replacement and application status. Validate a complete patch first. Concurrent stale writes should
return a conflict. Multi-file character changes need a staged commit or a recoverable transaction.

Sources: [Behaviour read/modify/write](../lib/luna_cli/behaviour.py#L57),
[Character endpoint order](../lib/luna_cli/web_routers.py#L310),
[SOUL write](../lib/luna_cli/character.py#L119).

### F6 — P1: retention does not cover all raw-data stores

The in-process policy covers the Luna index and observed gateway rows. Normal transcripts have a
separate engine retention policy. Native OpenCode sessions and attachment snapshots are outside
the Luna policy. Its addition introduced another raw conversation store that needs explicit lifecycle
ownership.

**Reproduced:** applying one-day retention removed an expired canonical fixture row while leaving
expired synthetic data and an attachment under the native runtime tree untouched. This was a
policy-coverage probe, not a claim about OpenCode's private database schema.

Honcho raw-data pruning is also incomplete for the fresh managed stack: it is delegated to a timer
that the installer leaves disabled, and the pruner defaults to host `psql` on loopback port 5432.
The managed Compose database is deliberately private and exposes no host port. Simply enabling the
timer does not provide a working managed-stack pruning path. Processed long-term conclusions and
raw source retention should have distinct, explicit semantics.

**Change:** maintain a data inventory covering source transcripts, native sessions, attachments,
memory sources, derived facts, identities, logs and backups. Give each store a supported retention,
delete/export and backup operation. Run managed database maintenance through its own stack or a
supported service API; keep the database network private. Show actual last-success/coverage in UI.

Sources: [in-process scope](../lib/luna_core/retention.py#L232),
[native lifecycle](../lib/luna_core/opencode_client.py#L104),
[Honcho maintenance](../tools/prune_data.py#L124),
[disabled service definitions](../deploy/install_units.py#L46),
[private database](../honcho/docker-compose.yml).

### F7 — P1: upgrades can leave a mixed installation and retain deleted code

Assembly copies files into the active runtime in place. It records the new manifest but never
removes files absent from the new version. Dependency installation happens after the copy.
`rollback.py` stops trial units; it does not restore an earlier code/environment version.

**Reproduced:** a module removed from the source survived the next assembly. A subsequent assembly
rejected an external symlink after it had already replaced another active code file. The installation
was changed despite failure. A later dependency failure presents the same publication-order risk.

**Change:** stage immutable versioned code and its environment, validate them, then publish an
atomic current-version pointer. Keep state outside the release tree and retain the previous release.
Include tested state-migration/restore behavior. Preserve the standing rule that gateway restart is
the operator's action. Snapshot child-profile databases with SQLite's backup API too; currently only
root `*.db` files use it and the profile tree is copied as ordinary files.

Sources: [in-place assembly](../deploy/assemble.py#L52),
[copy before dependency sync](../deploy/install.sh#L59),
[trial stop helper](../deploy/rollback.py#L11), [migration](../deploy/migrate.py).

## Other product changes I would make

**Make group capabilities and memory visibility explicit.** Group and owner DM share powerful
toolsets. The ACP edit requester is bound only in ACP sessions; ordinary gateway file writes do not
all require an approval. Routing dangerous-command approvals to the owner therefore does not define
the whole access boundary. Recall has no surface visibility filter, and output redaction catches
email/phone patterns rather than arbitrary private facts. I would ship narrow group capabilities,
separate public-room/private-DM memory views, and explicit owner opt-ins for broader access. This
changes the documented choice to give groups full tools and should be a deliberate product decision.
Telegram privileged approval callbacks themselves are currently sender-gated and fail closed; the
older contrary statement in the threat-model document is stale.

**Make the character configuration authoritative everywhere.** Wake questions and the wake persona
blurb still name and describe Luna in code. Renaming the SOUL does not update them. Group shaping
unconditionally removes Arabic/Persian script and substitutes a fixed English response. The always-on
mechanical style filter also survives disabling the auto-loaded humanizer skill. Add explicit
character name/aliases/language/style configuration and derive the wake brief from it. Keep safety
policy separate from voice. Relevant sources: [wake identity](../lib/luna_core/cascade.py#L67),
[wake questions](../lib/luna_core/cascade.py#L321), [output policy](../lib/luna_core/text.py#L366).

**Bound actual group message size.** A 24,999-character, single-line synthetic reply passed the
configured line cap. Telegram will need multiple messages for it. Add a character/token and
delivery-count budget alongside the line cap, with a defined overflow behavior.

**Distinguish configured from verified and degraded.** An intentionally nonexistent native model
identifier was marked done when an installed binary was present. Honcho readiness tests HTTP health,
not write/read/embedding/derivation. Persist dated checks against the current config revision and
show chat, memory and self-wake readiness independently. Allow a useful reactive-chat mode while
optional services are unfinished. Provider quotas are external conditions; the Luna issue is a
misleading readiness state, not the quota itself. Sources:
[chat readiness](../lib/luna_cli/onboarding.py#L84),
[memory readiness](../lib/luna_cli/onboarding.py#L157).

**Define clearing and atomic CRUD semantics.** Sending null for pronouns/role from People returned
200 while retaining the old values. The API drops nulls before its write path. Use field-presence
semantics so omitted means unchanged and explicit null/empty means clear, with tests from the form
through the real endpoint. Source: [identity update](../lib/luna_cli/web_routers.py#L269).

**Keep native isolation and budget its resources.** Three native startup samples took 0.25–0.29s
and used roughly 247–267 MiB RSS each before inference; complete start/catalog/close took 0.68–0.71s
on this machine. Keep process isolation, cache catalog results and bound concurrent native workers
against a memory budget. Treat native protocol capabilities and experimental endpoints as an explicit
adapter contract. Add declared support for auxiliary options instead of silently dropping options
in the OpenAI-shaped adapter. Make native compaction/context pressure visible alongside Luna's own
history/compression state.

**Finish the release identity and operational surface.** The product still has 36 inherited workflow
files, upstream release/install automation, engine-derived version `0.21.3`, and overlay version
`0.1.0`. Audit inherited triggers/secrets before tagging. Give Luna its own release version and a
manifest recording engine/native versions, dependency lock and data compatibility. Keep the public
support matrix limited to tested platforms. The source-removal release smoke is valuable; add
failure-injection upgrade tests and a complete synthetic fresh-install → setup → message → memory
→ recall → restart scenario. The replay corpus also needs more room/persona/language/outage cases
before changing the shipped wake policy.

## What I would keep

The deliberate vendoring policy and engine-edit inventory; transport-derived identity; the sole
Telegram poller plus tokenless observe index; bounded user-sidecar context; code-enforced group
limits; authenticated/session-bound Luna MCP tools; isolated native credentials; guarded cron paths;
and installing a release outside the checkout after deleting its unpacked source.

## Implementation order

1. Establish supported profile scope, unify configuration transactions, fix the invalid default
   budget save, and complete the memory adapter/configuration contract.
2. Add the room outbox, visible delivery health, complete retention and a tested backup/restore path.
3. Make upgrades transactional and exercise interrupted copies, dependency failures and rollback.
4. Establish group capability/memory visibility policy, finish character-driven wake/language
   configuration, and introduce capability-level setup readiness.
5. Run a controlled Telegram trial with a separate bot and synthetic participants, including outage
   recovery, identity changes, approvals and restart. Keep the working personal deployment intact.

## Validation and limits

The audit reran **635 companion tests** (2 live tests skipped), **145 gateway tests**, **231 dashboard
API/engine contract tests** and **558 frontend tests**; all passed. The isolated probes then reproduced
the failures described above. Existing passing coverage is strong around individual helpers and
happy paths, with gaps around actual defaults, multiple profiles, real adapter lifecycle, backlog,
concurrent writes and interrupted upgrades.

Session evidence is stored under `/tmp/luna-system-audit/`: `probes.py`/`probes.json`,
`dashboard-probes.py`/`dashboard-probes.json`, `default-config-probe.json`,
`memory-config-probe.json`, `native-lifecycle.json`, and the API/frontend test logs. Companion/gateway
results are in `/tmp/luna-system-audit-suite.log`. These artifacts contain synthetic data only.

No live Telegram delivery, adversarial model exploitation, full Honcho derivation/recall-quality
evaluation, off-loopback deployment, macOS or Windows installation was performed in this audit.
