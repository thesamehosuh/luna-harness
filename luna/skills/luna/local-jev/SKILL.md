---
name: local-jev
description: |
  Set up, configure, and operate a self-hosted Jev-compatible System One endpoint (CLM or Laya)
  as Luna's middle jev route (free tier → local → paid). Use when the user asks about local jev,
  running jev offline/locally, CLM, Laya, edgejev, the jev fallback chain, local model endpoints
  for the companion's wake decisions, GPU hang/fan issues while serving jev, or why the local jev route stays
  silent. Covers install, the config block, ports, measured limits, and safe GPU operation.
license: Apache-2.0
metadata:
  version: "1.0.0"
---

# Local Jev — self-hosted System One as the middle route

Luna decides wakes through jev (TypeSafe System One). Besides the hosted free tier and the paid
route, the harness supports a **self-hosted Jev-compatible endpoint** slotted *between* them in
the fallback chain: free tier → **local** → paid. This skill is how to stand one up and wire it
in. You download and run the model yourself; the harness only points at the endpoint.

## What "local jev" means here

Any server speaking the System One wire format (`POST {base}/systemone` with
`{state, model, questions}` → `{answers, usage}`) on this machine. Two known options:

| option | what it is | runs on | serves at | model name |
|---|---|---|---|---|
| **CLM** (Contrastive Language Model, 8B) | Qwen3-8B encoder + contrastive heads; open research release with a TypeSafe-compatible API | GPU (or CPU, slow) | `http://127.0.0.1:8700/v1` | `clm-latest` |
| **Laya** (edgejev, 322M) | small System One model; int8, fully offline | CPU is fine | `http://127.0.0.1:8009/v1` | `jev-ml` / `jev-en` |

Upstream projects: CLM (`pip install contrastive-lm`, repo `contrastive-lm`; needs a Qwen3-8B
pooling encoder — vLLM on CUDA, or llama.cpp `--pooling last` on Vulkan) and Laya
(`yzfly/edgejev` + ConvAI Laya weights). Install them from their own docs; do not vendor them
into this repo.

**Ports to never take:** `:8010` is Honcho's. `:8700`/`:8090` (CLM), `:8009` (Laya) are the
usual choices here.

## Configure the harness (the only step the harness needs)

`luna/config/config.yaml.luna` → `luna.ambient.jev` — hermes-style: a named `providers` registry
plus an ordered `route` list. **Swap and reorder routes by editing `route` only**; the local slot
can sit anywhere (shipped: free → local → paid):

```yaml
    jev:
      timeout_seconds: 20
      route: [zen-free, local, typesafe]      # reorder freely; first = primary
      providers:
        zen-free:
          base_url: https://opencode.ai/zen/v1
          model: jev-1.13-free
          api_key_env: OPENCODE_ZEN_API_KEY
        local:
          base_url: http://127.0.0.1:8700/v1   # Laya: http://127.0.0.1:8009/v1
          model: clm-latest                    # Laya: the name you served (e.g. jev-ml)
        typesafe:
          base_url: https://api.typesafe.ai/v1
          model: jev-latest
          api_key_env: TYPESAFE_API_KEY
```

- `model` is whatever your local server accepts/labels (CLM: `clm-latest`; Laya: the name you
  served). Omit `api_key_env` for local — no `Authorization` header is sent, and local servers
  do not need one. A provider may also set `timeout_seconds`, `endpoint`, `instructions`.
- Make local the primary (e.g. fully offline box): `route: [local, zen-free, typesafe]`.
- Nothing listening on the port? The slot fails over almost immediately (connection refused).
  To skip it entirely, drop `local` from `route`.
- Unknown names in `route` are skipped (fail closed) — a typo quiets the chain, it never crashes
  the poller.
- The chain is resilient by design: if the local server dies mid-session, the next exhausted
  free-tier call falls through to paid — Luna never mutes because of the local slot.

## Measured limits (read before promising parity)

Benchmarked 2026-09-28 against 166 of Luna's own recorded jev verdicts (details:
`luna/local-jev/README.md`):

| | CLM-8B | Laya |
|---|---|---|
| verdict agreement vs hosted Jev (hand cascade) | 0.50 balanced (0/21 acts) | 0.50 balanced (1/21 acts) |
| latency per 17-question batch | ~15 s (GPU) | ~67 s (CPU) |

Local backends answer the social-judgement questions on a different, nearly uncorrelated scale
from hosted Jev, so with the shipped thresholds Luna mostly **stays silent** on the local route.
That is acceptable as a middle fallback (silence is Luna's default anyway) and it is free and
private — but it is **not** hosted-Jev parity yet. Fine-tuning CLM on Luna-domain labels is the
planned fix; until then treat the local route as a cost/availability tier, not a quality tier.

## Safe operation (this hardware class)

- **Sustained GPU load hangs some cards** (RX 580/gfx803 class: display loss, fan stuck at max,
  forced reboot). The failure signature is **loss of fan speed control**, not temperature —
  temperature reads fine right up to the hang. Run `luna/tools/gpu_fan_guard.py` whenever the
  GPU serves batches; it watches the tachometer and kills GPU workloads when the fan jumps
  toward `fan1_max`.
- Batch experiments in **small runs** (≤12 requests) with idle gaps; never hours of back-to-back
  requests. If the fan spins up hard, stop — do not "just finish the run".
- llama.cpp + mean pooling cannot split across physical batches: if you embed long states with
  `--pooling mean`, raise `--ubatch` (e.g. `-b 2048 -ub 2048`) or inputs over ~512 tokens fail.
  `--pooling last` (what CLM's head needs) does not have this limit.
- CLM's encoder and Honcho's LM Studio embedding model share an 8 GiB card. Keep LM Studio's
  *embedding* model loaded (Honcho needs it); generative models are safe to unload.

## Health checks

```bash
curl -s http://127.0.0.1:8700/health        # CLM api
curl -s http://127.0.0.1:8090/health        # CLM encoder
curl -s http://127.0.0.1:8009/health        # Laya
Behaviour page, Cost panel                  # which route served recent decisions
```

`jev_usage` in `~/.luna/luna-state.db` records the route (`free` / `local`… / `fallback:*`),
tokens, and cost per decision — the ground truth for "did the local slot actually serve".
