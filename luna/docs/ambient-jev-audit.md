# Ambient wakes and Jev: audit, 2026-10-25

**Remediated, 2026-10-26.** The findings below describe the original audit. Production fixes
and deterministic regressions now cover all twelve findings; this is not a live model-quality
certification. Optional wakes remain off by default, reaction permissions remain empty and wake
thresholds have not been relaxed.

Implemented: one profile-aware validated Jev factory, explicit keyless routes and free-only default
routing; strict typed safety answers; offline replay of stored scores with zero model calls;
room/topic-scoped context and watermarks; durable intent reservations and actual transport receipts;
source/config/enablement checks before generation and delivery/retries; shared retry deadlines and
per-attempt usage admission; honest Setup proof and worker health; gateway-owned worker shutdown.
The dashboard exposes selected watched groups and unknown-price calls. Dynamic content still uses
sidecars/user context, preserving the prompt-cache contract.

Verification: **817 companion tests (2 live skipped), 147 gateway tests, 568 dashboard tests**.
Additional focused delivery and final core checks passed (77 and 105 cases). The new regression
suite is `luna/tests/component/test_ambient_jev_regressions.py`; real adapter receipt/retry tests are
in `test_room_dispatch_gateway.py`. Hosted judgment quality, provider availability and unassisted
native installation remain alpha acceptance work, not established by synthetic tests.

## Evidence and scope

Reviewed the indexer → candidate → Jev → deterministic cascade → resource guard → gateway →
reply/reaction path, plus Setup, Behaviour health, cost reporting, What-if replay and worker
lifecycle. The original developer probe (retained with the ignored historical evidence)
reproduced **19 cases, with no probe errors**. These collapse into the 12 findings below.
The relevant existing unit/component/contract tests still passed: **189 passed**.

All reproductions used disposable homes, synthetic identities/history/credentials and mocked
transports. Network access through the client was blocked; no real model, Telegram or Honcho
requests were made. The lifecycle probe started and explicitly stopped its own mocked worker.
Probe exit code 1 means a finding reproduced; these are characterizations, not passing regression
tests for future fixes. Sanitized machine-local evidence is retained under
`ignored/luna-ambient-audit-20261025/`; that directory is excluded from release assembly.

To run the current regressions with development dependencies installed, use a disposable home
and run `python scripts/audit_ambient_jev.py`. This invokes passing regression tests rather than
the historical bug-characterization probes. It makes no live provider or chat requests.

This establishes code defects and deterministic consequences. It does not measure actual Jev
judgment quality, hosted availability, large-room social timing or provider billing.

## Historical release blockers (P1; now remediated)

### 1. What-if replay can disregard a local-only route and send mixed history remotely

