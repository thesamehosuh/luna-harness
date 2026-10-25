/**
 * The guarded history, tested against a fake history rather than a real browser.
 *
 * `push`/`replace`/`go` are trivially checkable, but `POP` is the case that matters: browser-back has
 * already moved the URL by the time we learn about it, so the guard has to put it back *and* keep the
 * React tree from ever hearing about the move. A fake is the only way to assert that without a real
 * history stack — jsdom's `history.back()` is async and would make these tests flaky.
 */

import { describe, expect, it, vi } from "vitest";

import { PendingNavigationStore, UnsavedRegistry } from "./dirty-registry";
import {
  createGuardedHistory,
  type HistoryUpdate,
  type RoutableHistory,
} from "./guarded-history";

/** Records what the guard asked the underlying history to do. */
function fakeHistory() {
  const listener = { current: null as ((u: HistoryUpdate) => void) | null };
  const seen: HistoryUpdate[] = [];
  const calls = { push: [] as unknown[], replace: [] as unknown[], go: [] as number[] };
  const base: RoutableHistory = {
    action: "POP",
    location: { pathname: "/character" },
    createHref: (() => "/href") as never,
    createURL: (() => new URL("http://localhost/")) as never,
    encodeLocation: (() => ({ pathname: "/", search: "", hash: "" })) as never,
    push: (to, state) => void calls.push.push([to, state]),
    replace: (to, state) => void calls.replace.push([to, state]),
    go: (delta) => void calls.go.push(delta),
    listen: (fn) => {
      // react-router's history throws on a second listener; modelling that keeps these tests honest
      // about what the router actually sees.
      if (listener.current) throw new Error("A history only accepts one active listener");
      listener.current = fn;
      return () => {
        listener.current = null;
      };
    },
  };
  return {
    base,
    calls,
    seen,
    pop(delta: number | null) {
      listener.current?.({ action: "POP", location: { pathname: "/next" }, delta });
    },
  };
}

function setup(dirty: boolean) {
  const registry = new UnsavedRegistry();
  const navigation = new PendingNavigationStore(registry);
  const fake = fakeHistory();
  const guarded = createGuardedHistory(fake.base, registry, navigation);
  guarded.listen((u) => fake.seen.push(u));
  if (dirty) registry.register({ id: "a", label: "the persona" });
  return { registry, navigation, fake, guarded };
}

describe("createGuardedHistory — clean dashboard", () => {
  it("passes push, replace and go straight through", () => {
    const { fake, guarded } = setup(false);
    guarded.push("/config" as never);
    guarded.replace("/cron" as never, { a: 1 });
    guarded.go(2);
    expect(fake.calls.push).toEqual([["/config", undefined]]);
    expect(fake.calls.replace).toEqual([["/cron", { a: 1 }]]);
    expect(fake.calls.go).toEqual([2]);
  });

  it("never blocks a popstate when nothing is dirty", () => {
    const { fake } = setup(false);
    fake.pop(-1);
    expect(fake.seen).toHaveLength(1);
    expect(fake.calls.go).toEqual([]);
  });
});

