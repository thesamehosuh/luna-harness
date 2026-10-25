// @vitest-environment jsdom
/**
 * The gate this phase was written for: **a dirty form blocks navigation**, and a clean one does not.
 *
 * Before it, `grep 'beforeunload|isDirty|unsaved' web/src` returned one hit and it was a comment —
 * nothing stopped a nav from destroying the persona, the raw YAML, the wake policy, a composed cron
 * job or the five-step profile wizard. So these assertions are deliberately end-to-end rather than
 * per-unit: hook → registry → provider → DirtyBar → the decision the user makes with it. A unit test
 * of the registry alone would pass while the wiring that makes it matter stayed broken.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";

// The other .tsx suites get this from a shared setup; there isn't one, so declare it here before
// rendering — otherwise every act() below warns and the assertions race the commit.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  PendingNavigationStore,
  UnsavedRegistry,
  pendingNavigation,
  unsavedRegistry,
} from "@/lib/dirty-registry";
import { UnsavedChangesProvider } from "@/contexts/UnsavedChanges";
import {
  createGuardedHistory,
  type HistoryUpdate,
  type RoutableHistory,
} from "@/lib/guarded-history";
import { DirtyBar } from "@/components/DirtyBar";
import { dirtyBarLabels } from "@/lib/dirty-bar-copy";
import { useUnsavedChanges, isDraftDirty } from "@/hooks/useUnsavedChanges";

let container: HTMLDivElement;
let root: Root;

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(ui));
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  pendingNavigation.cancel();
});

const click = (el: Element | null | undefined) => {
  if (!el) throw new Error("element not found");
  el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
};

const buttonNamed = (text: string) =>
  [...container.querySelectorAll("button")].find((b) =>
    (b.textContent ?? "").trim().toLowerCase().startsWith(text.toLowerCase()),
  );

/**
 * A form that registers itself as dirty, plus the three decisions the bar offers — the same wiring
 * `UnsavedChangesProvider` uses, against an injected registry so each test gets a clean pair.
 */
function DirtyForm(props: {
  registry: UnsavedRegistry;
  navigation: PendingNavigationStore;
  label?: string;
  onSave?: () => void | boolean | Promise<void | boolean>;
  onDiscard?: () => void;
  id?: string;
  dirty?: boolean;
}) {
  const { registry, navigation } = props;
  useUnsavedChanges({
    id: props.id ?? "test-form",
    label: props.label ?? "the persona",
    dirty: props.dirty ?? true,
    onSave: props.onSave,
    onDiscard: props.onDiscard,
    registry,
  });

  // Subscribe the way the provider does, so the bar re-renders when a navigation is held or resolved.
  const entries = useSyncExternalStore(
    registry.subscribe,
    registry.getSnapshot,
    registry.getSnapshot,
  );
  const pending = useSyncExternalStore(
    navigation.subscribe,
    navigation.getSnapshot,
    navigation.getSnapshot,
  );

  return (
    <DirtyBar
      labels={entries.map((e) => e.label)}
      pending={pending}
      onSave={() => {
        void registry.saveAll().then((ok) => {
          if (ok) navigation.proceed();
        });
      }}
      onDiscard={() => {
        registry.discardAll();
        navigation.proceed();
      }}
      onStay={() => navigation.cancel()}
    />
  );
}

function makeHistory() {
  const state = { listener: null as ((u: HistoryUpdate) => void) | null };
  const calls = { push: [] as unknown[], replace: [] as unknown[], go: [] as number[] };
  const base: RoutableHistory = {
    action: "POP",
    location: { pathname: "/character" },
    createHref: (() => "/href") as never,
    createURL: (() => new URL("http://localhost/")) as never,
    encodeLocation: (() => ({ pathname: "/", search: "", hash: "" })) as never,
    push: (to) => void calls.push.push([to]),
    replace: (to) => void calls.replace.push([to]),
    go: (d) => void calls.go.push(d),
    listen: (fn) => {
      if (state.listener) throw new Error("A history only accepts one active listener");
      state.listener = fn;
      return () => {
        state.listener = null;
      };
    },
  };
  return {
    base,
    calls,
    pop: (delta: number | null) =>
      state.listener?.({
        action: "POP",
        location: { pathname: "/next" },
        delta,
      }),
  };
}

