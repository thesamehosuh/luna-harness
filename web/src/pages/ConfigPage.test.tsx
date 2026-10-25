// @vitest-environment jsdom
/**
 * The raw-YAML editor's unsaved-changes guard.
 *
 * The bug: a free-text textarea over the whole of `config.yaml`, one nav click from gone, with a save
 * button on the same screen as every other control. Typing there is the highest-consequence edit in
 * the dashboard and had no protection at all.
 *
 * What matters here is the *baseline*: `yamlBaseline` is the text as last loaded from (or written to)
 * disk. A naive dirty check against `""` would mark the textarea dirty on first paint and prompt the
 * user on every reload, which is how a guard trains people to dismiss it without reading.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import { unsavedRegistry } from "@/lib/dirty-registry";

const configApi = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getSchema: vi.fn(),
  getDefaults: vi.fn(),
  getConfigRaw: vi.fn(),
  getStatus: vi.fn(),
  saveConfig: vi.fn(),
  saveConfigRaw: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, ...configApi } };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  document.body.innerHTML = "";
  for (const fn of Object.values(configApi)) fn.mockReset();
  configApi.getConfig.mockResolvedValue({ display: { name: "saved" } });
  configApi.getSchema.mockResolvedValue({
    fields: { "display.name": { type: "string", category: "general" } },
    category_order: ["general"],
  });
  configApi.getDefaults.mockResolvedValue({ display: { name: "default" } });
  configApi.getConfigRaw.mockResolvedValue({ yaml: "display:\n  name: saved\n", path: "/tmp/config.yaml" });
  configApi.getStatus.mockResolvedValue({ config_path: "/tmp/config.yaml" });
  configApi.saveConfig.mockResolvedValue({ ok: true });
  configApi.saveConfigRaw.mockResolvedValue({ ok: true });
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

const LOADED = "# Luna\nmodel: gpt-4o-mini\ndisplay:\n  skin: luna\n";

describe("config YAML guard", () => {
  function Editor(props: {
    yamlMode: boolean;
    yamlText: string;
    baseline: string;
    onSave?: () => Promise<void>;
    onReload?: () => Promise<void>;
  }) {
    // Exactly the rule ConfigPage applies: the baseline is the text as last read from or written to
    // disk, and the guard is inactive while the raw view is not on screen.
    const dirty = props.yamlMode && props.yamlText !== props.baseline;
    useUnsavedChanges({
      id: "config-yaml",
      label: "Raw YAML config",
      dirty,
      onSave: props.onSave,
      onDiscard: props.onReload,
      registry: unsavedRegistry,
    });
    return <span>{props.yamlText}</span>;
  }

  async function render(ui: React.ReactNode) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(ui));
  }

  it("is clean on first paint, with the textarea showing the loaded text", async () => {
    await render(<Editor yamlMode yamlText={LOADED} baseline={LOADED} />);
    expect(unsavedRegistry.isDirty()).toBe(false);
    expect(container.textContent).toBe(LOADED);
  });

  it("is clean while the raw view is closed, even with stale text retained", async () => {
    // Switching back to the form view leaves `yamlText` in state but the form is then the source of
    // truth, so the raw text is no longer in-progress work. Prompting there would be wrong.
    await render(<Editor yamlMode={false} yamlText={`${LOADED}typed`} baseline={LOADED} />);
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("is dirty once a single character is typed", async () => {
    await render(<Editor yamlMode yamlText={`${LOADED}# note`} baseline={LOADED} />);
    expect(unsavedRegistry.list().map((e) => e.label)).toEqual(["Raw YAML config"]);
  });

  it("goes clean when the edit is written to disk", async () => {
    // handleYamlSave sets the baseline to what it just wrote, which is what makes Save clear the bar
    // without a reload.
    const typed = `${LOADED}# note`;
    await render(<Editor yamlMode yamlText={typed} baseline={typed} />);
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("is dirty on whitespace alone — YAML indentation is significant", async () => {
    // A trailing newline is invisible and easy to add accidentally, and for YAML it can change the
    // document's meaning at the boundary. Refusing to treat it as an edit would silently discard it.
    await render(<Editor yamlMode yamlText={`${LOADED}\n`} baseline={LOADED} />);
    expect(unsavedRegistry.isDirty()).toBe(true);
  });

  it("offers Discard, which reloads the file rather than reverting to a stale copy", async () => {
    const onReload = vi.fn(async () => {});
    await render(
      <Editor yamlMode yamlText={`${LOADED}typed`} baseline={LOADED} onSave={async () => {}} onReload={onReload} />,
    );
    expect(unsavedRegistry.list()[0].onDiscard).toBeDefined();
    let saved = false;
    await act(async () => {
      saved = await unsavedRegistry.saveAll();
      unsavedRegistry.discardAll();
    });
    expect(saved).toBe(true);
    expect(onReload).toHaveBeenCalledOnce();
  });

  it("hands the bar the page's own save, and a failed save leaves the guard armed", async () => {
    const onSave = vi.fn(async () => {
      throw new Error("config.yaml is read-only");
    });
    await render(<Editor yamlMode yamlText={`${LOADED}typed`} baseline={LOADED} onSave={onSave} />);

    let saved = true;
    await act(async () => {
      saved = await unsavedRegistry.saveAll();
    });
    expect(saved).toBe(false);
    expect(onSave).toHaveBeenCalledOnce();
    // Still dirty: the guard must not let a navigation through on the strength of a write that failed.
    expect(unsavedRegistry.isDirty()).toBe(true);
  });
});

describe("ConfigPage form guard", () => {
  async function renderPage() {
    const [{ default: ConfigPage }, { I18nProvider }, { PageHeaderProvider }, { UnsavedChangesProvider }, { MemoryRouter }] =
      await Promise.all([
        import("./ConfigPage"),
        import("@/i18n"),
        import("@/contexts/PageHeaderProvider"),
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
              <PageHeaderProvider pluginTabs={[]}>
                <ConfigPage />
              </PageHeaderProvider>
            </MemoryRouter>
          </I18nProvider>
        </UnsavedChangesProvider>,
      ),
    );
    await waitFor(() => Boolean(inputNamed("Name")));
  }

  const inputNamed = (label: string) =>
    [...document.querySelectorAll("input")].find((el) =>
      el.parentElement?.textContent?.toLowerCase().includes(label.toLowerCase()),
    ) as HTMLInputElement | undefined;

  const setValue = (el: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const waitFor = async (condition: () => boolean) => {
    for (let i = 0; i < 100 && !condition(); i += 1) {
      await act(async () => new Promise((resolve) => setTimeout(resolve, 10)));
    }
    expect(condition()).toBe(true);
  };

  const click = (button: HTMLButtonElement | undefined) => {
    if (!button) throw new Error("button not found");
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  };

  it("registers the actual form draft and keeps Save and leave blocked when its write fails", async () => {
    await renderPage();
    await act(async () => setValue(inputNamed("Name")!, "draft"));
    expect(unsavedRegistry.list().map((entry) => entry.label)).toEqual(["Config"]);

    configApi.saveConfig.mockRejectedValueOnce(new Error("disk is read-only"));
    let saved = true;
    await act(async () => {
      saved = await unsavedRegistry.saveAll();
    });
    expect(saved).toBe(false);
    expect(unsavedRegistry.isDirty()).toBe(true);

    configApi.saveConfig.mockResolvedValueOnce({ ok: false });
    await act(async () => {
      saved = await unsavedRegistry.saveAll();
    });
    expect(saved).toBe(false);
    expect(unsavedRegistry.isDirty()).toBe(true);

    configApi.saveConfig.mockResolvedValueOnce({ ok: true });
    await act(async () => {
      saved = await unsavedRegistry.saveAll();
    });
    expect(saved).toBe(true);
    expect(unsavedRegistry.isDirty()).toBe(false);
    expect(configApi.saveConfig).toHaveBeenLastCalledWith({ display: { name: "draft" } });
  });

  it("requires a decision before switching from a dirty form to YAML", async () => {
    await renderPage();
    await act(async () => setValue(inputNamed("Name")!, "draft"));
    const yamlButton = [...document.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").trim() === "YAML",
    ) as HTMLButtonElement | undefined;
    await act(async () => click(yamlButton));
    expect(document.querySelector('[role="alertdialog"]')).not.toBeNull();
    const discard = [...document.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").toLowerCase().includes("discard and leave"),
    ) as HTMLButtonElement | undefined;
    await act(async () => click(discard));
    await waitFor(() => document.querySelector("textarea") !== null);
    expect(configApi.getConfigRaw).toHaveBeenCalled();
  });

  it("requires a decision before switching from dirty YAML back to the form", async () => {
    await renderPage();
    const yamlButton = [...document.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").trim() === "YAML",
    ) as HTMLButtonElement | undefined;
    await act(async () => click(yamlButton));
    await waitFor(() => document.querySelector("textarea") !== null);

    const textarea = document.querySelector("textarea")!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, "edited yaml\n");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const formButton = [...document.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").trim() === "Form",
    ) as HTMLButtonElement | undefined;
    await act(async () => click(formButton));
    expect(document.querySelector('[role="alertdialog"]')).not.toBeNull();

    const discard = [...document.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").toLowerCase().includes("discard and leave"),
    ) as HTMLButtonElement | undefined;
    await act(async () => click(discard));
    await waitFor(() => document.querySelector("textarea") === null);
    expect(inputNamed("Name")?.value).toBe("saved");
    expect(configApi.getConfigRaw).toHaveBeenCalledTimes(2);
  });

  it("asks before importing over dirty form edits", async () => {
    await renderPage();
    await act(async () => setValue(inputNamed("Name")!, "draft"));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{"display":{"name":"imported"}}'], "config.json", {
      type: "application/json",
    });
    Object.defineProperty(fileInput, "files", { configurable: true, value: [file] });
    await act(async () => fileInput.dispatchEvent(new Event("change", { bubbles: true })));
    await waitFor(() => document.querySelector('[role="alertdialog"]') !== null);

    const discard = [...document.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").toLowerCase().includes("discard and leave"),
    ) as HTMLButtonElement | undefined;
    await act(async () => click(discard));
    await waitFor(() => inputNamed("Name")?.value === "imported");
    expect(unsavedRegistry.isDirty()).toBe(true);
  });
});
