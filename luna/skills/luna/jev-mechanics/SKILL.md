---
name: jev-mechanics
description: |
  How the Luna harness's wake decision pipeline works: the stage-0 prefilter, the structured state, the
  17 atomic questions, the compose() threshold cascade, wake budgets, and the free→local→paid
  fallback chain. Use when asked why the companion stayed silent or spoke, why a wake/reaction did or did
  not fire, when tuning thresholds or debugging wakes/cascade behaviour, when changing questions
  or state shape, or when reasoning about Luna's own decision mechanics and costs.
license: Apache-2.0
metadata:
  version: "1.0.0"
---

# Luna's jev machinery — how she decides to speak

Luna does not "decide to reply" with a language model's chat instinct. Every candidate message
runs a fixed, auditable pipeline; jev answers typed questions, **code** composes the verdict.
This skill is the product's knowledge of its own mechanics. Sources of truth:
`luna/lib/luna_core/cascade.py` (stages + gates), `luna/plugins/luna-ambient/` (poller),
`luna/docs/jev.md` (API + design rules), `luna/local-jev/README.md` (benchmarks).

## The pipeline (one candidate message)

```
observe (group chatter → state.db)  →  luna-ambient poll (~3 s cadence)
  →  Stage 0  prefilter (code, free)
  →  Stage 1  build_state() + 17 atomic questions → one jev batch call
  →  Stage 2  compose() — deterministic threshold cascade (code)
  →  Stage 3  wake budget (code) → deliver → record wake + jev_usage
```

Fail-closed at every step: any jev error, missing answer, or budget veto yields **silent**.
Silence is the default and the product's core temperament (plan D18: self-wakes are rare).

### Stage 0 — cheap code filters (no model, no cost)

Skips: bot authors, formal mentions/replies-to-Luna (the gateway answers those reactively),
non-substantive text (< 3 word-chars; messages naming "luna" bypass this), messages already
acted on, and candidates younger than `ambient.settle_seconds` (10 s — most busy-room chatter
is superseded before it deserves a spend; name-mentions bypass the settle).

### Stage 1 — the state and the questions

State is **structured JSON**, bounded (`state_max_chars` 8000, `recent_lines` 20) and built for
the cache: per-turn dynamic content must never enter the system prompt (it rides this state or
the sidecar instead). Fields: `luna` blurb, `room` register (the dark-humour reading rule lives
here), `recent_messages` (reply edges preserved), `candidate` (the judged message),
`luna_recent_activity` (wake cadence for freshness — computed in code, never by the model).

17 **atomic** questions in one batch (one judgement each — the docs' rule: never merge two
judgements into one question): 13 always, + 4 when the reaction tier is enabled.

| question | type | role |
|---|---|---|
| `named_luna` / `directly_addressed` | noul | composed in code into `addressed` (max of the two) |
| `luna_could_add_value` | noul | feeds the value composite |
| `message_would_fit` | noul | the ambient-message gate ("would speaking up be welcome") |
| `has_open_question_luna_can_answer` | noul | value + reaction-yield rule |
| `topic_fits_luna` / `would_be_redundant` / `someone_is_venting` | noul | value composite |
| `topic_is_sensitive` / `topic_is_private` | noul | **safety gates** — over the cap ⇒ silent always |
| `interruption_cost` / `timeliness` | score | value composite / timing band |
| `contribution_type` | choice | informational |
| `requests_reaction` | noul | explicit "react to this" outranks replies |
| `reaction_would_fit` / `reaction_emoji` | noul / choice | reaction tier fit + emoji (allow-list) |
| `reaction_would_feel_fresh` | noul | anti-repetition (paired with the code cooldown) |

### Stage 2 — compose(), the threshold cascade

Order matters and is deliberate (`cascade.compose`):