/** The full app seam: a dirty form, a guarded history, and the bar the user acts on. */
async function renderApp(
  options: {
    dirty?: boolean;
    label?: string;
    /** Mirrors the real contract, so a test cannot pass with a signature the app never uses. */
    onSave?: () => void | boolean | Promise<void | boolean>;
    onDiscard?: () => void;
  } = {},
) {
  const registry = new UnsavedRegistry();
  const navigation = new PendingNavigationStore(registry);
  const fake = makeHistory();
  const guarded = createGuardedHistory(fake.base, registry, navigation);
  // Stand in for the router: `HistoryRouter` subscribes to exactly this, and a POP only reaches the
  // guard through `listen`. Without a listener the fake's popstate has nowhere to go.
  const routerUpdates: HistoryUpdate[] = [];
  guarded.listen((u) => routerUpdates.push(u));
  await render(
    <DirtyForm
      registry={registry}
      navigation={navigation}
      dirty={options.dirty}
      label={options.label}
      onSave={options.onSave}
      onDiscard={options.onDiscard}
    />,
  );
  return { registry, navigation, fake, guarded, routerUpdates };
}

describe("dirty forms block navigation", () => {
  it("a push from a dirty form does not reach the history", async () => {
    const { guarded, fake } = await renderApp();
    await act(async () => guarded.push("/config" as never));
    expect(fake.calls.push).toEqual([]);
  });

  it("a browser-back from a dirty form does not move the router, and the URL is restored", async () => {
    const { fake, routerUpdates } = await renderApp();
    await act(async () => fake.pop(-1));
    expect(fake.calls.go).toEqual([1]);
    expect(routerUpdates).toEqual([]);
  });

  it("the bar offers Save / Discard / Stay while a navigation is held", async () => {
    const { guarded, navigation } = await renderApp();
    await act(async () => guarded.push("/config" as never));
    expect(navigation.hasPending()).toBe(true);
    expect(container.querySelector('[data-pending="true"]')).not.toBeNull();
    expect(buttonNamed("Save and leave")).toBeTruthy();
    expect(buttonNamed("Discard and leave")).toBeTruthy();
    expect(buttonNamed("Stay")).toBeTruthy();
  });

  it("Stay drops the held navigation and stays on the page", async () => {
    const { guarded, navigation, fake } = await renderApp();
    await act(async () => guarded.push("/config" as never));
    await act(async () => click(buttonNamed("Stay")));
    expect(navigation.hasPending()).toBe(false);
    expect(fake.calls.push).toEqual([]);
  });

  it("Save commits the edit and then performs the navigation", async () => {
    const onSave = vi.fn();
    const { guarded, navigation, fake } = await renderApp({ onSave });
    await act(async () => guarded.push("/config" as never));
    await act(async () => click(buttonNamed("Save and leave")));
    expect(onSave).toHaveBeenCalledOnce();
    expect(fake.calls.push).toEqual([["/config"]]);
    expect(navigation.hasPending()).toBe(false);
  });

  it("an async save is awaited before the navigation happens", async () => {
    // Ordering matters: navigating first and saving after would destroy exactly the state the guard
    // exists to protect, and the page unmounts before the write lands.
    const order: string[] = [];
    let releaseSave = () => {};
    const { guarded, fake } = await renderApp({
      onSave: () =>
        new Promise<void>((resolve) => {
          releaseSave = () => {
            order.push("saved");
            resolve();
          };
        }),
    });
    await act(async () => guarded.push("/config" as never));
    await act(async () => click(buttonNamed("Save and leave")));
    // The click returned but the save has not resolved: nothing may have navigated.
    order.push("clicked");
    expect(order).toEqual(["clicked"]);
    expect(fake.calls.push).toEqual([]);

    await act(async () => releaseSave());
    expect(fake.calls.push).toEqual([["/config"]]);
    expect(order).toEqual(["clicked", "saved"]);
  });

  it("Discard throws the edit away and performs the navigation", async () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();
    const { guarded, navigation, fake } = await renderApp({ onSave, onDiscard });
    await act(async () => guarded.push("/config" as never));
    await act(async () => click(buttonNamed("Discard and leave")));
    expect(onDiscard).toHaveBeenCalledOnce();
    expect(onSave).not.toHaveBeenCalled();
    expect(fake.calls.push).toEqual([["/config"]]);
    expect(navigation.hasPending()).toBe(false);
  });

  it("a save that RETURNS false does not navigate — the real-world failure mode", async () => {
    // Every real handler catches its own error to show a toast, so it *returns* rather than throws.
    // A throw-only contract is therefore satisfied by a save that failed, and the guard navigates
    // away having persisted nothing. This is the test whose absence hid that.
    const onSave = vi.fn(() => false);
    const { guarded, navigation, fake } = await renderApp({ onSave });
    await act(async () => guarded.push("/config" as never));
    await act(async () => click(buttonNamed("Save and leave")));
    expect(onSave).toHaveBeenCalledOnce();
    expect(fake.calls.push).toEqual([]);
    expect(navigation.hasPending()).toBe(true);
  });

  it("a save that resolves false after a delay also holds the navigation", async () => {
    let release = () => {};
    const { guarded, fake } = await renderApp({
      onSave: () =>
        new Promise<boolean>((resolve) => {
          release = () => resolve(false);
        }),
    });
    await act(async () => guarded.push("/config" as never));
    await act(async () => click(buttonNamed("Save and leave")));
    expect(fake.calls.push).toEqual([]);
    await act(async () => release());
    expect(fake.calls.push).toEqual([]);
  });

  it("a failed save does NOT navigate — that would lose the very work being protected", async () => {
    const onSave = vi.fn(() => {
      throw new Error("config.yaml is read-only");
    });
    const { guarded, navigation, fake } = await renderApp({ onSave });
    await act(async () => guarded.push("/config" as never));
    await act(async () => click(buttonNamed("Save and leave")));
    expect(fake.calls.push).toEqual([]);
    expect(navigation.hasPending()).toBe(true);
  });

  it("a browser-back is replayed once the user chooses to leave", async () => {
    const { navigation, fake } = await renderApp({ onSave: vi.fn() });
    await act(async () => fake.pop(-1));
    expect(navigation.hasPending()).toBe(true);
    await act(async () => click(buttonNamed("Save and leave")));
    // Restored with +1, then the original back navigation was allowed through.
    expect(fake.calls.go).toEqual([1, -1]);
  });

  it("a profile switch (no history involvement) is held too", async () => {
    const { registry, navigation } = await renderApp();
    // `ProfileKeyedRoutes` remounts the tree on a profile switch, which never reaches history.
    const setProfile = vi.fn();
    await act(async () => {
      navigation.request(setProfile);
    });
    expect(setProfile).not.toHaveBeenCalled();
    await act(async () => click(buttonNamed("Stay")));
    expect(setProfile).not.toHaveBeenCalled();
    expect(registry.isDirty()).toBe(true);
  });
});

