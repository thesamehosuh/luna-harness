/**
 * `useUnsavedChanges` — declare that a surface has edits that are not on disk yet.
 *
 * The surface owns *what* dirty means and how to save or revert it; this hook owns the wiring. It
 * registers into the shared registry only while `dirty` is true, which is what makes `isDirty()` a
 * size check and what makes the `beforeunload` prompt appear exactly when there is something to
 * lose.
 *
 * Callbacks go through refs rather than effect dependencies. Inline arrow functions would
 * otherwise re-register on every render — and `register()` replaces the entry, so the identity of
 * the stored callback would churn constantly for no benefit. Reading through a ref at call time also
 * means the saved handler always sees the newest state, which a captured closure would not.
 */

import { useContext, useEffect, useRef } from "react";

import { unsavedRegistry, type UnsavedRegistry } from "@/lib/dirty-registry";
import { UnsavedChangesContext, type UnsavedChangesApi } from "@/contexts/unsaved-changes-context";

export interface UnsavedChangesOptions {
  /** Stable identity for this surface within a page. */
  id: string;
  /** What is unsaved, in the user's words: "the persona", "wake policy". Shown in the bar. */
  label: string;
  dirty: boolean;
  /** Returning `false` means "did not save" and blocks the pending navigation — see the registry. */
  onSave?: () => void | boolean | Promise<void | boolean>;
  onDiscard?: () => void;
  /** Overridden by tests; the app always uses the singleton. */
  registry?: UnsavedRegistry;
}

export function useUnsavedChanges({
  id,
  label,
  dirty,
  onSave,
  onDiscard,
  registry = unsavedRegistry,
}: UnsavedChangesOptions): void {
  const saveRef = useRef(onSave);
  const discardRef = useRef(onDiscard);
  // Assigned in an effect, not during render: writing a ref while rendering is what the
  // `react-hooks/refs` rule warns about, and this also guarantees the stored callback is never
  // observed mid-render.
  useEffect(() => {
    saveRef.current = onSave;
    discardRef.current = onDiscard;
  });

  // `hasSave` is a dependency in its own right: a surface that gains or loses the ability to save
  // (a modal that only becomes committable once its job is loaded) has to re-register, or the bar
  // would keep offering a Save that does nothing — or keep omitting one that would have worked.
  const hasSave = typeof onSave === "function";
  const hasDiscard = typeof onDiscard === "function";

  useEffect(() => {
    if (!dirty) return;
    return registry.register({
      id,
      label,
      // Indirection through the ref, not a captured closure: inline arrow functions would otherwise
      // re-register on every render, and a captured one would call a handler holding stale state.
      onSave: hasSave ? () => saveRef.current?.() : undefined,
      onDiscard: hasDiscard ? () => discardRef.current?.() : undefined,
    });
  }, [dirty, id, label, hasSave, hasDiscard, registry]);
}

/**
 * A dirty check that tolerates the ways a draft and its loaded baseline legitimately differ.
 *
 * The naive versions are wrong in ways users notice. Comparing `JSON.stringify(draft)` against the
 * server's version marks a freshly-loaded form dirty whenever the server omits an empty field or
 * returns extra keys — the browser then nags on every reload, which trains people to dismiss the
 * prompt without reading it. Comparing field-by-field in the other direction leaves the bar up
 * forever after a value is typed back to what it was.
 *
 * Deep equality on both sides fixes both: the draft must genuinely differ from the loaded value,
 * and round-tripping through JSON normalises key order and absent-vs-empty.
 */
export function isDraftDirty(draft: unknown, baseline: unknown): boolean {
  return stableStringify(draft) !== stableStringify(baseline);
}

function stableStringify(value: unknown): string {
  if (value === undefined) return "undefined";
  try {
    return JSON.stringify(value, (_key, val: unknown) => {
      if (val && typeof val === "object" && !Array.isArray(val)) {
        // Sorted keys so `{a,b}` and `{b,a}` compare equal regardless of insertion order.
        return Object.fromEntries(
          Object.entries(val as Record<string, unknown>).sort(([a], [b]) =>
            a < b ? -1 : a > b ? 1 : 0,
          ),
        );
      }
      return val;
    });
  } catch {
    // A cyclic or otherwise unserialisable draft: fall back to identity so a form is never
    // silently reported clean because its value could not be measured.
    return String(value);
  }
}

/**
 * A no-op default rather than a throw: a page that renders outside the provider must still work, it
 * just loses the guard. Throwing would turn a missing safety net into a blank page — the exact
 * failure this whole phase exists to prevent.
 */
const NO_GUARD: UnsavedChangesApi = { requestLeave: (resume) => resume() };

/**
 * Guard a navigation the router never sees: a profile switch (which remounts the routed tree rather
 * than calling `history.push`), a modal that discards its draft on close, a wizard's Cancel.
 *
 * For ordinary navigation use the guarded history — it covers sidebar links, `navigate()`, and
 * browser-back in one place without every call site opting in.
 */
export function useUnsavedChangesGuard(): UnsavedChangesApi {
  const ctx = useContext(UnsavedChangesContext);
  return ctx ?? NO_GUARD;
}
