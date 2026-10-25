// @vitest-environment jsdom
/**
 * The persona's unsaved-changes guard.
 *
 * The persona is the most expensive thing in the dashboard to lose: hours of tuning in a textarea,
 * one nav click from gone, and previously with nothing at all between the two. This pins the
 * baseline comparison — the part that decides whether the bar appears at all.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";

import { isDraftDirty, useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import { pendingNavigation, unsavedRegistry } from "@/lib/dirty-registry";

const lunaMocks = vi.hoisted(() => ({
  getCharacter: vi.fn(),
  saveCharacter: vi.fn(),
  previewShaping: vi.fn(),
  saveSkinColors: vi.fn(),
  toggleSkill: vi.fn(),
  saveOutput: vi.fn(),
  getPeers: vi.fn(),
  listIdentities: vi.fn(),
  upsertIdentity: vi.fn(),
  mergeIdentity: vi.fn(),
  syncPeers: vi.fn(),
  getAudit: vi.fn(),
  listPresets: vi.fn(),
}));

vi.mock("@/lib/luna-api", () => ({ lunaApi: lunaMocks }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const fireEvent = {
  change(element: HTMLInputElement | HTMLTextAreaElement, { target }: { target: { value: string } }) {
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, target.value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  },
};

beforeEach(() => {
  pendingNavigation.cancel();
  document.body.innerHTML = "";
  for (const fn of Object.values(lunaMocks)) fn.mockReset();
  lunaMocks.getCharacter.mockResolvedValue(bundle());
  lunaMocks.saveCharacter.mockResolvedValue({ bundle: bundle() });
  // The full `PreviewResult` shape. An earlier mock omitted `notes`, and the preview panel does
  // `preview.notes.join(...)` on the success path — which crashed the render rather than the test,
  // which is exactly what the type exists to prevent. (The backend's `changed`/`limits` keys are
  // included so the mock matches the contract rather than the minimum the panel happens to read.)
  lunaMocks.previewShaping.mockResolvedValue({
    surface: "group",
    input: "",
    output: "",
    changed: false,
    notes: [],
    limits: { emoji_filter: true, strip_emoji: true, allowed_emoji: "", max_lines: 4 },
  });
  lunaMocks.toggleSkill.mockResolvedValue(bundle());
  void vi.restoreAllMocks();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

/** The shape `applyBundle` reads out of a loaded `CharacterBundle.soul`. */
const loaded = {
  title: "Luna",
  intro: "A companion at home in your group chats.",
  sections: [
    { title: "voice", body: "short lines, lowercase" },
    { title: "boundaries", body: "never speaks for someone else" },
  ],
  footer: "she is around",
};

describe("persona dirty baseline", () => {
  it("a freshly-loaded persona is not dirty", () => {
    const draft = {
      title: loaded.title,
      intro: loaded.intro,
      sections: loaded.sections.map((s) => ({ ...s })),
      footer: loaded.footer,
    };
    expect(isDraftDirty(draft, loaded)).toBe(false);
  });

  it("is dirty after editing the intro", () => {
    const draft = { ...loaded, intro: "A different introduction entirely." };
    expect(isDraftDirty(draft, loaded)).toBe(true);
  });

  it("is dirty after adding a section — the Add-section button has no confirmation", () => {
    const draft = { ...loaded, sections: [...loaded.sections, { title: "new", body: "" }] };
    expect(isDraftDirty(draft, loaded)).toBe(true);
  });

  it("is dirty after removing a section", () => {
    const draft = { ...loaded, sections: loaded.sections.slice(0, 1) };
    expect(isDraftDirty(draft, loaded)).toBe(true);
  });

  it("is dirty after editing one section's body", () => {
    const draft = {
      ...loaded,
      sections: [loaded.sections[0], { ...loaded.sections[1], body: "changed" }],
    };
    expect(isDraftDirty(draft, loaded)).toBe(true);
  });

  it("is dirty after reordering sections", () => {
    const draft = { ...loaded, sections: [...loaded.sections].reverse() };
    expect(isDraftDirty(draft, loaded)).toBe(true);
  });

  it("is clean when every edit is typed back", () => {
    const draft = { ...loaded, title: "Luna", sections: loaded.sections.map((s) => ({ ...s })) };
    expect(isDraftDirty(draft, loaded)).toBe(false);
  });
});