describe("a surface with nothing to save cannot be saved away", () => {
  it("reserves the guard's measured height and releases it when the form becomes clean", async () => {
    let height = 64;
    let resized: () => void = () => {};
    const disconnect = vi.fn();
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: () => void) { resized = callback; }
      observe() {}
      disconnect = disconnect;
    });
    const bounds = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(() => new DOMRect(0, 0, 300, height));
    function Form({ dirty }: { dirty: boolean }) {
      useUnsavedChanges({ id: "measured-form", label: "config", dirty, onSave: () => true });
      return null;
    }
    try {
      await render(<UnsavedChangesProvider><Form dirty /></UnsavedChangesProvider>);
      expect(document.documentElement.style.getPropertyValue("--unsaved-bar-height")).toBe("64px");
      height = 144;
      await act(async () => resized());
      expect(document.documentElement.style.getPropertyValue("--unsaved-bar-height")).toBe("144px");
      await act(async () => root.render(<UnsavedChangesProvider><Form dirty={false} /></UnsavedChangesProvider>));
      expect(document.documentElement.style.getPropertyValue("--unsaved-bar-height")).toBe("");
      expect(disconnect).toHaveBeenCalledOnce();
    } finally {
      bounds.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("the real provider omits Save when any dirty surface has no save action", async () => {
    function Forms() {
      useUnsavedChanges({ id: "saveable", label: "config", dirty: true, onSave: vi.fn() });
      useUnsavedChanges({ id: "wizard", label: "new profile", dirty: true });
      return null;
    }
    await render(<UnsavedChangesProvider><Forms /></UnsavedChangesProvider>);
    expect(unsavedRegistry.size).toBe(2);
    expect(buttonNamed("Save")).toBeUndefined();
    const leave = vi.fn();
    await act(async () => { pendingNavigation.request(leave); });
    expect(buttonNamed("Save and leave")).toBeUndefined();
    await act(async () => click(buttonNamed("Discard and leave")));
    expect(leave).toHaveBeenCalledOnce();
  });

  it("Stay prevents a delayed save from resuming a later navigation", async () => {
    let finish = () => {};
    function Form() {
      useUnsavedChanges({
        id: "slow-save", label: "config", dirty: true,
        onSave: () => new Promise<boolean>((resolve) => { finish = () => resolve(true); }),
      });
      return null;
    }
    await render(<UnsavedChangesProvider><Form /></UnsavedChangesProvider>);
    const first = vi.fn();
    const second = vi.fn();
    await act(async () => { pendingNavigation.request(first); });
    await act(async () => click(buttonNamed("Save and leave")));
    await act(async () => click(buttonNamed("Stay")));
    await act(async () => { pendingNavigation.request(second); });
    await act(async () => finish());
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();
    expect(pendingNavigation.hasPending()).toBe(true);
  });

  it("offers no Save when no registered surface can save", async () => {
    // The profile wizard's steps are only persisted by Create. `saveAll` used to skip such an entry
    // and report success, so "Save and leave" discarded five steps under a label promising to keep
    // them — and the non-pending Save was a dead button.
    const registry = new UnsavedRegistry();
    const navigation = new PendingNavigationStore(registry);

    function Wizard() {
      useUnsavedChanges({
        id: "wizard",
        label: "this new profile",
        dirty: true,
        onSave: undefined,
        registry,
      });
      const entries = useSyncExternalStore(
        registry.subscribe,
        registry.getSnapshot,
        registry.getSnapshot,
      );
      const pending = useSyncExternalStore(
        navigation.subscribe,
        navigation.getSnapshot,
        navigation.getSnapshot,
      );
      return (
        <DirtyBar
          labels={entries.map((e) => e.label)}
          pending={pending}
          canSave={entries.some((e) => e.onSave)}
          onSave={() => void registry.saveAll().then((ok) => ok && navigation.proceed())}
          onDiscard={() => {
            registry.discardAll();
            navigation.proceed();
          }}
          onStay={() => navigation.cancel()}
        />
      );
    }

    await render(<Wizard />);
    expect(buttonNamed("Save")).toBeUndefined();

    const resume = vi.fn();
    await act(async () => navigation.request(resume));
    await act(async () => {});
    expect(resume).not.toHaveBeenCalled();
    // Discard is still offered, and still works — it is the one action this surface can honour.
    await act(async () => click(buttonNamed("Discard and leave")));
    expect(resume).toHaveBeenCalledOnce();
  });
});

