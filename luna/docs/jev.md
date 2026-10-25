# jev (TypeSafe System One)

How the harness uses jev, and the design rules it follows. Source: <https://docs.typesafe.ai>.

## What jev is

A **System One** model: it does not generate text. You send a `state` plus typed `questions`, and it
returns typed `answers` with probabilities (and confidence for Choice/Score) that code branches on.
Every question is evaluated **independently and in parallel** against the same state, so batching many
atomic questions into one call is cheap and barely slower than one.

## API contract

```
POST {base_url}/systemone
Authorization: Bearer <key>
Content-Type: application/json
{ "state": <string|object|array>, "model": "...", "questions": { "<id>": <question>, ... } }
→ { "model": "...", "answers": { "<id>": <answer>, ... }, "usage": { input_tokens, output_tokens } }
```

- `questions` is a **map keyed by id** (the API rejects a list).
- `state` can be a string **or structured JSON**; the docs recommend named fields for most requests.
- Errors: `401` bad key, `422` validation, `429` rate limit, `529` overloaded → retry with backoff.

### Question types

| Type | `criteria` | Answer |
|---|---|---|
| `noul` | optional map `{"true": ..., "false": ...}` | `noul` (0–1). No confidence. |
| `choice` | map `{option: description}` (≤255) | `choice`, `probabilities`, `confidence` |
| `score` | ordered array of 2–10 level descriptions | `score` (probability-weighted float), `legend`, `probabilities`, `confidence` |

> Gotcha we fixed: `noul` criteria keys are **`true`/`false`**, not `yes`/`no`.

## Backends