[Dashboard replay](../../luna/lib/luna_cli/api_models.py#L350) launches
[jev_replay.py](../../luna/tools/jev_replay.py#L90). The tool builds its own hosted-default client
using `OPENCODE_ZEN_API_KEY`, rather than the profile's configured provider chain. Its context
loader combines messages across chats/topics. “Offline” here means no chat posts; the tool makes
fresh model requests. It also ignores most configured cascade thresholds, uses permissive
in-memory wake budgets, enables a reaction palette and bypasses the runtime judgment guard and
usage ledger. Consequently it is neither a faithful simulation nor a reliably local operation.

**Evidence:** `replay_ignores_local_only_configuration` captured a hosted client target despite
a local-only configuration, mixed-chat state and two fresh judgment calls. Network was mocked;
this demonstrates the outbound request path, not an actual disclosure during this audit.

**Fix:** first prevent implicit hosted replay. Provide genuine offline replay of recorded
judgments. Any explicit live re-judgment must show its destination, use the common profile client,
scope one room/topic, honor configured thresholds and enforce/meter its own limits. Preserve the
distinction between simulated outcomes and delivered wakes.

### 2. Client construction can attach the wrong key or silently restore a hosted route

[Ambient client construction](../../luna/plugins/luna-ambient/__init__.py#L388) substitutes the
OpenCode Zen credential when a named primary route omits `api_key_env`. This contradicts the
documented keyless-local behavior: moving a local/custom route first can attach an unrelated
hosted credential to that endpoint. The primary's configured `endpoint` and client-level
`instructions` are also dropped. An explicitly empty/unresolved route becomes the hardcoded
hosted default instead of a configuration error.

[Setup fallback construction](../../luna/lib/luna_cli/onboarding.py#L573) omits the profile-aware
credential resolver; fallbacks read process environment instead. The primary can use the right
profile key while a fallback uses a different process-level key.

**Evidence:** `primary_key_and_endpoint`, `empty_route_creates_hidden_default` and
`setup_fallback_uses_process_key` reproduced these behaviors with synthetic keys.

**Fix:** share one validated client factory across runtime, Setup and replay. Missing credentials
on an explicitly keyless route must mean no Authorization header. Respect explicit endpoints,
timeouts and all route credentials consistently. Distinguish absent legacy configuration from an
explicit empty/invalid route; show the latter as disabled/misconfigured instead of contacting a
different provider. Do not silently substitute a paid provider.

### 3. Jev's decision context still crosses topic boundaries; reply lookup crosses chats

[Candidate selection](../../luna/plugins/luna-ambient/__init__.py#L553),
[recent context](../../luna/plugins/luna-ambient/__init__.py#L604), last-spoke timing and the
evaluation watermark are not scoped per topic. The parent lookup matches `message_id` without
`chat_id`, although message identity is composite. Colliding Telegram message IDs can therefore
attribute a reply to someone in another room. Earlier topic isolation in reply generation does
not repair the preceding judgment's context.

**Evidence:** `mixed_topics_and_reply_chats` included another topic's synthetic text and selected
the wrong chat's reply parent. Busy topics can additionally dominate candidate selection.

**Fix:** carry trusted profile/platform/chat/topic/message identity through every stage. Scope
candidate scans, recent context, reply joins, watermarks and timing accordingly. Keep any global
emergency resource cap separate from conversational scope. Dynamic scope stays in the user or
ephemeral sidecar path, preserving cached prompt prefixes.

### 4. Invalid safety answers can permit a wake; malformed JSON can spend a paid fallback

[Answer parsing](../../luna/lib/luna_core/jev.py#L109) does not fully validate answers against
the requested question schema. Failed probability conversion returns zero. Thus malformed
privacy/sensitivity answers can be interpreted as low risk by the deterministic cascade instead
of causing silence. HTTP 200 with invalid JSON is classified as a transport failure and can
advance to a paid fallback, contrary to the intended malformed-response policy.

**Evidence:** `invalid_safety_answers` produced a `message` decision with unparseable privacy and
sensitivity values both becoming `0.0`. `invalid_json_spends_fallback` advanced a simulated bad
HTTP 200 response to a paid route. These are protocol failures, independent of model quality.

**Fix:** validate required IDs, requested types, finite numeric ranges, allowed choices and
distributions before composition. Any invalid required answer must yield an explicit protocol
failure and silence. Separate protocol errors from retryable network/status errors. The
[official System One schema](https://docs.typesafe.ai/api/system-one) supplies typed answer
contracts, including the 0–1 probability range.

### 5. The wake ledger confuses scheduling with delivery

[Ambient injection](../../luna/plugins/luna-ambient/__init__.py#L1028) treats the injector's
boolean as delivery success. But
[gateway scheduling](../../gateway/run_inbound.py#L1870) returns true when work is scheduled;
authorization/admission can subsequently return false. Ambient immediately consumes its wake
budget and writes a sent-looking wake row. Generation can also return `NO_REPLY` or fail.
The post-model hook indexes generated speech before the transport confirms delivery, potentially
creating phantom room history after a send failure.

**Evidence:** `scheduled_true_but_dispatch_false` and
`wake_recorded_for_scheduled_silence` reproduced accepted scheduling followed by rejection or
silence while the wake row persisted.

**Fix:** use a correlated lifecycle: proposed → admitted → generated → delivered, with distinct
silent/expired/failed outcomes. Only confirmed delivery owns the sent ledger and outgoing room
history. Keep a separate intent reservation to prevent duplicates while work is pending. Retry
only inside the original relevance lease; avoid repeatedly buying the same judgment. Add a
receipt path without breaking existing callers' scheduling-boolean contract.

### 6. Setup can mark a failed Jev connection ready

[run_wake_test](../../luna/lib/luna_cli/onboarding.py#L499) calls the fail-closed cascade, then
unconditionally marks its returned decision as a successful live test. A caught authentication
failure becomes silence, and Setup describes that as “jev answered.” The saved result is trusted
by the readiness check.

**Evidence:** `setup_reports_failed_judgment_as_ready` simulated HTTP 401; Setup returned
`ok: true` even though its own decision reason contained the authentication error.

**Fix:** success requires an actual successful, schema-valid judgment. A valid silent verdict
counts as success; silence caused by failure does not. Bind readiness evidence to the effective
provider/configuration and credential revision so later edits invalidate stale success.

## Reliability and product gaps (P2)

### 7. Resource controls count logical decisions, not all attempts, and discard unknown-cost usage

One [judgment reservation](../../luna/lib/luna_core/judgement_guard.py) can encompass multiple
retries on multiple routes. The probe exercised **12 HTTP attempts for one guard reservation**.
With three default 20-second routes and four attempts each, timeout-heavy execution can occupy
roughly four minutes plus delays; there is no single end-to-end deadline. Rebuilding the client
each scan also loses route cooldown state when a fallback succeeds.

[Usage recording](../../luna/plugins/luna-ambient/__init__.py#L852) drops successful usage entirely
when USD cost is absent. A successful 100-input/10-output-token response produced zero ledger rows.
The dashboard's reported-cost brake cannot then account for that usage. Its reported-cost label
must remain explicit; it is not a provider billing ceiling. The
[official response examples](https://docs.typesafe.ai/api/system-one) include token usage without
a USD amount, so absence is a legitimate case to handle.

**Evidence:** `retry_attempts_exceed_guard_count`, `missing_cost_discards_successful_usage`.
**Fix:** durable per-attempt metering, a total request deadline, bounded retries and persistent
route cooldowns. Record successes/failures and tokens even when price is unknown; show unknown
cost separately from zero. Paid fallback should be an explicit user choice with visible limits.

### 8. Turning wakes off does not cancel an in-flight decision; stale internal targets can send

[poll_once](../../luna/plugins/luna-ambient/__init__.py#L1197) checks enabled/setup state before
the potentially slow judgment but not after it. A judgment completing after disable can still
inject. The room coordinator's stale-arrival check excludes internal events, so an old wake target
can receive a fresh queue lifetime. The separate ambient stale-scan setting does not establish a
freshness check immediately before delivery.

**Evidence:** `disabling_during_judgment_still_injects` injected after configuration changed to
disabled/skipped. `stale_internal_target_is_admitted` sent a ten-minute-old internal target with
a configured 60-second waiting limit.
**Fix:** carry source time, expiry, message/config revision and cancellation ownership. Recheck
after judgment, before generation and at reaction/send admission. Off cancels pending owned wakes.

### 9. Watching multiple groups is incomplete and can silently stop automatic selection

[Room selection](../../luna/plugins/luna-ambient/__init__.py#L140) uses one explicit room, or
auto-selects only when exactly one Telegram group is allowed. Adding a second allowed group with
no explicit room makes the selected chat empty and scans silently stop. Busy-room checks also
operate before topic selection.

**Evidence:** `adding_another_group_stops_ambient_selection`.
**Fix:** explicit dashboard watched-room/topic controls, fair scheduling and scoped state. New
rooms remain opted out by default. If initial support remains single-room, display that limitation
and require a visible selection rather than silently appearing healthy.

### 10. Other bots can be mistaken for this companion

Candidate filtering, reply labels and last-spoke timing treat generic `is_bot` rows as this
companion. When another bot's messages are indexed, a human's question about that bot's answer
can be discarded as a reply to the companion, and the other bot can reset companion timing.

**Evidence:** `other_bots_are_treated_as_the_companion`.
**Fix:** identify the companion from its trusted own transport ID/reserved identity. A generic
bot flag is neither identity nor evidence that this companion already answered.

### 11. The ambient worker has no plugin-unload cleanup

[Registration](../../luna/plugins/luna-ambient/__init__.py#L1328) starts a daemon worker but
registers no unload callback, although the plugin host supports one. Reload/unload can leave an
old worker running with stale context and permit duplicate scans.

**Evidence:** `worker_has_no_unload_cleanup` started a safely mocked real worker, observed no
cleanup callback and verified it remained alive until the probe explicitly stopped/joined it.
**Fix:** stop/join on unload and gateway shutdown, supervise one worker per active profile/gateway,
and test reloads. Process-ownership detection also deserves an integration check; import-time
gateway flags alone are weak evidence of an active owning gateway.

### 12. Health and calibration evidence can look better than actual operation

[Health](../../luna/lib/luna_cli/api_models.py#L330) infers readiness from log strings. A
resource-guard verdict with no successful model call reports healthy. Last-spoke timing reads
wall-clock time independently of `evaluate(now=...)`, weakening deterministic replay/testing:
the probe expected one minute and observed roughly a year. Replay's permissive timing and
default thresholds further limit its calibration value.

**Evidence:** `health_without_judgment`, `injected_clock_does_not_control_last_spoke_gate`.
**Fix:** structured heartbeat, last successful validated request, route/config fingerprint and
explicit off/pending/paused/exhausted/error states. Inject one clock throughout the cascade.
Then validate timing and judgments on consented, labeled large-room fixtures. The current state
description assumes a private friend group; general public-room suitability remains unproven.

## What to preserve

The architecture is worth keeping: local prefilters, a compact judgment model, deterministic
composition, hard resource controls and ordinary gateway generation. Jev does not author replies
or establish transport identity. Reactions and outage-regex fallback ship off; fresh users can
skip wakes. Dynamic room context already has sidecar/user-message paths, and the gateway remains
the sole Telegram poller. Existing group coordination bounds concurrency and yields to humans.
Repair the seams above instead of adding several planning-model calls to each room message.

Do not loosen wake thresholds, enable reactions or add dynamic room state to the cached prompt
as part of these repairs. “Same decisions as the old fork” is useful regression evidence, but
shared old defects can still pass that comparison.

## Recommended implementation and release order

1. Contain replay routing; unify profile-scoped clients, explicit routes and credential handling.
2. Add strict protocol validation and honest Setup/readiness results.
3. Scope candidate/context/state by room/topic and correct own-bot identity.
4. Add correlated delivery receipts, freshness/cancellation and worker ownership.
5. Meter each attempt, retain unknown-cost usage and expose accurate health in the dashboard.
6. Convert every applicable probe into an ordinary failing-before/passing-after regression;
   extend deterministic replay with multiple rooms/topics, other bots, outages and shutdowns.
7. Run a disposable real Telegram/Jev trial for delivery failures, edits, overlapping replies,
   restarts, late judgments and calibrated wake frequency. Provider authentication and current
   endpoint compatibility require this live test; this audit did not prove or disprove them.

Separately, release still needs real memory derivation/recall quality checks, clean advertised-OS
installation/reboot/permission tests, an unassisted onboarding rehearsal, and versioned public
downloads/signing/publication. See [release readiness](release-readiness.md). The existing packaged
candidate predates these audit findings and does not contain their remediation.