describe("clean forms do not block navigation", () => {
  it("passes push through untouched", async () => {
    const { guarded, fake, navigation } = await renderApp({ dirty: false });
    await act(async () => guarded.push("/config" as never));
    expect(fake.calls.push).toEqual([["/config"]]);
    expect(navigation.hasPending()).toBe(false);
  });

  it("renders no bar at all when nothing is dirty", async () => {
    await render(
      <DirtyBar
        labels={[]}
        pending={false}
        onSave={() => {}}
        onDiscard={() => {}}
        onStay={() => {}}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("a form that becomes clean releases the guard", async () => {
    const { guarded, fake, registry } = await renderApp();
    expect(registry.isDirty()).toBe(true);
    await act(async () => root.render(<span>gone</span>));
    expect(registry.isDirty()).toBe(false);
    await act(async () => guarded.push("/config" as never));
    expect(fake.calls.push).toEqual([["/config"]]);
  });
});

describe("beforeunload", () => {
  it("prompts only while a surface is dirty", async () => {
    const registry = new UnsavedRegistry();

    function Harness() {
      const [dirty, setDirty] = useState(false);
      useUnsavedChanges({ id: "f", label: "the persona", dirty, onSave: () => {}, registry });
      // Subscribe rather than reading `isDirty()` as an effect dependency: the registry is external
      // state, so the component has to be told when it changes — exactly what the provider does.
      const dirtyCount = useSyncExternalStore(
        registry.subscribe,
        registry.getSnapshot,
        registry.getSnapshot,
      ).length;
      useEffect(() => {
        if (dirtyCount === 0 || typeof window === "undefined") return;
        const onBeforeUnload = (e: BeforeUnloadEvent) => {
          e.preventDefault();
          e.returnValue = "";
        };
        window.addEventListener("beforeunload", onBeforeUnload);
        return () => window.removeEventListener("beforeunload", onBeforeUnload);
      }, [dirtyCount]);
      return (
        <button onClick={() => setDirty((d) => !d)} data-testid="toggle">
          {dirty ? "dirty" : "clean"}
        </button>
      );
    }

    await render(<Harness />);

    const fire = () => {
      const event = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };

    // Clean: the browser is told nothing, so there is no "Leave site?" on a routine reload.
    expect(fire()).toBe(false);

    await act(async () => click(container.querySelector("[data-testid=toggle]")));
    expect(registry.isDirty()).toBe(true);
    expect(fire()).toBe(true);

    await act(async () => click(container.querySelector("[data-testid=toggle]")));
    expect(registry.isDirty()).toBe(false);
    expect(fire()).toBe(false);
  });
});

describe("isDraftDirty", () => {
  it("ignores key order", () => {
    expect(isDraftDirty({ a: 1, b: 2 }, { b: 2, a: 1 })).toBe(false);
  });

  it("sees a real value change", () => {
    expect(isDraftDirty({ a: 1 }, { a: 2 })).toBe(true);
  });

  it("treats a nested array of objects by value, not identity", () => {
    const base = { sections: [{ title: "a", body: "b" }] };
    expect(isDraftDirty({ sections: [{ title: "a", body: "b" }] }, base)).toBe(false);
    expect(isDraftDirty({ sections: [{ title: "a", body: "changed" }] }, base)).toBe(true);
  });

  it("does not report a freshly-cloned object as dirty", () => {
    // The failure mode that would make every reload nag: the page holds a copy of the server's
    // value, not the identical reference.
    const loaded = { name: "coder", tags: ["a"] };
    const draft = JSON.parse(JSON.stringify(loaded));
    expect(isDraftDirty(draft, loaded)).toBe(false);
  });

  it("sees a section added to the persona", () => {
    const loaded = { sections: [{ title: "a", body: "b" }] };
    const draft = { sections: [...loaded.sections, { title: "c", body: "d" }] };
    expect(isDraftDirty(draft, loaded)).toBe(true);
  });
});

describe("dirtyBarLabels", () => {
  it("names a single unsaved surface", () => {
    const copy = dirtyBarLabels({}, ["the persona"]);
    expect(copy.blocked).toContain("the persona");
  });

  it("collapses several into one name plus a count", () => {
    const copy = dirtyBarLabels({}, ["the persona", "wake policy"]);
    expect(copy.blocked).toContain("the persona");
    expect(copy.blocked).toContain("1 more");
  });

  it("prefers a translated label over the English fallback", () => {
    const copy = dirtyBarLabels({ unsavedStay: "Bleiben" }, []);
    expect(copy.stay).toBe("Bleiben");
  });
});