describe("persona guard lifetime", () => {
  function Persona(props: { dirty: boolean; onSave?: () => void }) {
    useUnsavedChanges({
      id: "character-soul",
      label: "the persona",
      dirty: props.dirty,
      onSave: props.onSave,
      onDiscard: () => {},
      registry: unsavedRegistry,
    });
    return <span>persona editor</span>;
  }

  async function render(ui: React.ReactNode) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(ui));
  }

  it("names the surface in the user's terms", async () => {
    await render(<Persona dirty />);
    expect(unsavedRegistry.list().map((e) => e.label)).toEqual(["the persona"]);
  });

  it("releases the guard when the page unmounts after a successful save", async () => {
    // A save calls applyBundle, which refreshes the baseline; `dirty` then goes false and the effect
    // cleanup releases the entry. If it did not, the bar would follow the user around the dashboard.
    await render(<Persona dirty />);
    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => root.render(<Persona dirty={false} />));
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("hands the bar the page's own save function", async () => {
    const onSave = vi.fn();
    await render(<Persona dirty onSave={onSave} />);
    expect(await unsavedRegistry.saveAll()).toBe(true);
    expect(onSave).toHaveBeenCalledOnce();
  });
});

// ── B3: the two actions that overwrite SOUL.md server-side ─────────────────────────────────────────

const SAVED_RAW = "# Luna\n\nthe saved persona\n";

function bundle(raw = SAVED_RAW) {
  return {
    soul: {
      title: "Luna",
      intro: "the saved persona",
      sections: [],
      footer: "",
      raw,
    },
    output: { emoji_filter: true, strip_emoji: true, allowed_emoji: [], max_lines: 4 },
    skins: [
      { name: "luna", description: "Luna", colors: { banner_text: "#ffffff" }, builtin: false },
      { name: "mono", description: "Mono", colors: { banner_text: "#eeeeee" }, builtin: true },
    ],
    current_skin: "luna",
    skills: [{ name: "luna-notes", category: "companion" }],
    auto_load: [],
    // Deliberately NOT equal to the loaded soul, so the no-op shortcut does not swallow the dialog
    // these tests are about. `matchingBundle()` is the fixture for the no-op case.
    presets: [
      { id: "generic", name: "Generic", description: "the shipped one", content: "# Luna\n\nsomething else entirely\n" },
      { id: "other", name: "Other", description: "different", content: "# Luna\n\nyet another\n" },
    ],
  };
}

/** A bundle whose selected preset already matches the loaded persona. */
function matchingBundle() {
  const b = bundle();
  return {
    ...b,
    presets: [
      {
        id: "generic",
        name: "Generic",
        description: "the shipped one",
        // Byte-identical to what `renderSoul` produces for this soul, which is the condition the
        // no-op shortcut checks.
        content: "# Luna\n\nthe saved persona\n",
      },
    ],
  };
}

async function renderCharacterPage() {
  const [{ default: CharacterPage }, { I18nProvider }, { PageHeaderProvider }, { UnsavedChangesProvider }] = await Promise.all([
    import("./CharacterPage"),
    import("@/i18n"),
    import("@/contexts/PageHeaderProvider"),
    import("@/contexts/UnsavedChanges"),
  ]);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <I18nProvider>
        <MemoryRouter>
          <PageHeaderProvider pluginTabs={[]}>
            <UnsavedChangesProvider>
            <CharacterPage />
            </UnsavedChangesProvider>
          </PageHeaderProvider>
        </MemoryRouter>
      </I18nProvider>,
    ),
  );
  await waitFor(() => buttonWith(container, "Apply preset") !== undefined);
}

const buttonWith = (c: HTMLElement, text: string) =>
  [...c.querySelectorAll("button")].find((b) =>
    (b.textContent ?? "").toLowerCase().includes(text.toLowerCase()),
  );

/** The DS ConfirmDialog renders into a portal on document.body, not into `container`. */
const dialogText = () =>
  document.querySelector('[role="alertdialog"]')?.textContent ?? null;

const dialogButton = (text: string) =>
  [...document.querySelectorAll('[role="alertdialog"] button')].find((b) =>
    (b.textContent ?? "").toLowerCase().includes(text.toLowerCase()),
  ) as HTMLButtonElement | undefined;

