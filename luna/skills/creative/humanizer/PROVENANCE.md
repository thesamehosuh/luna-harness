# Provenance — humanizer (vendored)

- **Upstream:** https://github.com/blader/humanizer (Siqi Chen, MIT)
- **Version:** 3.0.0 (`metadata.version` in SKILL.md)
- **Pinned commit:** `9862685f575c65a8247f90369951df1b3416e3d6` (main, fetched 2026-09-26)
- **Deploy target:** `$HERMES_HOME/skills/creative/humanizer/` (install.sh copies this dir)

## Why it is baked in

Luna's purpose is being a believable human member of the room; AI tells break the illusion for
everyone. The skill is therefore harness-owned and always deployed (not an optional catalog
install), and `skills.auto_load` in `config.yaml` injects its full body into the stable system
prompt tier **once per session** — cache-safe and applied to every reply without the model
invoking `skill_view`. The mechanical subset (residue, openers, chat line rhythm) is additionally
enforced in `luna/lib/luna_core/text.py` as a free fallback. SOUL.md is user-owned and stays
independent of all of this.

## Local amendments

The vendored SKILL.md carries one clearly-marked harness block ("Harness note (Luna)") that makes
the every-reply expectation explicit. The skill body below it is upstream 3.0.0 verbatim.

## Updating

Fetch the new SKILL.md + LICENSE at a pinned commit, bump the line above, and re-check the
SOUL.md distillation against the new pattern list (v3 renumbered the patterns; the distill
references tells, not numbers).
