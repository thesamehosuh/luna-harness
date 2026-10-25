/**
 * The unsaved-changes registry.
 *
 * Before this, `grep 'beforeunload|isDirty|unsaved'` over `web/src` returned one hit and it was a
 * comment: nothing in the dashboard stopped a navigation from destroying in-progress work. The
 * persona, the raw-YAML textarea, the wake-policy form, a composed cron job and the five-step
 * profile wizard were all one click (or one browser-back, or one Escape) from gone.
 *
 * Two things live here, both framework-free so the vitest suite covers them without a DOM:
 *
 * - {@link UnsavedRegistry} — the set of surfaces that currently have unsaved edits. A surface
 *   registers *while dirty* and unregisters when clean, so "is anything dirty" is a size check and
 *   a stale entry can't outlive the component that made it.
 * - {@link PendingNavigationStore} — the one navigation the guard deferred. Holding it in a store
 *   rather than component state is deliberate: `createGuardedHistory` lives above the React tree
 *   (it has to, to wrap the router's history), so it needs a channel to the UI that does not
 *   depend on provider mount order.
 *
 * Both are classes rather than module-level mutable objects so tests get a fresh instance; the
 * singletons below are what `main.tsx` wires up.
 */

/** One surface with unsaved edits. */
export interface DirtyEntry {
  /** Stable identity so a re-render updates the entry instead of adding a second one. */
  id: string;
  /** Human description of what is unsaved — "the persona", "wake policy". Shown in the DirtyBar. */
  label: string;
  /**
   * Commit the edits. Omitted when the surface has no way to save (see `DirtyBar`, which hides its
   * Save button when no registered surface can save).
   *
   * Returning `false` means "did not save", and `saveAll` then refuses the pending navigation. This
   * exists because the obvious implementation — let the handler throw — does not work here: every
   * real handler already catches its own error to show a toast, so a throw-only contract would be
   * satisfied by handlers that failed, and the guard would navigate away having saved nothing.
   * `void`/a resolved promise still means success.
   */
  onSave?: () => void | boolean | Promise<void | boolean>;
  /** Throw the edits away and return the surface to its loaded state. */
  onDiscard?: () => void;
}

export class UnsavedRegistry {
  private entries = new Map<string, DirtyEntry>();
  private listeners = new Set<() => void>();
  private snapshot: readonly DirtyEntry[] = [];

  // `subscribe` / `getSnapshot` are handed straight to `useSyncExternalStore`, which calls them
  // unbound — so a prototype method would lose `this`. Binding here makes the class safe to
  // destructure, which is otherwise an easy footgun at every call site.
  constructor() {
    this.subscribe = this.subscribe.bind(this);
    this.getSnapshot = this.getSnapshot.bind(this);
  }

  /**
   * Add (or replace) an entry and return its unregister function.
   *
   * Registering the same `id` twice replaces the callbacks — which is what a re-render with a new
   * inline `onSave` closure should do. Without that, a surface whose save handler captures fresh
   * state would keep calling the first closure forever.
   */
  register(entry: DirtyEntry): () => void {
    this.entries.set(entry.id, entry);
    this.publish();
    return () => {
      // Only remove our own entry: a remount may already have replaced this id, and unregistering
      // then would drop the live surface's entry.
      if (this.entries.get(entry.id) !== entry) return;
      this.entries.delete(entry.id);
      this.publish();
    };
  }

  unregister(id: string): void {
    if (!this.entries.delete(id)) return;
    this.publish();
  }

  list(): DirtyEntry[] {
    return [...this.entries.values()];
  }

  get size(): number {
    return this.entries.size;
  }

  isDirty(): boolean {
    return this.entries.size > 0;
  }