async function waitFor(cond: () => boolean, timeoutMs = 5000) {
  const start = Date.now();
  while (!cond()) {
    if (Date.now() - start > timeoutMs) throw new Error("waitFor: never became true");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
}

describe("B3 — preset apply confirms before overwriting SOUL.md", () => {
  it("writes nothing until the confirmation is accepted", async () => {
    await renderCharacterPage();
    await act(async () => buttonWith(container, "Apply preset")!.click());

    expect(dialogText()).toContain("Replace the persona");
    expect(lunaMocks.saveCharacter).not.toHaveBeenCalled();
  });

  it("states the consequence rather than asking a bare question", async () => {
    await renderCharacterPage();
    await act(async () => buttonWith(container, "Apply preset")!.click());
    await waitFor(() => dialogText() !== null);
    // The user needs to know what is being lost, not just that something is.
    expect(dialogText()).toMatch(/overwritten/i);
    expect(dialogText()).toMatch(/cannot be undone/i);
    expect(dialogText()).toMatch(/\d+ lines?/);
  });

  it("writes on confirm", async () => {
    await renderCharacterPage();
    await act(async () => buttonWith(container, "Apply preset")!.click());
    await waitFor(() => dialogButton("Replace persona") !== undefined);
    await act(async () => dialogButton("Replace persona")!.click());
    expect(lunaMocks.saveCharacter).toHaveBeenCalledTimes(1);
    expect(lunaMocks.saveCharacter.mock.calls[0][0]).toMatchObject({ preset_id: "generic" });
  });

  it("writes nothing when cancelled", async () => {
    await renderCharacterPage();
    await act(async () => buttonWith(container, "Apply preset")!.click());
    await waitFor(() => dialogButton("Cancel") !== undefined);
    await act(async () => dialogButton("Cancel")!.click());
    expect(lunaMocks.saveCharacter).not.toHaveBeenCalled();
    await waitFor(() => dialogText() === null);
  });

  it("does not prompt when the preset is already the active persona", async () => {
    // A confirm on a no-op is one people learn to dismiss without reading — which then costs them the
    // confirmation that actually mattered.
    lunaMocks.getCharacter.mockResolvedValue(matchingBundle());
    await renderCharacterPage();
    await act(async () => buttonWith(container, "Apply preset")!.click());
    // Give a dialog a chance to appear before asserting it did not — otherwise this passes whether
    // the shortcut works or the dialog is merely slow.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(dialogText()).toBeNull();
    expect(lunaMocks.saveCharacter).not.toHaveBeenCalled();
  });
});

describe("B3 — export writes the draft, not the last-saved file", () => {
  it("downloads what is on screen rather than bundle.soul.raw", async () => {
    // The bug this fixes: export used the last *saved* raw text from a page whose textareas hold the
    // user's unsaved edits, so exporting mid-edit silently threw that work away — the worst possible
    // outcome for the one action meant to be a backup.
    let captured = "";
    // `createObjectURL` reads the Blob it is given, which is where the exported bytes actually are.
    const createObjectURL = vi.fn((blob: Blob) => {
      void blob.text().then((t) => {
        captured = t;
      });
      return "blob:mock";
    });
    const revokeObjectURL = vi.fn();
    const realURL = globalThis.URL;
    vi.stubGlobal("URL", Object.assign(Object.create(realURL), realURL, {
      createObjectURL,
      revokeObjectURL,
    }));
    // Capture the download name from the property assignment the page performs, and suppress the
    // navigation jsdom would otherwise attempt.
    let filename = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      filename = this.download;
    });

    await renderCharacterPage();
    await act(async () => fireEvent.change(introInput(), { target: { value: "the unsaved persona" } }));
    await act(async () => buttonWith(container, "Export persona")!.click());
    await waitFor(() => captured !== "");

    expect(filename).toBe("SOUL.md");
    expect(captured).toContain("the unsaved persona");
    expect(captured).not.toContain("the saved persona");
    // Rendered from the parsed draft, so the export is a re-render of what is on screen rather than
    // a byte copy of the server's file — that is the fix, and it is also what makes an export
    // round-trip: importing it back reproduces the page.
    expect(captured.startsWith("# Luna")).toBe(true);
  });
});

function introInput() {
  return [...container.querySelectorAll("textarea")].find((el) =>
    el.closest("label")?.textContent?.includes("Who they are"),
  )!;
}

function maxLinesInput() {
  return container.querySelector<HTMLInputElement>('input[type="number"]')!;
}

function skinColorInput() {
  return container.querySelector<HTMLInputElement>('input[type="color"]')!;
}

