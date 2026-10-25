# Provenance — jev-mechanics (first-party)

- **Upstream:** none. First-party skill of the luna-harness fork.
- **Version:** 1.0.0 (`metadata.version` in SKILL.md)
- **Source:** distilled from `luna/lib/luna_core/cascade.py`, `luna/plugins/luna-ambient/`,
  `luna/docs/jev.md`, and the 2026-09-28 evaluation (`luna/local-jev/README.md`).
- **Created:** 2026-09-28
- **Deploy target:** `$HERMES_HOME/skills/luna/jev-mechanics/` (install.sh copies this dir)

## Why it is baked in

The product now has real decision machinery — typed questions, threshold cascade, route chain,
hard budgets — and it must be able to explain and reason about its own mechanics ("why did I
stay silent?", "why no reaction?") without hallucinating a policy. One skill keeps that
knowledge single-sourced and shippable with the fork. It is **on-demand** (not in
`skills.auto_load`) so the cached system prompt stays clean.

## Updating

Any change to `CascadeConfig` defaults, question wording (`build_questions`), state shape
(`build_state`), stage order, or the route chain must update this skill in the same change —
the numbers in the gate tables are quoted from the code. Keep the honesty rule for the local
tier's quality claims: numbers only, sourced from `luna/local-jev/README.md`.
