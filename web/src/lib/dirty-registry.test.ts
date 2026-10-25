/**
 * The registry is the thing that decides "is there work at risk", so it is tested without React.
 *
 * What these pin, beyond the obvious bookkeeping:
 * - `register()` replacing by id (a re-render must not leave two entries for one form),
 * - a stale unregister not deleting a *live* entry that replaced it,
 * - `saveAll()` refusing to continue when a surface fails to save — the whole point of the guard is
 *   that it never becomes the reason work is lost.
 */

import { describe, expect, it, vi } from "vitest";

import { PendingNavigationStore, UnsavedRegistry } from "./dirty-registry";

/** A registry wired to its own navigation store, the way `main.tsx` wires the singletons. */
function pair() {
  const registry = new UnsavedRegistry();
  const navigation = new PendingNavigationStore(registry);
  return { registry, navigation };
}

describe("UnsavedRegistry", () => {
  it("is clean until something registers", () => {
    const { registry } = pair();
    expect(registry.isDirty()).toBe(false);
    expect(registry.list()).toEqual([]);
  });

  it("reports dirty while a surface is registered and clean once it unregisters", () => {
    const { registry } = pair();
    const release = registry.register({ id: "soul", label: "the persona" });
    expect(registry.isDirty()).toBe(true);
    release();
    expect(registry.isDirty()).toBe(false);
  });

  it("replaces an entry registered twice under one id instead of duplicating it", () => {
    const { registry } = pair();
    const second = vi.fn();
    registry.register({ id: "soul", label: "stale" });
    registry.register({ id: "soul", label: "the persona", onSave: second });
    expect(registry.size).toBe(1);
    expect(registry.list()[0].label).toBe("the persona");
  });

  it("does not let a stale unregister delete the entry that replaced it", () => {
    const { registry } = pair();
    const releaseOld = registry.register({ id: "soul", label: "old" });
    registry.register({ id: "soul", label: "new" });
    // A remount registers the new entry before React runs the old effect's cleanup.
    releaseOld();
    expect(registry.isDirty()).toBe(true);
    expect(registry.list()[0].label).toBe("new");
  });

  it("runs every save in registration order", async () => {
    const { registry } = pair();
    const order: string[] = [];
    registry.register({ id: "a", label: "a", onSave: () => void order.push("a") });
    registry.register({ id: "b", label: "b", onSave: async () => void order.push("b") });
    expect(await registry.saveAll()).toBe(true);
    expect(order).toEqual(["a", "b"]);
  });

  it("refuses a partial save when another dirty surface has no save action", async () => {
    const { registry } = pair();
    const save = vi.fn();
    registry.register({ id: "config", label: "config", onSave: save });
    registry.register({ id: "wizard", label: "new profile" });
    expect(await registry.saveAll()).toBe(false);
    expect(save).not.toHaveBeenCalled();
  });

  it("reports failure when a save RETURNS false, not only when it throws", async () => {
    // The case that actually bit: every real handler catches its own error to show a toast, so it
    // returns normally. A throw-only contract would be satisfied by a save that failed, and the
    // guard would navigate away having persisted nothing.
    const { registry } = pair();
    registry.register({ id: "a", label: "a", onSave: () => false });
    expect(await registry.saveAll()).toBe(false);
  });

  it("reports failure when an async save resolves to false", async () => {
    const { registry } = pair();
    registry.register({ id: "a", label: "a", onSave: async () => false });
    expect(await registry.saveAll()).toBe(false);
  });

  it("treats a void save as success", async () => {
    const { registry } = pair();
    registry.register({ id: "a", label: "a", onSave: () => {} });
    expect(await registry.saveAll()).toBe(true);
  });

  it("stops and reports failure when a save rejects, so no navigation proceeds", async () => {
    const { registry } = pair();
    const after = vi.fn();
    registry.register({
      id: "a",
      label: "a",
      onSave: () => {
        throw new Error("disk full");
      },
    });
    registry.register({ id: "b", label: "b", onSave: after });
    expect(await registry.saveAll()).toBe(false);
    expect(after).not.toHaveBeenCalled();
  });

  it("awaits an async save before declaring success", async () => {
    const { registry } = pair();
    let done = false;
    registry.register({
      id: "a",
      label: "a",
      onSave: async () => {
        await new Promise((r) => setTimeout(r, 5));
        done = true;
      },
    });
    expect(await registry.saveAll()).toBe(true);
    expect(done).toBe(true);
  });

  it("discards every surface", () => {
    const { registry } = pair();
    const a = vi.fn();
    const b = vi.fn();
    registry.register({ id: "a", label: "a", onDiscard: a });
    registry.register({ id: "b", label: "b", onDiscard: b });
    registry.discardAll();
    expect(a).toHaveBeenCalledOnce();
    expect(b).toHaveBeenCalledOnce();
  });

  it("keeps its snapshot referentially stable until the entries actually change", () => {
    // `useSyncExternalStore` compares by identity. A fresh array per call would either spin or miss
    // the change; a stable one is what makes the subscription correct.
    const { registry } = pair();
    const before = registry.getSnapshot();
    expect(registry.getSnapshot()).toBe(before);

    const release = registry.register({ id: "a", label: "a" });
    const withEntry = registry.getSnapshot();
    expect(withEntry).not.toBe(before);
    expect(withEntry.map((e) => e.label)).toEqual(["a"]);

    // Re-registering the same id replaces the entry — a new snapshot, because the entry object
    // differs. The *first* release is now a no-op (it does not own the live entry any more)...
    const releaseReplacement = registry.register({ id: "a", label: "a" });
    expect(registry.getSnapshot()).not.toBe(withEntry);
    release();
    expect(registry.getSnapshot()).toHaveLength(1);

    // ...and only the current owner's release removes it.
    releaseReplacement();
    expect(registry.getSnapshot()).toEqual([]);
  });

  it("does not notify when a re-registration changes nothing", () => {
    const { registry } = pair();
    const entry = { id: "a", label: "a" };
    registry.register(entry);
    const listener = vi.fn();
    registry.subscribe(listener);
    // Same object back in: no observable change, so no notification and no wasted render.
    const release = registry.register(entry);
    expect(listener).not.toHaveBeenCalled();
    release();
  });

  it("notifies subscribers on every change and stops after unsubscribe", () => {
    const { registry } = pair();
    const listener = vi.fn();
    const unsubscribe = registry.subscribe(listener);
    const release = registry.register({ id: "a", label: "a" });
    expect(listener).toHaveBeenCalledTimes(1);
    release();
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    registry.register({ id: "b", label: "b" });
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

describe("PendingNavigationStore", () => {
  it("a completed save cannot resume a new request made after Stay", () => {
    const { registry, navigation } = pair();
    registry.register({ id: "soul", label: "persona" });
    const first = vi.fn();
    const second = vi.fn();
    navigation.request(first);
    const revision = navigation.getRevision();
    navigation.cancel();
    navigation.request(second);
    navigation.proceed(revision);
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();
    expect(navigation.hasPending()).toBe(true);
    navigation.proceed();
    expect(second).toHaveBeenCalledOnce();
  });
  it("runs the navigation immediately when nothing is dirty", () => {
    const { navigation } = pair();
    const resume = vi.fn();
    expect(navigation.request(resume)).toBe(true);
    expect(resume).toHaveBeenCalledOnce();
    expect(navigation.hasPending()).toBe(false);
  });

  it("holds the navigation when something is dirty", () => {
    const { registry, navigation } = pair();
    registry.register({ id: "a", label: "a" });
    const resume = vi.fn();
    expect(navigation.request(resume)).toBe(false);
    expect(resume).not.toHaveBeenCalled();
    expect(navigation.hasPending()).toBe(true);
  });

  it("proceeds and clears, so a held navigation cannot be replayed twice", () => {
    const { registry, navigation } = pair();
    registry.register({ id: "a", label: "a" });
    const resume = vi.fn();
    navigation.request(resume);
    navigation.proceed();
    navigation.proceed();
    expect(resume).toHaveBeenCalledOnce();
    expect(navigation.hasPending()).toBe(false);
  });

  it("cancel drops the navigation without running it", () => {
    const { registry, navigation } = pair();
    registry.register({ id: "a", label: "a" });
    const resume = vi.fn();
    navigation.request(resume);
    navigation.cancel();
    expect(resume).not.toHaveBeenCalled();
    expect(navigation.hasPending()).toBe(false);
  });

  it("refuses a second request while one is pending, keeping the first", () => {
    // Pressing back and then clicking a sidebar link would otherwise drop the back silently and
    // offer the user the link — still asked, but about the wrong navigation. The first request is the
    // one they took, so it is the one held.
    const { registry, navigation } = pair();
    registry.register({ id: "a", label: "a" });
    const first = vi.fn();
    const second = vi.fn();
    expect(navigation.request(first)).toBe(false);
    expect(navigation.request(second)).toBe(false);
    navigation.proceed();
    expect(first).toHaveBeenCalledOnce();
    expect(second).not.toHaveBeenCalled();
  });

  it("flips its snapshot so a subscriber re-renders when a navigation is held", () => {
    const { registry, navigation } = pair();
    const listener = vi.fn();
    navigation.subscribe(listener);
    expect(navigation.getSnapshot()).toBe(false);
    registry.register({ id: "a", label: "a" });
    navigation.request(() => {});
    expect(navigation.getSnapshot()).toBe(true);
    expect(listener).toHaveBeenCalled();
    navigation.proceed();
    expect(navigation.getSnapshot()).toBe(false);
  });
});