describe("Character card draft isolation", () => {
  beforeEach(() => {
    let saved = bundle();
    lunaMocks.saveCharacter.mockImplementation(async (updates) => {
      saved = {
        ...saved,
        soul: updates.title === undefined ? saved.soul : { ...saved.soul, ...updates },
        output: updates.output ?? saved.output,
        current_skin: updates.skin ?? saved.current_skin,
        auto_load: updates.auto_load ?? saved.auto_load,
      };
      return { bundle: saved };
    });
    lunaMocks.saveSkinColors.mockImplementation(async (name, colors) => {
      saved = { ...saved, skins: saved.skins.map((s) => s.name === name ? { ...s, colors } : s) };
      return { bundle: saved };
    });
  });

  it.each(["hard limits", "skin", "skill"])("preserves the persona when saving %s", async (action) => {
    await renderCharacterPage();
    await act(async () => fireEvent.change(introInput(), { target: { value: "my persona draft" } }));
    if (action === "hard limits") {
      await act(async () => fireEvent.change(maxLinesInput(), { target: { value: "7" } }));
      await act(async () => buttonWith(container, "Save hard limits")!.click());
    } else if (action === "skin") {
      await act(async () => buttonWith(container, "mono")!.click());
    } else {
      const skill = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')]
        .find((el) => el.closest("label")?.textContent?.includes("luna-notes"))!;
      await act(async () => skill.click());
    }
    expect(lunaMocks.saveCharacter).toHaveBeenCalledOnce();
    expect(introInput().value).toBe("my persona draft");
    expect(unsavedRegistry.list().map((entry) => entry.id)).toContain("character-soul");
  });

  it("guards limits and colors, and saves every dirty card without discarding another", async () => {
    await renderCharacterPage();
    expect(unsavedRegistry.isDirty()).toBe(false);
    await act(async () => {
      fireEvent.change(introInput(), { target: { value: "my persona draft" } });
      fireEvent.change(maxLinesInput(), { target: { value: "7" } });
      fireEvent.change(skinColorInput(), { target: { value: "#aabbcc" } });
    });
    expect(unsavedRegistry.list().map((entry) => entry.id)).toEqual([
      "character-soul", "character-output", "character-colors",
    ]);
    const leave = vi.fn();
    await act(async () => { pendingNavigation.request(leave); });
    const save = [...document.querySelectorAll<HTMLButtonElement>("[data-unsaved-guard] button")]
      .find((button) => button.textContent?.includes("Save and leave"))!;
    await act(async () => save.click());
    expect(lunaMocks.saveCharacter.mock.calls.map(([body]) => [body])).toEqual([
      [{ title: "Luna", intro: "my persona draft", sections: [], footer: "" }],
      [{ output: { emoji_filter: true, strip_emoji: true, allowed_emoji: [], max_lines: 7, max_chars: 1200, language: "auto", style_filter: false, sentence_breaks: true } }],
    ]);
    expect(lunaMocks.saveSkinColors).toHaveBeenCalledWith("luna", { banner_text: "#aabbcc" }, "Luna");
    expect(leave).toHaveBeenCalledOnce();
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("lets users turn off sentence line breaks without changing casual-style selection", async () => {
    await renderCharacterPage();
    const toggle = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')]
      .find((el) => el.closest("label")?.textContent?.includes("Sentence line breaks"))!;
    expect(toggle.checked).toBe(true);
    await act(async () => toggle.click());
    expect(unsavedRegistry.list().map((entry) => entry.id)).toContain("character-output");
    await act(async () => buttonWith(container, "Save hard limits")!.click());
    expect(lunaMocks.saveCharacter.mock.calls[0][0].output).toMatchObject({ sentence_breaks: false, style_filter: false });
  });

  it("holds navigation and keeps the limits draft when its save fails", async () => {
    lunaMocks.saveCharacter.mockRejectedValue(new Error("disk full"));
    await renderCharacterPage();
    await act(async () => fireEvent.change(maxLinesInput(), { target: { value: "7" } }));
    const leave = vi.fn();
    await act(async () => { pendingNavigation.request(leave); });
    const save = [...document.querySelectorAll<HTMLButtonElement>("[data-unsaved-guard] button")]
      .find((button) => button.textContent?.includes("Save and leave"))!;
    await act(async () => save.click());
    expect(leave).not.toHaveBeenCalled();
    expect(maxLinesInput().value).toBe("7");
    expect(unsavedRegistry.isDirty()).toBe(true);
  });

  it("discards color edits before an accepted skin switch and keeps other drafts on Stay", async () => {
    await renderCharacterPage();
    await act(async () => fireEvent.change(skinColorInput(), { target: { value: "#aabbcc" } }));
    await act(async () => buttonWith(container, "mono")!.click());
    expect(lunaMocks.saveCharacter).not.toHaveBeenCalled();
    expect(pendingNavigation.hasPending()).toBe(true);
    const stay = document.querySelector<HTMLButtonElement>('[data-unsaved-guard] button[aria-label="Stay"]')!;
    await act(async () => stay.click());
    expect(skinColorInput().value).toBe("#aabbcc");
    await act(async () => buttonWith(container, "mono")!.click());
    const discard = [...document.querySelectorAll<HTMLButtonElement>("[data-unsaved-guard] button")]
      .find((button) => button.textContent?.includes("Discard and leave"))!;
    await act(async () => discard.click());
    expect(lunaMocks.saveCharacter).toHaveBeenCalledWith({ skin: "mono" }, undefined);
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("keeps editors disabled while a write is pending", async () => {
    let finish: (value: unknown) => void = () => {};
    lunaMocks.saveCharacter.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    await renderCharacterPage();
    await act(async () => buttonWith(container, "Save persona")!.click());
    expect(introInput().matches(":disabled")).toBe(true);
    await act(async () => finish({ bundle: bundle() }));
    expect(introInput().matches(":disabled")).toBe(false);
  });
});
