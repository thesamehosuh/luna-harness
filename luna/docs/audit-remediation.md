# Audit remediation

The user approved the system audit findings and proposed product changes. This records the
implementation in the standalone checkout, including the additional dashboard-chat startup gap.
No production gateway was restarted and no release was published. The original fork was not edited.
The test-isolation incident below affected the default engine home and must not be omitted from
the handoff.

## Implementation checklist

- [x] F1: scoped companion API, config, secrets and background workers; two-profile regression.
- [x] F2: complete memory lifecycle adapter and shared Honcho connection settings.
- [x] F3: durable oldest-first delivery, idle retries, uncertain-send reconciliation and health.
- [x] F4: explicit unlimited budgets, atomic validation, independent hourly loop guard and replay.
- [x] F5: engine/shared settings lock, staged recoverable multi-file changes, revision conflicts.
- [x] F6: store inventory, native/session/attachment retention, managed Honcho maintenance, backup.
- [x] F7: immutable staged code/environment, atomic publication, prior release rollback, WAL backup.
- [x] Group capability and room/private memory boundaries, dashboard owner opt-ins.
- [x] Authoritative character identity/language/style, bounded group message delivery.
- [x] Dated revision-bound readiness, degraded reactive chat, actual memory data-path checks.
- [x] Identity omitted/present-null semantics through the real API.
- [x] Native resource guard, catalog cache, declared auxiliary option support and context pressure.
- [x] Product release identity, supported-platform CI, failure-injection and integration evidence.

## Behavior changes

Groups receive web capabilities and public history from their own room. Owner-private file memory,
workspace context and external DM recall do not enter group or visitor-DM agents. Owners are exact
configured transport ids. Empty owner lists cannot open privileged slash commands. Broader group
host access is an explicit dashboard option. Group streaming/interim text cannot bypass final
privacy, line and UTF-16 size enforcement. The configured language defaults to auto; the optional
English setting uses a deterministic non-Latin-script filter, not a semantic language detector.

Character, Behaviour and threshold writes validate before publication. SOUL, skin and YAML changes
share the engine's lock, have a recovery journal, and support revision conflicts. Explicit null
identity fields clear values while omitted fields preserve them. Character names and aliases flow
into wake questions, prompts and chat presentation; shipped Luna text remains an example persona.

Room delivery now drains every indexed message oldest first. A committed ledger survives restart;
unknown send outcomes are held until remote reconciliation. Missing lookup results do not permit
blind resend. Idle indexer passes retry backlogs without another Telegram poller. The System panel
shows pending age, held sends, retention coverage, dated verification, backups and rollback.

Memory lifecycle hooks reach the bundled backend and its invalidation signal contributes to the
signature. All memory paths use one profile connection resolver. Recall waits are bounded and a
stalled backend cannot spawn unlimited workers. Reactive chat remains available while memory is
degraded. Readiness distinguishes configuration from actual verified operations and expires after
configuration changes or age.

Daily wake preferences use explicit null for unlimited; independent hourly delivery and judgement
attempt/reported-cost guards remain enforced. Shipped dry-run and disabled reactions remain.
Mention fallback now requires explicit configuration. Unicode content passes the substantive-text
prefilter; recorded replay fixtures cover outage and flood behavior without loosening thresholds.

Native workers reserve cross-process memory slots, hold session leases and use separate owned raw
stores. Retention handles those stores, older shared stores, image snapshots, canonical ended
sessions and expired backups. Managed Honcho pruning runs inside its private database/cache
containers from the indexer as well as the optional timer.

Upgrades construct immutable code, dependencies and managed Node at their final release path before
publishing the active pointer. Failures leave the previous runtime selected. Previous-release
rollback checks data-schema compatibility and snapshots current local state. SQLite snapshots
include committed WAL data in primary and child profiles. Engine upstream updates are refused.

## Every launch path must enter Luna

The reported dashboard bug was deeper than a label. The embedded terminal inherited a Hermes TUI,
interpreter, source path, model arguments and working directory. Fresh named profiles could also
receive the engine persona and omit companion plugins; default bootstrap could mint an upstream
vendor account despite the selected Luna model.

The distribution manifest now controls default home, product version, companion bootstrap and
child launch paths. Dashboard chat/actions and generated gateway services bind to the installed
Luna code, interpreter and selected profile. Stale inherited Hermes source/TUI/model paths cannot
win. Fresh profiles get companion defaults and distinct memory workspaces. Customized SOUL files
are preserved; only the exact untouched engine default is migrated. No implicit vendor account
is created. Explicit empty tool selections stay empty. The chat TUI is bundled, and installation
fetches a pinned checksum-verified Node executable without needing npm at runtime. Character
renames refresh the chat identity. Chat update guidance points to the dashboard.