describe("createGuardedHistory — dirty dashboard", () => {
  it("holds a push instead of performing it", () => {
    const { fake, guarded, navigation } = setup(true);
    guarded.push("/config" as never);
    expect(fake.calls.push).toEqual([]);
    navigation.proceed();
    expect(fake.calls.push).toEqual([["/config", undefined]]);
  });

  it("holds a replace", () => {
    const { fake, guarded, navigation } = setup(true);
    guarded.replace("/cron" as never);
    expect(fake.calls.replace).toEqual([]);
    navigation.proceed();
    expect(fake.calls.replace).toEqual([["/cron", undefined]]);
  });

  it("holds an explicit go (navigate(-1))", () => {
    const { fake, guarded, navigation } = setup(true);
    guarded.go(-1);
    expect(fake.calls.go).toEqual([]);
    navigation.proceed();
    expect(fake.calls.go).toEqual([-1]);
  });

  it("lets go(0) through — a reload of the current entry destroys nothing", () => {
    const { fake, guarded } = setup(true);
    guarded.go(0);
    expect(fake.calls.go).toEqual([0]);
  });

  it("blocks a popstate, walks the history back, and never tells the router", () => {
    const { fake, navigation } = setup(true);

    fake.pop(-1);

    // The URL was already changed by the browser; put it back.
    expect(fake.calls.go).toEqual([1]);
    // The router is still on the page the user was editing.
    expect(fake.seen).toEqual([]);
    expect(navigation.hasPending()).toBe(true);
  });

  it("replays the original direction when the user then chooses to leave", () => {
    const { fake, navigation } = setup(true);
    fake.pop(-1);
    navigation.proceed();
    expect(fake.calls.go).toEqual([1, -1]);
  });

  it("swallows the popstate produced by its own undo instead of blocking it again", () => {
    const { fake, navigation } = setup(true);

    fake.pop(-1);
    // Still dirty, and the restore fires its own popstate.
    fake.pop(1);
    // Not forwarded: the router was never told about the move we blocked, so it still holds the old
    // location, and re-rendering it accomplishes nothing. This is also what keeps `restoring` from
    // behaving like a time window — see the rapid-back test below.
    expect(fake.seen).toEqual([]);
    expect(navigation.hasPending()).toBe(true);
  });

  it("does not let a second back-press escape through while a restore is in flight", () => {
    // The bug: `restoring` used to be treated as a window rather than as "the popstate I caused",
    // so a second POP arriving before the restore landed consumed the flag, was forwarded to the
    // router, and navigated away from a dirty page with no prompt at all.
    const { fake } = setup(true);

    fake.pop(-1); // blocked, queues a restore
    fake.pop(-1); // a second back-press, arriving before that restore
    expect(fake.seen).toEqual([]);
  });

  it("a same-entry pop (delta 0) is forwarded, not blocked into a reload", () => {
    // `history.go(0)` is a document reload by spec, so blocking a delta-0 POP and calling `go(-0)`
    // would reload the page with the router never told and a navigation held.
    const { fake, navigation } = setup(true);
    fake.pop(0);
    expect(fake.calls.go).toEqual([]);
    expect(fake.seen).toHaveLength(1);
    expect(navigation.hasPending()).toBe(false);
  });

  it("a rapid double-back replays only one navigation", () => {
    // Two back-presses: the first is blocked and restores; the second arrives while `restoring` and
    // is swallowed rather than becoming a second held navigation with a confusing resume.
    const { fake, navigation } = setup(true);
    fake.pop(-1);
    fake.pop(-1);
    expect(navigation.hasPending()).toBe(true);
    navigation.proceed();
    expect(fake.calls.go).toEqual([1, -1]);
  });

  it("forwards a popstate it cannot measure (no delta) rather than stranding the URL", () => {
    const { fake, navigation } = setup(true);

    // react-router reports `delta: null` when the history entry carries no `idx` — e.g. a landing
    // page reached from outside the SPA. There is no distance to walk back, so blocking would leave
    // the URL and the rendered page disagreeing with nothing to undo it. Letting it through is the
    // only honest option; beforeunload and the remaining guards still cover the reload case.
    fake.pop(null);
    expect(fake.seen).toHaveLength(1);
    expect(fake.calls.go).toEqual([]);
    expect(navigation.hasPending()).toBe(false);
  });

  it("stops blocking once the surface is clean again", () => {
    const { registry, fake, guarded } = setup(true);

    // Clean the registry the way a successful save would.
    registry.discardAll();
    registry.unregister("a");
    guarded.push("/config" as never);
    expect(fake.calls.push).toEqual([["/config", undefined]]);
  });

  it("stops treating a popstate as blocking after the surface unregisters", () => {
    const { registry, fake } = setup(true);
    registry.unregister("a");
    fake.pop(-1);
    expect(fake.seen).toHaveLength(1);
    expect(fake.calls.go).toEqual([]);
  });
});

describe("createGuardedHistory — passthrough surface", () => {
  it("delegates href/URL construction untouched", () => {
    const createHref = vi.fn(() => "/href");
    const createURL = vi.fn(() => new URL("http://localhost/x"));
    const encodeLocation = vi.fn(() => ({ pathname: "/x", search: "", hash: "" }));
    const base: RoutableHistory = {
      action: "POP",
      location: null,
      createHref: createHref as never,
      createURL: createURL as never,
      encodeLocation: encodeLocation as never,
      push: () => {},
      replace: () => {},
      go: () => {},
      listen: () => () => {},
    };
    const guarded = createGuardedHistory(
      base,
      new UnsavedRegistry(),
      new PendingNavigationStore(new UnsavedRegistry()),
    );
    expect(guarded.createHref("/a" as never)).toBe("/href");
    expect(guarded.createURL("/a" as never).pathname).toBe("/x");
    expect(guarded.encodeLocation("/a" as never).pathname).toBe("/x");
    expect(createHref).toHaveBeenCalledOnce();
    expect(createURL).toHaveBeenCalledOnce();
    expect(encodeLocation).toHaveBeenCalledOnce();
  });
});