0. **Safety**: `sensitive ≥ 0.60` or `private ≥ 0.60` ⇒ silent, always, before anything else.
1. **Explicit reaction request** ⇒ reaction (the human asked for a tap; words would be wrong).
2. **Directed** (`addressed ≥ 0.70`) ⇒ message — being addressed is never overruled. Exception:
   merely *named* with no open question and a reaction clearly fits ⇒ a tap instead of a paragraph.
3. **Ambient message** — rare by design (`message_would_fit ≥ 0.42`, value `≥ 0.60`, timeliness
   in the 1.0 ± 0.5 band, plus timing gates `min_new_messages` 3 / `min_minutes_since_luna` 10,
   and not-addressed caps).
4. **Reaction** — its own fit judgment (`reaction_would_fit ≥ 0.66`), freshness (`≥ 0.43`), emoji
   confidence (`≥ 0.35`), private/sensitive caps; **yields** when a real open question deserves
   words (`open_q ≥ 0.55` and `add_value ≥ 0.45`). Media-only messages never get taps.
5. Otherwise silent.

### Stage 3 — hard budgets (code, independent of jev)

Reaction cooldown **15 minutes** (`ambient.budget.reaction_cooldown_minutes`) is a real brake;
daily/weekly caps are off by default. Dedup (never act twice on one message) is always on.

## The route chain — swappable and reorderable

`luna.ambient.jev` is hermes-style: a named `providers` registry (base_url, model, api_key_env,
optional endpoint/instructions/timeout_seconds) plus an ordered `route` list of names — first
entry is the primary, the rest are fallbacks. Reorder to reprioritise, rename to swap, add a
provider and slot it anywhere; inline dicts and legacy `fallbacks:` lists also resolve. Unknown
names are skipped (fail closed). Shipped order: `zen-free → local → typesafe` (free → local →
paid; local setup: the `local-jev` skill). Only 429/529 or transport failures advance; a
malformed response is a bug and never spends the next route. `LUNA_JEV_*` env vars override the
primary. `jev_usage` logs the serving route name, tokens, and cost per decision
(Behaviour page, Cost panel). OpenCode Go does not serve `/systemone`.

**Honest local-tier caveat** (measured: `luna/local-jev/README.md`): CLM/Laya answer these
social questions on a near-uncorrelated scale with hosted Jev, so the local route mostly stays
silent with the shipped thresholds. Fine as a free/private middle fallback; not at parity.

## Operating knowledge

- **Reaction tier** is allow-list gated (`ambient.reactions.allowed`: 👍 🤣 😭; empty disables —
  plan D19) and platform-gated (`telegram.reactions` + `allow_platform_actions`).
- `ambient.dry_run: true` means decisions are computed and logged but not delivered.
- Never do date arithmetic or counting in jev — timing is a Score band, arithmetic is code.
- State-shape rules for anyone editing questions: one judgement per question, full-sentence
  rubric levels, describe options (never bare keys), do not restate the question's keywords in
  the state, and A/B question rewording before shipping — stricter wording silently starves
  gates (see the jaggedness table in `luna/docs/jev.md`).
- Changing `CascadeConfig` defaults, question wording, or state shape changes behaviour for
  **every** backend — run `scripts/test.sh`, the replay corpus (`luna/tests/`), and measure
  against `jev_usage` history before shipping.

## Tuning surface

- Thresholds: `ambient.thresholds.*` in config (mirrors `CascadeConfig` fields) or
  `LUNA_AMBIENT_<FIELD>` env overrides. Defaults in `cascade.py` are the source of truth and are
  calibrated on real room replay (`luna/tools/jev_replay.py`).
- Labels for offline evaluation come free from `jev_usage` (the action recorded per decided
  message) — the benchmark set of the local-jev evaluation was built exactly this way.
- When asked "why did you stay silent?": the answer is one of the named reasons
  (`stage0: …`, `sensitive/private safety gate`, `addressed to Luna`, `middle band / below
  threshold`, `stage3: cooldown …`) — they are logged on every decision.
