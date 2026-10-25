# Luna threat model (P6 hardening pass)

Scope: the two surfaces a Luna deployment actually exposes — the **dashboard** (loopback HTTP API +
SPA) and the **Telegram group/DM chat surface**. Self-hosted, single operator. Updated after the
approved system-audit remediation; see `audit-remediation.md` for validation and release limits.

## Trust boundaries

| Boundary | Who is on the other side | Assumption |
|---|---|---|
| Dashboard socket | anyone who can reach the port | on loopback, that means any local uid |
| Dashboard, gated | any network caller | behind the OAuth gate, mandatory off-loopback |
| Group chat | **every member of a watched group**, including hostile ones | text is fully attacker-controlled |
| Owner DM | exact configured transport owner id | full assistant capabilities |
| Other DM | any admitted non-owner | narrow capabilities, no owner-private memory |
| Model provider | the configured route chain | sees prompts; listed on the Behaviour page |
| Host filesystem | local processes | DBs are `0600`; `.env` is untracked |

Two facts shape everything else:

1. **Group text is attacker input.** Anyone in the room can send arbitrary text, including a
   display name of their choosing. Anything derived from group text is untrusted data, never an
   instruction.
2. **On loopback, the session token is readable by any local user.** The SPA embeds
   `__HERMES_SESSION_TOKEN__` in `/`, and `/` is not behind the `/api/` gate — that is the
   engine's long-standing loopback trust model, not a Luna change. So "local unprivileged user" is
   a real attacker here, equivalent in reach to a token holder.

## What was fixed in this pass

**Retention was only half-enforced.** `luna.data.retention_days` shipped in the template and
`install.sh` installs a daily `luna-data-retention.timer` that runs the pruner — but that was the
*only* enforcement path. A deployment that never ran `install.sh`'s systemd setup (manual gateway
start, a container, a second gateway process) had none, and even where it existed the transcript
could sit unpruned for up to a day. `luna_core.retention.enforce` now also runs in-process, from both
indexer loops (the gateway thread and the standalone `luna-logger/run.py` runner), bounded by
`luna.data.auto_prune` + `auto_prune_interval_minutes`, which are honoured by the CLI path too so
the two agree. Fail-soft by construction: it never raises and never blocks indexing. An unreadable
config now *skips* the pass rather than falling back to the shipped 1-day default, so one bad read
cannot delete a month of history.

**The observe switch was invisible.** `telegram.observe_unmentioned_group_messages` ships **on** and
is the widest thing Luna stores, yet it was absent from the dashboard schema — raw YAML only, which
AGENTS.md §6 forbids. It is now a first-class Config field, described in terms of what turning it
off costs (she stops being able to chime in unprompted).

**Untrusted room text could reach the system prompt.** If the private sidecar seam was
unavailable, `luna-room` concatenated the room block into `event.channel_prompt` — system-level, and
inside the cached-agent signature (invariant 1). An exception in the safe path promoted attacker
text into the highest-trust slot. Now it fails closed: no seam, no room context that turn.

**Group output shaping failed open twice.** An unrecorded session (cold cache, or FIFO eviction
past 512 entries) returned the reply *unshaped* — no redaction, no line cap. And the exception path
kept only the line cap, so a broken pipeline still shipped personal details. Both now fail closed:
unknown surface shapes as `group` (over-shaping a DM costs emoji; under-shaping a group leaks other
people's details), and the fallback re-applies redaction and markdown stripping.

**Dashboard cost and CSRF edges.** `/replay` (600s subprocess) and `/onboarding/honcho/up` (660s
`docker compose up --wait`) had no rate limit; `/verdicts/stream` capped nothing while holding a
file handle and a task per connection; `/peers/sync` took no request body, leaving `SameSite=Lax` as
its only CSRF control. Added per-endpoint limits, an 8-connection SSE cap, and a JSON
content-type guard. Also: the router now carries a `_require_token` dependency so all 22 routes have
a second auth layer behind the middleware, and the auth contract test derives its route list from
the router instead of hand-maintaining it (which is how `/verdicts/stream` came to be the one route
with no assertion).

**Injection hardening detail.** The room block rides the ephemeral sidecar as user-role context.
Two things make that safer: the overlay now has a contract test asserting that *no* plugin under
`luna/plugins/` assigns to `channel_prompt` (detected via the AST, so a docstring mentioning it is
not a false positive), and `redact_personal_details` no longer runs a quadratic regex —
`transform_llm_output` is timeout-bounded, and a hook that times out is discarded, which would ship
the *raw* reply, so injected long digit runs were a genuine denial-of-service on the privacy
control. Redaction now runs in whitespace-aligned slices (60k digits: 13.1s → 0.9s).

**Smaller engine fixes.** `_has_valid_query_token` compared against the import-time token while the
header path used the env-overridable one, so the two disagreed about which token was live. The SPA's
session export sent `X-Luna-Session-Token` while the server reads `X-Hermes-Session-Token`, so
loopback export always 401'd. The injected token was interpolated into HTML unescaped (an
operator-supplied token containing `</script>` could break out).

