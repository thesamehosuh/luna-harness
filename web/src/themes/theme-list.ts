import { BUILTIN_THEMES } from "./presets";
import { THEME_NAME_ALIASES } from "./aliases";
import type { DashboardTheme, ThemeListEntry } from "./types";

/**
 * Merge the server's theme list into what the picker renders.
 *
 * `presets.ts` is the label authority. The server sends built-ins as bare ids, and for any name we
 * own we read the label and description straight off `BUILTIN_THEMES` — a served label for a built-in
 * is ignored even if one is present. That is the whole point: when the backend also carried labels,
 * the two drifted and the dashboard showed "Hermes Teal" or "Luna Teal" depending on which surface
 * rendered the name. Refusing the server's copy means a re-vendor cannot reintroduce the split.
 *
 * User themes are the opposite case — their labels come from the user's own YAML, so the served
 * values are the truth and the name is shown verbatim if the YAML omitted them.
 *
 * Built-ins are emitted first and in `BUILTIN_THEMES` order so the picker's defaults do not shuffle
 * based on what the server happened to return.
 */
export function buildThemeList(entries: readonly ThemeListEntry[]): ThemeListEntry[] {
  const merged: ThemeListEntry[] = [];

  for (const theme of Object.values(BUILTIN_THEMES)) {
    merged.push({ name: theme.name, label: theme.label, description: theme.description });
  }

  for (const entry of entries) {
    if (entry.name in BUILTIN_THEMES) continue; // already emitted from the preset, with its real label
    // An older running server can still advertise retired presets. A real user definition with
    // the same name takes precedence, as it does during preference migration.
    if (Object.hasOwn(THEME_NAME_ALIASES, entry.name) && !entry.definition) continue;
    merged.push({
      name: entry.name,
      label: entry.label ?? entry.name,
      description: entry.description ?? "",
      definition: entry.definition,
    });
  }

  return merged;
}

/** Index the definitions the server shipped (user themes only — built-ins carry none). */
export function indexUserThemeDefs(
  entries: readonly ThemeListEntry[],
): Record<string, DashboardTheme> {
  const defs: Record<string, DashboardTheme> = {};
  for (const entry of entries) {
    if (entry.definition) defs[entry.name] = entry.definition;
  }
  return defs;
}
