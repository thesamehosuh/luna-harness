# Provenance — local-jev (first-party)

- **Upstream:** none. First-party skill of the luna-harness fork.
- **Version:** 1.0.0 (`metadata.version` in SKILL.md)
- **Source:** distilled from the 2026-09-28 local System One evaluation session; findings and
  numbers live in `luna/local-jev/README.md` (experiments tree, not shipped to `$HERMES_HOME`).
- **Created:** 2026-09-28
- **Deploy target:** `$HERMES_HOME/skills/luna/local-jev/` (install.sh copies this dir)

## Why it is baked in

The fork's jev route chain supports a self-hosted System One endpoint as the middle fallback
(free → local → paid). Operating one safely needs machine-specific knowledge (GPU hang class,
ports shared with Honcho, measured quality limits) that the product must carry so nobody
re-learns it the hard way. The skill is harness-owned and always deployed; it is **on-demand**
(not in `skills.auto_load`) so it never touches the cached system prompt.

## Updating

When the fine-tuned CLM head lands or the benchmark set grows, update the "Measured limits"
table and bump `metadata.version`. Keep the honesty rule: never describe the local route as
at-parity without a benchmark number behind it.