## Current capability, memory and wake boundaries

- Groups default to the configured web toolset. Host tools require the explicit dashboard
  `luna.access.group_host_access` opt-in. Only exact configured owner transport ids receive full
  DM tools. Privileged slash commands remain owner-gated even with an empty owner list.
- Exec and slash-confirm buttons use the privileged sender gate. A watched chat alone does not
  grant its members approval rights. Disabling operator routing changes the destination, not
  approver authorization. The earlier version of this document incorrectly conflated the two.
- Group recall uses the indexed public messages of that room. Owner `MEMORY.md`, `USER.md`,
  workspace context files and bundled Honcho DM recall are not loaded for groups or visitor DMs.
  Persona remains shared character configuration. Group streaming/interim output is suppressed;
  final text passes code-enforced privacy, line and UTF-16 size limits.
- Self-wakes ship in dry-run mode, reactions disabled and mention fallback empty. Unlimited daily
  preferences use explicit null values; an independent hourly delivery ceiling and judgement
  attempt/reported-cost guards still apply. Quota failures consume attempts. Stage thresholds
  were not loosened; replay fixtures cover Unicode content and flood/outage behavior.
- Per-turn room text remains untrusted user-role context. Transport ids determine identity;
  display names and model statements cannot change registry ownership.
- Companion API requests, settings transactions, downloads, model credentials and background
  workers use the selected profile's home. Writes share the engine's thread/process lock;
  multi-file settings commits have a recovery journal and stale revisions are rejected.
- The durable room-delivery ledger holds uncertain sends for remote reconciliation. Failed
  lookups never become permission to resend blindly. Dashboard retry warns about the remote
  service's eventual consistency and duplicate risk.

## Operational limits

The dashboard remains an operator interface with host authority. Its authenticated provider URL
configuration intentionally supports private endpoints, including the local memory stack. Do not
give its session token to group members. The inherited loopback local-user trust model above is
unchanged.

Retention defers active native workers, active engine sessions and unprocessed memory work;
the dashboard reports coverage rather than claiming every raw source disappears at an exact
deadline. Derived memories and identity persist until explicitly deleted. Backups contain private
configuration and credentials and are published with mode 0600.

Restores require stopped gateways and idle native workers, create a safety backup, use transactional
Postgres restore and roll back caught local publication failures. Filesystem and Postgres cannot
share one atomic transaction: a host crash between them requires restoring the safety backup.
For a single point-in-time backup, stop writers first; live SQLite backups are individually
consistent, while ordinary files are captured separately.

## Regression-gated invariants

Identity from transport ids only (`luna_core/identity.py`; `upsert_auto` never re-keys and returns
early on manual rows; the in-band `[name|id]` prefix is used only when it agrees with the transport
id). Constant-time token comparison on all three paths. Host-header/DNS-rebinding validation. Loopback
binds by default; `0.0.0.0` always engages the OAuth gate with `SystemExit` fail-closed and `--insecure`
neutralised. `HttpOnly; SameSite=Lax; Secure` cookies. Authz default-deny with `GATEWAY_ALLOW_ALL_USERS`
as the only escape. Telegram error/send paths wrapped in secret redaction. Subprocess boundaries use
argv lists; managed database maintenance runs a fixed script inside the private container with no
user-supplied shell interpolation. Skin-name allowlist before path construction. All
SQL parameterised. Comment-preserving config writes re-validated with `yaml.safe_load`. Budget clamps
are hard enforcement. Verdict/wake logs never reach a group and never carry message text.
