# Native OpenCode engine

In **Setup → OpenCode (free models)** or **Models → OpenCode free models**, install the engine if
needed, choose a live catalog entry, press **Test model**, then **Use this model**. Chat requires no
API key. The main provider is `opencode-engine`; a selected model retains its native identity, for
example `opencode/big-pickle`. The direct Zen/Go API providers are still separate choices.

OpenCode's [official harness documentation](https://dev.opencode.ai/v2/docs/console/harnesses/)
states that free-tier chat models are available inside OpenCode and return 403 to other harnesses.
This integration uses the actual native engine, rather than changing HTTP headers on API requests.
The [model catalog](https://opencode.ai/v2/docs/models) is dynamic; identifiers and quotas can change.

## Ownership and safety

- OpenCode owns inference, its native session history and native compaction. Luna runs the ordinary
  turn prologue and finalizer, so persona, transport-derived identity, bounded recall, room output
  transforms, post-turn indexing, cleanup and memory synchronization remain in their existing paths.
- Each profile has a private `opencode/` runtime tree. The child gets a separate HOME/XDG tree and
  an explicit OS/network environment allowlist. Luna's keys, bot token, the operator's OpenCode
  credentials/configuration, native plugins and unrelated project MCP servers are not inherited.
- The local server binds only `127.0.0.1`, with a random Basic-auth password per process. Its SDK
  traffic bypasses proxies; cloud networking retains configured proxy and CA settings.
- The authenticated loopback MCP bridge exposes exactly the current Luna tool schemas. HTTP workers
  enqueue requests; the owning conversation thread uses the existing Luna tool dispatcher. Its
  normal approval context, hooks, cron restrictions, result budgeting and persistence guard apply.
  A tool-call row must be durable before execution. Bridge calls require the active native session
  id and reject browser Origins. Native shell/filesystem/subagent requests are refused, including
  in yolo mode; native forms are cancelled. The bridge is configured before native startup, and
  its catalog must be connected and served before prompting. This prevents a cold-start race that
  could omit Luna's tools from the first inference request.
- Stable Luna instructions are sent once for each native session. Dynamic room/recall content stays
  in the current user payload. A committed native binding is stored alongside the Luna session only
  after successful finalization. Resume requires matching prompt/tool/model composition and a digest
  of the canonical transcript. Changed/compacted history seeds a fresh native conversation. Missing
  or relocated committed native sessions are recoverable before prompting; failed or interrupted
  turns are never automatically replayed.
- Every inference call rechecks public-route identity and **all** advertised price tiers: input,
  output, cache read and cache write must be explicit numeric zeros. Missing prices, paid routes and
  zero-cost subscription allowances are excluded. The main native path has no paid fallback.
- Titles and compression use the same native model when their auxiliary provider is Auto. Explicit
  auxiliary provider settings remain separate. Native probes and auxiliary sessions are temporary.
  Image inputs use explicit attachments; message-provided `file://` URIs are rejected. Native
  streaming is buffered until completion so interim planning text cannot become a group reply.
- Honcho reasoning/embeddings and Jev's system-one wake protocol remain separately configured.
  Native free chat does not make these external services free or replace them.

## Context contract

| Source | OpenCode receives |
|---|---|
| Profile SOUL/persona, cached Luna system prompt | Native session instructions, preserving the normal Luna prompt builder. |
| Gateway channel/surface policy and configured system/developer priming | The same native instruction prefix; changing these invalidates the native binding. |
| Room roster, transport-derived identities, reply chains and gateway notes | Current user-message text, through the normal one-shot sidecar. |
| Memory recall and `pre_llm_call` plugin context | Current user text, with the normal memory fence and a durable text sidecar. Image turns retain both this text and their attachments. |
| User/assistant priming and earlier conversation | Seeded once as quoted history on a fresh native conversation; the native session retains it on resume. |

The native binding hashes the instruction/tool/model/priming composition and the canonical history.
Replay cleanup runs before matching, so expired dangerous confirmations cannot silently survive in a
resumed native session. A changed or compressed transcript seeds a new conversation. SQLite's
intentional image-to-text projection can resume an existing native session only when the stored
transcript exactly matches the expected durable projection; original image attachments remain in the
native session. A fresh seed after native history is lost has only the text/image placeholders
retained by the engine's canonical transcript.

`scripts/verify_opencode_context.py` inspects the actual model requests emitted by the real OpenCode
binary against a local fixture. Four turns cover persona/channel/priming placement, fenced recall,
plugin/room notes, a real image attachment, fresh agent/process restarts, byte-stable resumed user
and system prefixes, and a new history seed. CI runs it without cloud credentials or model quotas.

A live `openai/gpt-6-luna` check also returned five random codes injected separately through the
profile persona, channel policy, memory provider, room sidecar and plugin hook. The user question
contained none of the codes. All five matched in one inference step. This used the existing native
login only for the isolated test; the selected model remains an invocation parameter.

## Installation and distribution

The recommended runtime is OpenCode **2.1.2**. Tested API versions are 2.0.30–2.1.x; incompatible
versions are not adopted. Setup can reuse a compatible installed binary. Otherwise it downloads a
pinned official npm release, verifies its SHA-512 digest, extracts only the regular executable,
checks its reported version, and atomically publishes it under the profile. It never overwrites a
running binary. Linux glibc/musl, x64 baseline/arm64, macOS and Windows release targets are recorded;
the fresh-install execution test currently covers Linux glibc x64. Luna's shell installer remains
Linux/macOS-oriented. OpenCode is downloaded on demand, not embedded in Luna's release archive.

The core native integration is a Python adaptation of Xratu's OpenCode engine at
`f68ef5492518f4c9325816b368c20369080860f2` (Apache-2.0), including inherited T3 Code lifecycle
patterns (MIT). This rewrite adds profile credential isolation and routes all capabilities through
Luna's guarded tools. Full attribution and licenses ship in
`luna/lib/luna_core/OPENCODE_NOTICES.txt`; package data also includes the pinned release manifest.

## Verification

The isolated native 2.1.2 server returned ten public zero-price tool-capable models without keys.
The actual engine connected to Luna's authenticated MCP bridge. A fresh download passed the pinned
checksum, executable extraction and version check. This test caught and fixed a libc detection bug
on glibc systems with an optional musl loader installed.

All ten public free routes were checked. Eight returned **“Free usage limit reached”**; one was
deprecated and one was no longer available as free. The dashboard reports these failures without
completing a successful probe or falling back to a paid provider. Public free-model availability
remains controlled by OpenCode.

An explicitly authorized live test used the operator's existing OpenCode ChatGPT login and the
operator-selected `openai/gpt-6-luna` model. Through the actual OpenCode binary and Luna conversation
loop, it called Luna's guarded `read_file` tool and returned the exact synthetic file marker in two
inference steps. The file was unchanged. The model was a test argument, not a product default;
the product's isolated free-only setup does not inherit that login.

`scripts/verify_opencode_native.py` repeats the complete native-engine/MCP/tool/finalizer round trip
against a local deterministic model endpoint, without cloud credentials or quotas. It also asserts
that Luna's tools are present on the first inference request. CI installs the verified binary and
runs this check. An optional `--model provider/model --use-native-login` invocation explicitly tests
an existing native login without copying credentials or changing Luna configuration. No Telegram
token, personal chat history or legacy gateway was used in these checks.

Deterministic tests exercise real Luna conversation construction, session persistence/resume,
dynamic user sidecars, guarded file-tool dispatch/approval, fail-closed persistence, group output
shaping, cancellation, native SSE/protocol errors, free-price eligibility, model selection/auth,
verified installation and the frontend install/probe/save flow. The release smoke test verifies
installed native imports and packaged notices after deleting the unpacked source.