The real browser test used a synthetic Nova character and a local OpenAI-compatible fixture.
Typing into `/chat` produced `LUNA_DASHBOARD_CONTEXT_OK` only when the inference system text
contained that profile's marker and Luna runtime guidance, with no engine identity. The maintained
`scripts/verify_dashboard_chat.py` also checks stale inherited paths through the real terminal UI
and Python child.

## Validation

Use the Python 3.11 scratch environment at `/tmp/luna-release-audit.yp17cW/locked/venv/bin/python`
with the current checkout first on PYTHONPATH. Never use its editable installed source as evidence
for this tree. Synthetic homes and local providers only unless a live test is explicitly identified.

The previous audit evidence remains under `/tmp/luna-system-audit`. New regression tests assert
repaired behavior rather than preserving the old probe outcomes.

| Gate | Evidence |
|---|---|
| Companion unit/component/contract/replay + gateway subset | `/tmp/luna-final-suite.log`: 673 companion passed, 2 live skipped; 145 gateway passed |
| Full dashboard API subset | `/tmp/luna-final-api.log`: 231 passed; later affected seams `/tmp/luna-final-followups.log`: 237 passed |
| Dashboard frontend | `/tmp/luna-final-web.log`: 558 passing tests |
| TUI type check and targeted behavior tests | `/tmp/luna-final-tui-types.log`, `/tmp/luna-final-tui-test.log`: 133 passing tests |
| Real native tool bridge | `/tmp/luna-final-native-tool.log` |
| Real native four-turn context/resume | `/tmp/luna-final-native-context.log`: all checks true |
| Managed memory stack, local model fixtures | `/tmp/luna-final-memory-integration.json`: write/read, embedding search, derivation, cleanup, backup, private maintenance and restart recall all true |
| Actual dashboard chat | `/tmp/luna-final-dashboard-chat-source.log`, `/tmp/luna-final-dashboard-chat-cold.log` |
| Optional cloud-provider import/behavior regressions | `/tmp/luna-final-provider-imports.log`: 105 passed |
| Release assembly and installed runtime | `/tmp/luna-final-build.log`, `/tmp/luna-final-install.log`: all checks true, including source removal and actual chat without unrelated SDK installation |

Machine-readable results and the candidate checksum are recorded in
[`audit-remediation-results.json`](audit-remediation-results.json). The local candidate is
`/tmp/luna-final-artifacts/luna-0.1.0-alpha.1.tar.gz` (18,422,060 bytes). It was installed under a
path containing spaces with the unpacked source removed before chat was tested. The embedded chat
used its installed Python and managed Node, and received the selected synthetic persona.

The first 45-second installed-chat probe exposed an import-time `boto3` download for an unused
provider. A longer probe confirmed the delayed inference; AWS/Google SDK installation was then
moved to actual use and the rebuilt release passed with no such download. A separate Node transfer
timeout led to resumable, checksum-verified caching, covered by interrupted/tampered-download tests.

The Docker integration made two local chat and 30 local embedding requests. No real API credentials,
cloud inference or Telegram poller were used in these remediation checks. CI now includes these
maintained probes, with Linux/macOS Python 3.11/3.13 portability jobs. Inherited upstream workflows
are archived under `.github/legacy-workflows` and cannot publish engine artifacts accidentally.

## Remaining release limits

- This is an alpha candidate. No live Telegram cutover, public release, off-loopback deployment
  or local macOS execution was performed. Free-route availability and account quotas remain external.
- Retention defers active sessions/workers and pending derivation. Identity and derived memory
  persist until explicitly deleted; these policies are visible in the store inventory.
- Live SQLite backups are individually consistent. Stop writers for a single point-in-time
  snapshot across ordinary files and remote memory. Restore creates a safety backup and rolls back
  caught local publication errors, but Postgres and filesystem changes cannot share one atomic
  transaction. A host crash between them requires restoring that safety backup.
- Keep the old deployment until a separate-bot live trial validates room delivery, wake cadence
  and real memory quality. Deterministic contracts do not promise identical generated wording.

## Test-isolation incident

Early tests changed `LUNA_HOME` without also changing the engine's canonical `HERMES_HOME`. After
unifying those paths, a test overwrote the default `~/.hermes/config.yaml` and created synthetic
memory/index files there. Those files were quarantined privately under
`/tmp/luna-test-home-recovery`; the config was restored from the newest known-good backup
`~/.hermes/backups/config/config.yaml.good.20260926-114906`, mode 0600. That backup may predate the
pre-test config, so this is not a claim of exact recovery. No gateway was restarted.

Collection and every Luna test now get an isolated canonical engine home, and home-specific
fixtures set both aliases. The product default is `~/.luna`, independently of the old engine home.
The legacy fork still has only its pre-existing `luna/docs/memory.md` modification.