- **OpenCode Zen** (default): `https://opencode.ai/zen/v1/systemone`, `OPENCODE_ZEN_API_KEY`,
  models `jev-1.13` / `jev-1.13-free`. Free tier is zero-retention (not in Zen's data-use exceptions).
- **TypeSafe direct**: `https://api.typesafe.ai/v1/systemone`, `TYPESAFE_API_KEY`, model `jev-latest`.
- **Local self-hosted** (optional middle route): any System One-compatible endpoint on this
  machine — CLM (`:8700/v1`) or Laya/edgejev (`:8009/v1`). The user downloads and runs the model
  themselves; the harness only points `base_url` at it. Setup and measured limits:
  skills `luna/local-jev` (operation) and `luna/jev-mechanics` (decision machinery). Benchmark:
  `luna/local-jev/README.md` — free/private fallback quality, **not** hosted-Jev parity yet.
- **Fallback chain**: `luna.ambient.jev` is hermes-style swappable — a named `providers`
  registry plus an ordered `route` list of registry names (first entry is the primary; the rest
  are fallbacks). Reorder the list to reprioritise, rename to swap a route, add a provider and
  slot it anywhere; entries may also be inline dicts (legacy `fallbacks:` lists of
  `{provider, model, base_url?, api_key_env?}` still resolve, and may name registry entries too).
  The shipped `route` is **`[zen-free]`**. Add a configured local or paid destination explicitly
  in Behaviour to enable fallback. Empty/invalid routes stay silent; no hidden hosted route is
  constructed. All routes use the same profile-scoped key resolver, including Setup. No
  `api_key_env` means no Authorization header. A malformed response never spends a fallback.
  Successful fallback selection persists for a short cooldown instead of retrying the failed
  primary on every scan. `LUNA_JEV_*` overrides apply consistently to Setup and runtime.
  Provider `endpoint`, `instructions`, `timeout_seconds` and `tier` are preserved.
- **OpenRouter specifics** (verified live): the model is `typesafe/jev-1.13`, served by provider
  `TypeSafe`, on `POST https://openrouter.ai/api/alpha/decisions` — *not* `/systemone`, and
  `/chat/completions` explicitly refuses it ("is a decisions model"). Every question needs an
  `instructions` field that TypeSafe-direct does not require. Responses are the same shape, so the
  tuned thresholds carry over.
- **Metering**: OpenRouter returns `usage.cost` in USD per call. Every HTTP attempt is reserved against the durable attempt limit, including retries and failed
  requests. The configured timeout is a shared operation deadline (maximum 60 seconds), not a
  fresh allowance for each route. Successful usage is retained even without a reported USD price;
  the dashboard labels unknown-price calls rather than implying they cost zero. Records include the route
  (`free` / `local` / `paid` — see *Cost class* below), tokens and true cost into the `jev_usage`
  table — see the Behaviour page's Cost panel.
- **OpenCode Go does NOT serve `systemone`** — a Go key will not work here.
- Cloudflare fronts `opencode.ai` and returns `403` (error `1010`) to urllib's default User-Agent; we
  send an explicit UA.

## Confidence

Choice/Score answers carry `confidence` ∈ [0,1] derived from the probability spread (peaked → high).
Noul has none — use the probability directly. The documented pattern is three paths: **high → act,
medium → caution, low → don't act**, with thresholds scaled by risk. We apply this to the emoji pick
(`reaction_min_emoji_confidence`, currently 0.35); the message/directed tiers gate on the noul
probabilities instead, because the old `best_action` choice returned `silent` on ~98% of real
messages and its confidence gate made those tiers unreachable.

## Jaggedness (jev-1.13) — and how we design around it

| Failure mode | Our response |
|---|---|
| Literal reading | Write exact conditions; put boundary cases in criteria. |
| Math/counting/numbers | Keep arithmetic in code — the composite is ours, not the model's. |
| Date/time comparison | Never ask jev to compare times; timing is a Score, arithmetic is code. |
| **Ask about the social consequence, not the topic** | "Does this involve something sensitive (health, money, conflict, grief)?" rated a dark joke AND a hospital crisis both at 0.93-0.98. Reworded to "would a reaction be unwelcome because someone is genuinely upset?" — joke 0.13, real crisis 0.79. The room's register is stated in the `room` block so jev reads bleak statements as the jokes they are here. |
| **Private is not the same as personal** | The private question asks whether information is likely intended to stay private. Ordinary achievements, family plans, preferences, and casual updates should not be gated as private. |
| **Ask whether it means something, not whether it could** | The `reaction_would_fit` wording "would a reaction be a fitting response" is satisfied by *any* attachable message. Reworded to ask whether the reaction would actually say something: `Beep` 0.84 → 0.06, a real joke 0.88 → 0.73. |
| Stricter wording can silently starve a gate | Tightening `has_open_question_luna_can_answer` to "unanswered *and Luna can answer it*" dropped real questions (`Weren't we at 29 members?` 0.86 → 0.38), which would have broken the reaction-yield rule that keys off that score. Reverted — A/B before shipping. |
| Score lands between levels | A Score is probability-weighted and rarely lands exactly on a level (live "just right" = 1.07–1.17). Never gate on `score == level`; gate on a band (`timeliness_center ± timeliness_band`). |
| Indirection / multi-hop | **Atomic questions only** — we split "redundant or late", "sensitive or private", "emotional venting". |
| Large state, irrelevant detail (context rot) | Send a **bounded structured state**: candidate + a trimmed recent window. |
| Adversarial content | State is data; group text could try to steer. Be explicit; test edge cases. |
| Contradictory instructions/criteria | Criteria are an extension of the instruction, aligned. |
| No structural invariants | Never assume `P(not x)=1−P(x)`; never reuse a Noul threshold on a Choice. |
| Generation | Jev never writes the companion's reply; it only judges whether and how the companion should respond. |

## How Luna uses it

Two ways she can speak unprompted — plus reactions:

- **Directed (semantic trigger).** jev's `addressed_to_luna` decides whether a message is aimed at
  Luna even without a formal Telegram mention (e.g. "luna what is X"). This *replaces the literal
  "luna" word regex* with a semantic judgment. Formal mentions and replies-to-Luna stay deterministic
  and are marked `triggered` by `luna-room`, so the ambient layer never double-answers.
- **Ambient self-wake** — a rare, well-timed interjection (silence by default).
- **Reaction tier** — a low-key reaction instead of a message.

Pipeline:

1. **Stage 0** — cheap universal filters (free): not a formal mention/reply, not a bot, not already
   acted on (dedup), substantive. The ambient timing gates ("enough new messages", "Luna hasn't
   spoken too recently") are **not** here — they would block a directed reply, and we can't know a
   message is directed until jev answers. They apply to the ambient message branch only (Stage 2).
2. **Stage 1** — one batch of atomic questions over the bounded structured state.
3. **Stage 2** — deterministic composition (thresholds live in `luna.ambient.thresholds`, all
   tunable from the Behaviour page; the defaults in `luna_core.cascade.CascadeConfig` are the single
   source of truth):
   - `reaction` if the message **explicitly asks for a reaction** (`requests_reaction ≥ 0.70`) and a
     valid allowed emoji is available — this outranks the directed reply, because the human asked for
     a reaction and answering in words is wrong. A literal emoji named in the text (e.g. "React with
     👍") wins over jev's pick (code, not model).
   - `directed` if `addressed_to_luna ≥ 0.70`, where `addressed_to_luna` is **composed in code** as
     `max(named_luna, directly_addressed)` from two atomic judgments (docs: don't hide several
     judgments in one question). A high sensitive/private safety score (≥ 0.60) still stops the wake;
     the semantic judgment alone must not override the safety gate. Formal Telegram mentions never
     enter this ambient batch. A message that merely *names* her with nothing to answer
     (`open_q ≤ 0.50`) may downgrade to a reaction when one clearly fits.
   - ambient `message` if `message_would_fit ≥ 0.42` + `value ≥ 0.60` + just-right timing
     (`|timeliness − 1| ≤ timeliness_band`, i.e. a band, since Score lands between levels) + the
     ambient timing gates (enough new messages, Luna hasn't spoken too recently) + not
     sensitive/private/venting.
   - `reaction` if `reaction_would_fit ≥ 0.66` (its own judgment) + `value ≥ 0.35` +
     not sensitive/private + an allowed emoji + `reaction_would_feel_fresh ≥ 0.43` — but a genuine
     open question (`open_q ≥ 0.55`) that Luna could answer yields to words.
4. **Stage 3** — no code cap by default (jev decides frequency); dedup always prevents acting twice on
   one message. The reaction cooldown (`luna.ambient.budget.reaction_cooldown_minutes`, 15) is the
   one deliberate code-level brake.
5. **Stage 4 ordering** — the wake row is written only **after** delivery is confirmed. Dedup keys on
   `wakes.trigger_message_id`, so recording before delivery would permanently skip a message whose
   send failed (rolling back the evaluation watermark could not re-surface it).

## Reactions

The tier is **off** unless `luna.ambient.reactions.allowed` is set (an absent or empty list means no
reactions — silence is the default). The palette used in the room:

| Emoji | Meaning |
|---|---|
| 👍 | agreeing with a serious point |
| 🤣 | a deliberate joke / genuinely funny |
| 😭 | unhinged, chaotic, or ranting; the versatile, most-used one |

`reaction_would_feel_fresh` gets a code-computed summary of Luna's recent reactions
(`luna_recent_activity`) and judges repetition — jev decides freshness; it is never asked to do time
math. Thresholds are tuned on real history with `luna/tools/jev_replay.py`.

## Context budget

jev-1.13: **64k tokens per request, 32k for `state` + the longest question**. We send far less — a
bounded structured state (default ~8k chars ≈ 2k tokens): the candidate, the last ~20 messages with
**reply edges preserved**, a short Luna blurb, and `luna_recent_activity`. The docs warn that
unrelated state causes context rot, so relevance beats volume; the window is trimmed oldest-first to
fit the cap.

## Changing a question

Question wording matters more than any threshold. Verify a change against real room messages
before shipping it — a stricter question can silently starve a gate whose threshold was tuned
against the old calibration.

```bash
python luna/tools/jev_ab.py --db ~/.luna/luna-state.db --limit 20 \
  --old "current wording" --new "candidate wording"
```

Both wordings are asked in one request per message, so a comparison costs one jev call per message.

## Operator tooling — the Behaviour page

Watch verdicts and tune thresholds from `luna dashboard` → **Behaviour**. Timestamps are Tehran
local time. The feed shows messages bypassed before jev, settle-gated candidates, and the verdicts
for each ambient message wake — **ids, reasons, and weights only**. Message and reply text is never
written to the log (PRODUCT_PLAN P5, privacy): the wake story is tuned from the scores, so the log
does not need the room's words. The feed also carries a health strip (gateway, jev, wake totals),
the wake ledger, cost per route, and the threshold sliders with their code defaults. Log retention
(`luna-log-retention.timer`) truncates the active files on a schedule.

Threshold edits rewrite the `luna.ambient.thresholds` block in place
(`luna_core.configedit`), so comments and ordering survive; unknown keys are rejected, values that
would make the YAML invalid are refused, and the health strip flags jev being rate-limited (the
usual reason Luna goes quiet). The what-if replay button re-decides recent history offline and
sends nothing.

The `luna tune` CLI that used to back this panel is retired (P5); `luna_cli/tune.py` survives only
as the read/write library behind the page, and its tests.

## Rate limits

`jev-1.13`: 250k tokens/sec, 1200 requests/min. **`jev-1.13-free` is far more restricted** and
returns `429 FreeUsageLimitError` under load (our replay/tuning runs exhaust it). The client retries
`429`/`529` with backoff; the live tests skip on `429`. A jev failure fails closed (silent) and does
not advance the watermark, so the message is retried once the quota returns. For heavy use, switch
`LUNA_JEV_MODEL=jev-1.13` (paid: $0.042/1M input, output free).


## Cost class in the verdict stream

The Behaviour page's verdict feed shows `via=free|local|paid` — the **cost class** of the route that answered,
not the internal route name. `FallbackJevClient` carries a tier per route
(`luna_core/jev.py::route_tier`): an explicit `tier:` on the provider entry wins; otherwise it is
inferred (loopback/private host → `local`; `free` in the model/provider/base_url → `free`; else
`paid`). With the shipped chain that reads `free` for zen, `local` for a self-hosted CLM/Laya, and
`paid` for TypeSafe/OpenRouter. A bare (no-fallback) client is classified from its model/base_url.

## Tests

- Unit: request shape, `true/false` normalization, legend parsing, composite math, confidence gate.
- Component: dry-run vs record, candidate selection.
- **Live** (`luna/tests/component/test_jev_live.py`, needs `OPENCODE_ZEN_API_KEY`): a single question
  and the full 12-question batch, both parsed and composed end-to-end.


## Public-room audit remediation

The [ambient/Jev audit](ambient-jev-audit.md) now has deterministic regression coverage. Runtime
scans, watermarks, context and parent joins are scoped to a watched group/topic. Select watched
groups in Behaviour; a new group never opts in automatically. Other bots do not acquire the
companion’s identity. The worker starts/stops with its actual gateway owner and plugin lifecycle.

A wake has a separate pending reservation and transport receipt. Only successful delivery updates
the sent-wake ledger and outgoing room history. Silence, rejected admission, expiry, cancellation
and transport failure do not count as speech. Configuration/source edits and the original source
age are rechecked before generation, delivery and retries. Pending intents suppress duplicate
judgments, and no target is redirected to a different room or person.

What-if replay uses stored, scoped scores; it makes no network requests and exports no transcript.
It recomposes thresholds, not historical timing, admission or provider semantics. Model judgment
quality in large public groups still requires real-world calibration; thresholds and default
silence have not been loosened.
