# Testing

Two entry points (also see `PRODUCT_PLAN.md` §7 for the test policy):

```bash
scripts/test.sh            # unit + component + upstream gateway contract subset
scripts/test-contract.sh   # private-API + prompt-cache contract set (run after every upstream merge)
```

## Layout

```
luna/tests/
  unit/        pure logic: identity, text, room, jev, cascade, budget, indexer, peers,
               jev-route-tiers, queued-final-reply-anchor, cron-group-envelope,
               operator-route (loaded from the tree)
  component/   plugins against fakes + local Honcho (to be filled as components land)
  contract/    source-level private-symbol checks + engine-edit inventory checks (gate upstream merges)
  replay/      offline room replay + golden files (to be filled from real transcripts)
  fixtures/    telegram events, room transcripts, jev recordings, honcho layouts
```

## Running locally

The runtime venv (`~/.luna/venv`) has hermes deps; the test suite needs `pytest` and `pyyaml`
(plugins parse `config.yaml` in tests), so a lightweight venv is fine:

```bash
python3 -m venv .venv
.venv/bin/pip install pytest pyyaml
.venv/bin/python -m pytest -q luna/tests
```

Determinism: injected clock, UTC, seeded RNG, no network by default. jev tests use recorded
fixtures unless `--live` + `OPENCODE_API_KEY`. Honcho tests use a local `docker compose` workspace
(`luna-test`).

## Contract tests gate upstream merges

`luna/tests/contract/` reads the engine source files and asserts the private symbols we depend on
still exist (`_set_pending_turn_sidecar_notes`, `_telegram_group_observe_shared_source`,
`resolve_author_peer_id`, the `author_peer_id` key, `_hm_pre_gateway_dispatch_hook`,
`pre_gateway_dispatch`, `MemoryProvider`, `turn_author`), that the wiring of every Luna engine edit
survives, and that the edit inventory in `luna/docs/engine-vendor.md` stays complete
(`test_engine_edits.py`). A failure **blocks** the merge until the pin/edit is reconciled.

## Regression corpus (must stay green)

- the 58,335-char prefetch case (`luna/tests/unit/test_budget.py`)
- an A→B→C cross-member reply (`luna/tests/unit/test_room.py`)
- a 15-member roster (identity + alias map)
- a venting message (must not wake) and a sensitive message (must not wake) — cascade gates
- a high-value open question (must wake exactly once)

## Manual E2E

1. Run `luna-ambient` in dry-run for 24h; review intended wakes; tune thresholds.
2. Enable on the real group; observe a week; check `wakes` and member reactions; confirm caps + no 409s.
3. Verify: mention triggers; cross-member reply answered correctly; DM stays verbose; group stays
   conversational-only; purple skin in the CLI.
