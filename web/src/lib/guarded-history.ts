/**
 * A react-router history that refuses to navigate while something is dirty.
 *
 * The dashboard uses the declarative `<BrowserRouter>`, which has no blocker primitive —
 * `useBlocker` needs a data router (`createBrowserRouter` + `RouterProvider`), and migrating the
 * whole shell to one is far outside a guard's remit. The narrow seam that *does* work is the
 * history object itself: every `navigate()`, `<Link>` and `<NavLink>` ends up calling `push`,
 * `replace` or `go` on it. Wrapping those three, plus the `popstate` path that browser-back takes,
 * covers in-app navigation without touching routing.
 *
 * `POP` is the awkward one: by the time we see it the URL has already changed. We put the history
 * back with a counter-`go` and never forward the update to the router, so React keeps rendering the
 * page the user is still on. If they then choose Save/Discard, the held resume replays the original
 * `go` and the page finally changes.
 */

import {
  PendingNavigationStore,
  pendingNavigation,
  unsavedRegistry,
  type UnsavedRegistry,
} from "./dirty-registry";

/** `"POP" | "PUSH" | "REPLACE"` — react-router's `Action`, inlined to avoid an enum import. */
export type HistoryAction = "POP" | "PUSH" | "REPLACE";

export interface HistoryUpdate {
  action: HistoryAction;
  location: unknown;
  delta: number | null;
}

/**
 * The slice of react-router's `History` we wrap. Structural so tests can supply a fake, and
 * satisfied by `createBrowserHistory()`'s return value.
 */
export interface RoutableHistory {
  readonly action: HistoryAction;
  readonly location: unknown;
  createHref(to: never): string;
  createURL(to: never): URL;
  encodeLocation(to: never): { pathname: string; search: string; hash: string };
  push(to: never, state?: unknown): void;
  replace(to: never, state?: unknown): void;
  go(delta: number): void;
  listen(listener: (update: HistoryUpdate) => void): () => void;
}

/**
 * Both stores are injected rather than reached for, so a test can drive a private pair. The defaults
 * are the app singletons, which is what `main.tsx` wants.
 */
export function createGuardedHistory(
  base: RoutableHistory,
  registry: UnsavedRegistry = unsavedRegistry,
  navigation: PendingNavigationStore = pendingNavigation,
): RoutableHistory {
  // True while we are moving the history back to undo a blocked POP, so the POP that undo produces
  // is forwarded to the router instead of being blocked again.
  let restoring = false;

  const guarded: RoutableHistory = {
    get action() {
      return base.action;
    },
    get location() {
      return base.location;
    },
    createHref: (to) => base.createHref(to),
    createURL: (to) => base.createURL(to),
    encodeLocation: (to) => base.encodeLocation(to),

    push(to, state) {
      navigation.request(() => base.push(to, state));
    },

    replace(to, state) {
      navigation.request(() => base.replace(to, state));
    },

    go(delta) {
      if (delta === 0) {
        base.go(0);
        return;
      }
      navigation.request(() => base.go(delta));
    },

    listen(listener) {
      return base.listen((update) => {
        // `delta !== 0` matters: react-router reports 0 for a same-entry POP, and `history.go(0)`
        // is a document reload by spec. Blocking one and then calling `go(-0)` would reload the page
        // with the router never told and a navigation held whose resume is another reload.
        const blockedPop =
          update.action === "POP" &&
          !restoring &&
          registry.isDirty() &&
          update.delta !== null &&
          update.delta !== 0;

        if (update.action === "POP" && restoring) {
          // This is our own undo coming back. The router was never told about the move we blocked,
          // so it still holds the old location — forwarding this would only re-render it, while
          // *not* forwarding leaves URL and rendered page in agreement. Swallowing it also keeps
          // `restoring` from lingering: the flag describes "the popstate I caused", so it must be
          // consumed by that popstate and nothing else. Treating it as a window in time was the bug
          // where two fast back-presses consumed the flag and let a real navigation through.
          restoring = false;
          return;
        }

        if (!blockedPop) {
          listener(update);
          return;
        }

        const delta = update.delta as number;
        // Hold the navigation the user asked for, then walk the history back so the URL matches the
        // page React is still rendering.
        // `request` returns true when it ran the resume immediately — i.e. the surface became clean
        // between the `isDirty()` check above and here. The navigation has already happened, so
        // walking back would silently undo a move the user was allowed to make.
        const allowedThrough = navigation.request(() => {
          restoring = true;
          base.go(delta);
        });
        if (allowedThrough) return;
        restoring = true;
        base.go(-delta);
      });
    },
  };

  return guarded;
}
