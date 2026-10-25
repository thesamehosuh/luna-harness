/**
 * Pure presentation helpers for the Behaviour page's threshold editors.
 * Kept free of api/window imports so the vitest suite covers them directly.
 */

export interface ThresholdGroup {
  name: string;
  keys: string[];
}

/** The subset of `ThresholdValue` these helpers read. Structural so a full
 *  `ThresholdValue` satisfies it without importing the api module. */
export interface ThresholdBounds {
  min?: number;
  max?: number;
}

/**
 * Group threshold keys for the Behaviour page. Order matters: the named groups
 * first, everything else last (a newly added cascade field still shows up).
 */
export function groupThresholdKeys(keys: string[]): ThresholdGroup[] {
  const groups: Array<{ name: string; match: (k: string) => boolean; keys: string[] }> = [
    { name: "Wake gates", match: (k) => k.startsWith("min_") || k.startsWith("message_min_") || k.startsWith("directed_"), keys: [] },
    { name: "Reactions", match: (k) => k.startsWith("reaction_"), keys: [] },
    { name: "Safety ceilings", match: (k) => k.startsWith("safety_") || k.startsWith("message_max_"), keys: [] },
    { name: "Timing", match: (k) => k.startsWith("timeliness_"), keys: [] },
    { name: "Scoring weights", match: (k) => k.startsWith("w_"), keys: [] },
    { name: "Capacity", match: (k) => k === "state_max_chars" || k === "recent_lines", keys: [] },
  ];
  const rest: string[] = [];
  for (const key of [...keys].sort()) {
    const group = groups.find((g) => g.match(key));
    if (group) group.keys.push(key);
    else rest.push(key);
  }
  const out: ThresholdGroup[] = groups
    .filter((g) => g.keys.length > 0)
    .map(({ name, keys: ks }) => ({ name, keys: ks }));
  if (rest.length) out.push({ name: "Other", keys: rest });
  return out;
}

/** Human label for a threshold key: ``message_min_value`` → ``message min value``. */
export function thresholdLabel(key: string): string {
  return key.replace(/^.*thresholds\./, "").replaceAll("_", " ");
}

/** Map a cascade field type to the input step used by the number editors. */
export function thresholdStep(type: string): number {
  return type === "int" ? 1 : 0.01;
}

/**
 * Whether a threshold may be edited as a slider.
 *
 * A slider needs a real range from the backend. Rendering one without `min`/`max` is how the page
 * used to ship `max={1}` for every threshold: a minutes-since-last-spoke default of 10 pinned to
 * the far right, and dragging left wrote 0 — silently zeroing a wake cooldown. An unresolvable
 * bound must degrade to a number input, never to a guessed range.
 */
export function canSlider(entry: ThresholdBounds): boolean {
  return (
    typeof entry.min === "number" &&
    typeof entry.max === "number" &&
    Number.isFinite(entry.min) &&
    Number.isFinite(entry.max) &&
    entry.max > entry.min
  );
}

/**
 * Clamp a threshold value into its declared range.
 *
 * The backend validates on write, so an out-of-range value would be rejected there — but only
 * after the user has already typed it. Clamping on the way in keeps the control and the written
 * value in agreement.
 */
export function clampThreshold(value: number, entry: ThresholdBounds): number {
  const low = typeof entry.min === "number" ? entry.min : -Infinity;
  const high = typeof entry.max === "number" ? entry.max : Infinity;
  if (value < low) return low;
  if (value > high) return high;
  return value;
}
