/**
 * `UnsavedChangesProvider` — mounts the one `<DirtyBar>` and owns the `beforeunload` listener.
 *
 * Three responsibilities that have to live together, because each is a no-op without the others:
 *
 * - **`beforeunload`, only while dirty.** A listener that always returns a value makes the browser
 *   show "Leave site?" on every reload and every link-out of a clean dashboard. The listener's
 *   presence is derived from the registry snapshot, so the prompt is exactly as intrusive as the
 *   risk.
 * - **The bar.** Rendered above the routed tree, so it survives the navigation that a page-level one
 *   would have unmounted along with the form.
 * - **The blocked-navigation decision.** Save → commit every dirty surface, and only continue if
 *   every commit succeeded. Discard → throw them away and continue. Stay → drop the held navigation
 *   and leave the user exactly where they were.
 */

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { DirtyBar } from "@/components/DirtyBar";
import { pendingNavigation, unsavedRegistry } from "@/lib/dirty-registry";
import {
  UnsavedChangesContext,
  type UnsavedChangesApi,
} from "@/contexts/unsaved-changes-context";

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  // Two independent subscriptions: a held navigation can appear without the dirty set changing, and
  // vice versa when a surface registers. One `useSyncExternalStore` cannot watch two stores.
  const entries = useSyncExternalStore(
    unsavedRegistry.subscribe,
    unsavedRegistry.getSnapshot,
    unsavedRegistry.getSnapshot,
  );
  const pending = useSyncExternalStore(
    pendingNavigation.subscribe,
    pendingNavigation.getSnapshot,
    pendingNavigation.getSnapshot,
  );
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const barRef = useRef<HTMLDivElement>(null);

  const labels = useMemo(() => entries.map((entry) => entry.label), [entries]);
  const dirty = labels.length > 0;

  // Reserve the bar's actual height, including wrapped mobile actions, in the page scroller.
  useEffect(() => {
    if (!dirty || !barRef.current) return;
    const bar = barRef.current;
    const root = document.documentElement;
    const measure = () => root.style.setProperty("--unsaved-bar-height", `${bar.getBoundingClientRect().height}px`);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(bar);
    return () => {
      observer?.disconnect();
      root.style.removeProperty("--unsaved-bar-height");
    };
  }, [dirty]);

  // `beforeunload` only while something is dirty. `preventDefault` alone is not honoured by every
  // browser for the prompt, hence also setting `returnValue`; per the HTML spec the value is now
  // ignored but the assignment is what Firefox still needs.
  useEffect(() => {
    if (typeof window === "undefined" || !dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const onSave = useCallback(() => {
    if (savingRef.current) return;
    savingRef.current = true;
    const revision = pendingNavigation.getRevision();
    setSaving(true);
    void unsavedRegistry.saveAll().then((ok) => {
      savingRef.current = false;
      setSaving(false);
      // A failed save must not navigate: the surface is still dirty and its state would be lost.
      if (ok) pendingNavigation.proceed(revision);
    });
  }, []);

  const onDiscard = useCallback(() => {
    unsavedRegistry.discardAll();
    pendingNavigation.proceed();
  }, []);

  const onStay = useCallback(() => {
    pendingNavigation.cancel();
  }, []);

  const requestLeave = useCallback((resume: () => void) => {
    pendingNavigation.request(resume);
  }, []);

  const api = useMemo<UnsavedChangesApi>(() => ({ requestLeave }), [requestLeave]);

  return (
    <UnsavedChangesContext.Provider value={api}>
      {children}
      {/* Not rendered at all when clean: an empty fixed element over the bottom of every page is a
          invisible hit target, and `main` is a scroll container so the overlay would not even move
          with the content. */}
      {dirty && (
        <div
          ref={barRef}
          className="pointer-events-none fixed inset-x-0 bottom-0 z-[300] flex justify-center px-4 pb-4"
          data-unsaved-guard
        >
          <div className="pointer-events-auto w-full max-w-2xl shadow-2xl">
            <DirtyBar
              labels={labels}
              pending={pending}
              canSave={entries.every((entry) => entry.onSave)}
              saving={saving}
              onSave={onSave}
              onDiscard={onDiscard}
              onStay={onStay}
            />
          </div>
        </div>
      )}
    </UnsavedChangesContext.Provider>
  );
}