  /**
   * A referentially stable view of the entries for `useSyncExternalStore`.
   *
   * React compares snapshots by identity and re-renders when they differ, so returning a fresh array
   * from `list()` would either loop forever or (worse) miss the change that actually happened. The
   * array is rebuilt only on a real mutation, and only if the contents differ.
   *
   * This also fixes a missed-notification trap: a component that renders *before* its own effect
   * registers would otherwise read an empty list and never be told, because the change landed
   * before `useSyncExternalStore` had subscribed. React re-reads the snapshot once subscribed, and
   * a stable array makes that comparison meaningful.
   */
  getSnapshot(): readonly DirtyEntry[] {
    return this.snapshot;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /**
   * Run every registered `onSave` in registration order.
   *
   * Resolves false if any handler throws **or returns false**, which is what keeps "Save and leave"
   * honest. Without the `false` return path this was the worst bug in the guard: every surface
   * catches its own failure to show a toast, so `saveAll` resolved true, the navigation ran, and the
   * unsaved work was destroyed with an error toast as the last thing on screen.
   */
  async saveAll(): Promise<boolean> {
    const entries = this.list();
    // Saving one form cannot authorize discarding another that has no save action.
    if (entries.some((entry) => !entry.onSave)) return false;
    for (const entry of entries) {
      try {
        const result = await entry.onSave!();
        if (result === false) return false;
      } catch {
        // A surface that could not save must not let the navigation proceed — losing the page is
        // better than losing the write that failed.
        return false;
      }
    }
    return true;
  }

  /** Run every registered `onDiscard`. A throwing discard is swallowed: the surface is going away
   *  regardless, and the navigation the user asked for should still happen. */
  discardAll(): void {
    for (const entry of this.list()) {
      try {
        entry.onDiscard?.();
      } catch {
        /* the surface is being torn down anyway */
      }
    }
  }

  private publish(): void {
    const next = [...this.entries.values()];
    const unchanged =
      next.length === this.snapshot.length &&
      next.every((entry, i) => entry === this.snapshot[i]);
    if (unchanged) return;
    this.snapshot = next;
    for (const listener of [...this.listeners]) listener();
  }
}

export class PendingNavigationStore {
  private resume: (() => void) | null = null;
  private listeners = new Set<() => void>();
  private pending = false;
  private revision = 0;

  // A field rather than a constructor parameter property: `erasableSyntaxOnly` is on for this
  // project, so parameter properties are not available syntax.
  private readonly registry: UnsavedRegistry;

  constructor(registry: UnsavedRegistry = unsavedRegistry) {
    this.registry = registry;
    // Same reason as `UnsavedRegistry`: these go to `useSyncExternalStore` unbound.
    this.subscribe = this.subscribe.bind(this);
    this.getSnapshot = this.getSnapshot.bind(this);
  }

  /**
   * Defer a navigation, or run it immediately when nothing is dirty.
   *
   * Returns true when the navigation was allowed through. The history wrapper uses that to decide
   * whether it still has to undo the move it already made (a POP has already changed the URL by the
   * time we see it).
   */
  request(resume: () => void): boolean {
    if (!this.registry.isDirty()) {
      resume();
      return true;
    }
    // A second request while one is pending would silently drop the first: press back, then click a
    // sidebar link, and the bar would offer the link while the back was forgotten. Keeping the
    // original is the honest behaviour — the user is still asked, and they are asked about the
    // navigation they actually took. Re-entry only matters for a resume that is itself guarded.
    if (this.resume) return false;
    this.resume = resume;
    this.pending = true;
    this.revision += 1;
    this.emit();
    return false;
  }

  hasPending(): boolean {
    return this.resume !== null;
  }

  /** Stable boolean snapshot for `useSyncExternalStore`. */
  getSnapshot(): boolean {
    return this.pending;
  }

  /** A save may only resume the navigation that was pending when it started. */
  getRevision(): number {
    return this.revision;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Drop the deferred navigation — the "Stay" action. */
  cancel(): void {
    if (!this.resume) return;
    this.resume = null;
    this.pending = false;
    this.revision += 1;
    this.emit();
  }

  /**
   * Run and clear the deferred navigation — the "Save" / "Discard" actions.
   *
   * Cleared *before* running so a `resume` that itself triggers another guarded navigation (a
   * redirect, a profile switch) is not swallowed by a stale pending entry.
   */
  proceed(expectedRevision = this.revision): void {
    if (expectedRevision !== this.revision) return;
    const resume = this.resume;
    if (!resume) return;
    this.resume = null;
    this.pending = false;
    this.revision += 1;
    this.emit();
    resume();
  }

  private emit(): void {
    for (const listener of [...this.listeners]) listener();
  }
}

/** The instances the app uses. Tests construct their own rather than reaching for these. */
export const unsavedRegistry = new UnsavedRegistry();
export const pendingNavigation = new PendingNavigationStore();
