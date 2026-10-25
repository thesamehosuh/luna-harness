/**
 * Render a persona draft back to SOUL.md, mirroring `render_soul` in
 * `luna/lib/luna_cli/character.py`.
 *
 * Why this exists: B2's export button shipped `bundle.soul.raw` — the **last-saved** SOUL.md — while
 * sitting on a page whose textareas hold the user's unsaved edits. So exporting a persona you had
 * been tuning silently threw those edits away and handed you the old file instead. The fix is to
 * render the draft, which means reimplementing the renderer's formatting rules client-side.
 *
 * The byte-level rules copied from the Python:
 *   - title defaults to `Companion` when blank, and is stripped
 *   - a blank intro / section body / footer contributes nothing (not an empty heading)
 *   - the footer is preceded by a `---` divider
 *   - everything is right-stripped and a single trailing newline is added
 *
 * Anything else here silently produces a SOUL.md that does not round-trip, so this is kept
 * framework-free and tested directly against the Python's output.
 */

import type { SoulSection } from "@/lib/luna-api";

export interface SoulDraft {
  title: string;
  intro: string;
  sections: SoulSection[];
  footer: string;
}

/** Port of `render_soul`. Keep byte-identical to the Python or exports stop round-tripping. */
export function renderSoul(draft: SoulDraft): string {
  const parts: string[] = [];

  parts.push(`# ${draft.title.trim() || "Companion"}\n`);

  const intro = draft.intro.trim();
  if (intro) parts.push(`\n${intro}\n`);

  for (const section of draft.sections) {
    // A blank body still emits its heading — matching the Python, which appends `## title`
    // unconditionally and only gates the body. Changing this would make an export re-import as a
    // different soul.
    parts.push(`\n## ${section.title.trim()}\n`);
    const body = section.body.trim();
    if (body) parts.push(`\n${body}\n`);
  }

  const footer = draft.footer.trim();
  if (footer) parts.push(`\n---\n\n${footer}\n`);

  return `${parts.join("").replace(/\s+$/, "")}\n`;
}

/** Line count, for a "this will be replaced" confirmation that says something concrete. */
export function countLines(text: string): number {
  if (!text) return 0;
  return text.replace(/\n$/, "").split("\n").length;
}

/**
 * The first `limit` lines of each of two documents, for a cheap side-by-side preview.
 *
 * A full diff would be nicer, but the honest cheap version is the two openings: a persona that
 * changes character usually changes its title and intro, so a mismatch there is the signal the user
 * needs before confirming an overwrite.
 */
export function soulPreview(text: string, limit = 6): string[] {
  if (!text) return [];
  return text.replace(/\n$/, "").split("\n").slice(0, limit);
}

/**
 * Whether two SOUL.md documents differ in the part that identifies them.
 *
 * Used to soften a confirmation: replacing a persona with an identical one is not destructive and
 * should not make the user read a scary dialog. Only a real difference earns the prompt.
 */
export function soulsDiffer(a: string, b: string): boolean {
  return a.trim() !== b.trim();
}
