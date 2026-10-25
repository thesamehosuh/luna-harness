# Upstream sync

- `origin` = the product repo
- `upstream` = `NousResearch/hermes-agent`
- Base pin: **`59f9ff8dbc`** (hermes `0.21.3`, has the Sept-2026 module decomposition)

Engine edits are folded into the tree (PRODUCT_PLAN P1) and recorded in
`luna/docs/engine-vendor.md` — that file is the single inventory of every Luna edit to engine
files. This page covers the sync workflow only.

## Workflow

```bash
git fetch upstream
git merge upstream/main
scripts/test-contract.sh          # gates the merge
scripts/test.sh                   # luna tiers + bounded upstream subset
```

Never rebase published fork history.

## Expected conflicts

- `AGENTS.md` — intentional divergence (our dev guide vs upstream's). Upstream's copy is preserved at
  `luna/docs/hermes-upstream-AGENTS.md`; keep ours.
- The engine files listed in `luna/docs/engine-vendor.md` — Luna's edits land there; conflict
  resolution preserves the edit (each entry's provenance marker locates it).

## When a contract test fails

`luna/tests/contract/` fails when an upstream rename/removal breaks a symbol or wiring we depend
on. That **blocks** the merge until one of:

1. the pin is advanced and the adapter is updated (e.g. the sidecar method was renamed → update
   `luna-room` + the contract test), or
2. an engine edit restores the behavior (add/extend the inventory entry in
   `luna/docs/engine-vendor.md`), or
3. the fallback path is accepted and documented here.

## Engine edit ledger

Formerly a table of `luna/patches/*.patch`. Since P1 the edits live in the tree; the full
inventory — file, provenance (ex-patch number), and behavioural notes — is
`luna/docs/engine-vendor.md`. The old ledger's "overreach to know about" notes were folded
into that inventory's notes column.

## Declared tree divergences (outside `luna/`)

- `AGENTS.md` — intentional (see above).
- `.gitignore` — small additions for the Luna runtime artifacts.
- `scripts/test.sh`, `scripts/test-contract.sh` — Luna's own test entry points living in upstream's
  `scripts/` dir for discoverability.

Everything else in the fork is upstream-untouched.

## Pin history

| Date | Base | hermes | Note |
|---|---|---|---|
| 2026-09-24 | `59f9ff8dbc` | 0.21.3 | initial harness pin (from the live install). |
