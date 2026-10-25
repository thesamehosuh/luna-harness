/**
 * Copy for the unsaved-changes bar.
 *
 * Kept out of the component for the same reason as `load-error-copy.ts`: the label assembly (which
 * surface is named, how many are collapsed into a count, the `{what}` / `{count}` placeholders) is
 * pure logic that is worth testing without rendering a component.
 *
 * Every key is optional on the locale type, so the 16 exhaustive `Translations` objects still
 * compile while untranslated. A missing translation degrades to readable English rather than to an
 * empty bar — an unsaved-changes warning that renders blank is worse than one in the wrong language.
 */

import { en } from "@/i18n/en";

/** i18n keys the bar reads. */
export type DirtyBarKey =
  | "unsavedTitle"
  | "unsavedNavBlocked"
  | "unsavedWhat"
  | "unsavedDiscard"
  | "unsavedStay"
  | "unsavedSaveAndLeave"
  | "unsavedDiscardAndLeave"
  | "unsavedMultiple";

export interface DirtyBarLabels {
  title: string;
  /** "You have unsaved changes on the persona." — the whole reason the bar is interrupting. */
  blocked: string;
  what: string;
  discard: string;
  stay: string;
  saveAndLeave: string;
  discardAndLeave: string;
  multiple: string;
}

export function dirtyBarLabels(
  common: Partial<Record<DirtyBarKey, string>>,
  labels: string[],
): DirtyBarLabels {
  const pick = (key: DirtyBarKey, fallback: string) => common[key] ?? fallback;
  const multiple = pick("unsavedMultiple", en.common.unsavedMultiple!);
  // One surface is named outright; several collapse to the first plus a count, so a page with three
  // guarded forms does not produce a paragraph-long bar.
  const what =
    labels.length <= 1
      ? (labels[0] ?? "")
      : `${labels[0]}${multiple.replace("{count}", String(labels.length - 1))}`;
  return {
    title: pick("unsavedTitle", en.common.unsavedTitle!),
    blocked: pick("unsavedNavBlocked", en.common.unsavedNavBlocked!).replace("{what}", what),
    what: pick("unsavedWhat", en.common.unsavedWhat!),
    discard: pick("unsavedDiscard", en.common.unsavedDiscard!),
    stay: pick("unsavedStay", en.common.unsavedStay!),
    saveAndLeave: pick("unsavedSaveAndLeave", en.common.unsavedSaveAndLeave!),
    discardAndLeave: pick("unsavedDiscardAndLeave", en.common.unsavedDiscardAndLeave!),
    multiple,
  };
}
