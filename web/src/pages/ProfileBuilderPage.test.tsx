// @vitest-environment jsdom
/**
 * The profile wizard's unsaved-changes guard.
 *
 * Two ways the five steps used to be lost, both of which the guarded history alone cannot catch:
 * browser-back (caught, because `go` runs through the history) and a **profile switch**, which
 * remounts the entire routed tree via `ProfileKeyedRoutes` and never calls `history.push` at all.
 * The wizard's own Cancel button is a third.
 *
 * The dirty baseline matters most here: three of the wizard's fields are search boxes
 * (`modelFilter`, `skillFilter`, `hubQuery`) that only narrow what is on screen and never become
 * part of the profile. If they counted, typing a model name would arm a leave-prompt for work that
 * does not exist.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { isDraftDirty, useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import { PendingNavigationStore, UnsavedRegistry, unsavedRegistry } from "@/lib/dirty-registry";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

/** Mirror of `EMPTY_DRAFT` in ProfileBuilderPage. */
const EMPTY = {
  name: "",
  description: "",
  modelChoice: "",
  keepAll: true,
  keptSkills: [] as string[],
  hubSkills: [] as string[],
  mcpServers: [] as unknown[],
  mcpDraft: {
    name: "",
    transport: "http",
    url: "",
    httpAuth: "none",
    bearerToken: "",
    command: "",
    args: "",
    env: "",
  },
};

describe("profile wizard dirty baseline", () => {
  it("a wizard the user has only clicked through is not dirty", () => {
    expect(isDraftDirty({ ...EMPTY }, EMPTY)).toBe(false);
  });

  it("is dirty after typing a name", () => {
    expect(isDraftDirty({ ...EMPTY, name: "coder" }, EMPTY)).toBe(true);
  });

  it("is dirty after typing a description", () => {
    expect(isDraftDirty({ ...EMPTY, description: "reviews PRs" }, EMPTY)).toBe(true);
  });

  it("is dirty after picking a model", () => {
    expect(isDraftDirty({ ...EMPTY, modelChoice: "openai\u0000gpt-4o-mini" }, EMPTY)).toBe(true);
  });

  it("is dirty after toggling the keep-all skills switch off", () => {
    expect(isDraftDirty({ ...EMPTY, keepAll: false }, EMPTY)).toBe(true);
  });

  it("is dirty after deselecting skills under keep-all=false", () => {
    expect(isDraftDirty({ ...EMPTY, keepAll: false, keptSkills: ["skill-a"] }, EMPTY)).toBe(true);
  });

  it("is dirty after adding an MCP server", () => {
    expect(isDraftDirty({ ...EMPTY, mcpServers: [{ name: "linear" }] }, EMPTY)).toBe(true);
  });

  it("is dirty while an MCP server is still being composed", () => {
    expect(
      isDraftDirty(
        { ...EMPTY, mcpDraft: { ...EMPTY.mcpDraft, name: "linear", url: "https://mcp.example" } },
        EMPTY,
      ),
    ).toBe(true);
  });

  it("normalises the kept-skill list so click order is not an edit", () => {
    // `keptSkills` is a Set, so its iteration order follows click sequence rather than intent. The
    // page sorts it into the draft before comparing, so the same selection reached by different
    // click orders has to produce an identical draft. Pinning the sort here is what stops that from
    // regressing into a bar that reappears on every re-render.
    const build = (order: string[]) => ({
      ...EMPTY,
      keepAll: false,
      keptSkills: [...order].sort(),
    });
    expect(isDraftDirty(build(["c", "a", "b"]), build(["a", "b", "c"]))).toBe(false);
    expect(["c", "a", "b"]).not.toEqual(["a", "b", "c"]);
  });

  it("is clean again once every field is reset", () => {
    // The bar's Discard rewinds each field; the draft is then value-equal to the wizard's initial
    // state, which is the only baseline this page has — nothing is loaded from the server here.
    const edited = { ...EMPTY, name: "coder", keepAll: false, keptSkills: ["a"] };
    const rewound = { ...EMPTY, name: "", keepAll: true, keptSkills: [] };
    expect(isDraftDirty(edited, EMPTY)).toBe(true);
    expect(isDraftDirty(rewound, EMPTY)).toBe(false);
  });
});

describe("profile wizard guard", () => {
  function Wizard(props: { dirty: boolean }) {
    useUnsavedChanges({
      id: "profile-wizard",
      label: "this new profile",
      dirty: props.dirty,
      onDiscard: () => {},
      registry: unsavedRegistry,
    });
    return <span>wizard</span>;
  }

  async function render(ui: React.ReactNode) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(ui));
  }

  it("holds a guard with no save handler, because the wizard has nothing to commit yet", async () => {
    await render(<Wizard dirty />);
    const entry = unsavedRegistry.list()[0];
    expect(entry.label).toBe("this new profile");
    // Nothing on the page is persisted until Create, and Create needs a valid name — so there is no
    // honest Save to offer. The guard still has to hold, because Discard is always available.
    expect(entry.onSave).toBeUndefined();
    expect(typeof entry.onDiscard).toBe("function");
  });

  it("does not report success when a save-less entry is dirty", async () => {
    await render(<Wizard dirty />);
    expect(await unsavedRegistry.saveAll()).toBe(false);
    // Still dirty: nothing was written, and pretending otherwise would let the user navigate away
    // from a wizard that has not been committed.
    expect(unsavedRegistry.isDirty()).toBe(true);
  });

  it("releases on unmount when the profile is created", async () => {
    await render(<Wizard dirty />);
    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => root.render(<span>gone</span>));
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("the profile switch is held behind the same prompt", async () => {
    // `ProfileSwitcher` calls requestLeave, which is `PendingNavigationStore.request` — the same
    // channel the guarded history uses, so the same bar answers both.
    const registry = new UnsavedRegistry();
    const navigation = new PendingNavigationStore(registry);
    const setProfile = vi.fn();

    registry.register({ id: "profile-wizard", label: "this new profile" });
    expect(navigation.request(setProfile)).toBe(false);
    expect(setProfile).not.toHaveBeenCalled();

    navigation.proceed();
    expect(setProfile).toHaveBeenCalledOnce();
  });

  it("keeps a partially composed MCP draft in the real wizard's guarded state", async () => {
    const [{ default: ProfileBuilderPage }, { I18nProvider }, { UnsavedChangesProvider }, { MemoryRouter }] =
      await Promise.all([
        import("./ProfileBuilderPage"),
        import("@/i18n"),
        import("@/contexts/UnsavedChanges"),
        import("react-router"),
      ]);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () =>
      root.render(
        <UnsavedChangesProvider>
          <I18nProvider>
            <MemoryRouter>
              <ProfileBuilderPage />
            </MemoryRouter>
          </I18nProvider>
        </UnsavedChangesProvider>,
      ),
    );

    const name = document.querySelector("#pb-name") as HTMLInputElement;
    const setInput = (input: HTMLInputElement, value: string) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    await act(async () => setInput(name, "my-profile"));
    const mcpStep = [...document.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").includes("4. MCPs"),
    ) as HTMLButtonElement | undefined;
    expect(mcpStep?.disabled).toBe(false);
    await act(async () => mcpStep?.dispatchEvent(new MouseEvent("click", { bubbles: true })));

    const serverName = document.querySelector("#pb-mcp-name") as HTMLInputElement;
    await act(async () => setInput(serverName, "linear"));
    expect(serverName.value).toBe("linear");
    expect(unsavedRegistry.isDirty()).toBe(true);
    expect(document.querySelector('[data-unsaved-guard]')).not.toBeNull();
  });
});
