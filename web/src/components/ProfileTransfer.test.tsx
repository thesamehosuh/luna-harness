// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileTransfer } from "./ProfileTransfer";

const api = vi.hoisted(() => ({ exportProfile: vi.fn(), previewProfile: vi.fn(), importProfile: vi.fn() }));
vi.mock("@/lib/luna-api", () => ({ lunaApi: api }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
const imported = vi.fn();
const fixture = { format: "luna-profile", version: 1, soul: "# Nova", config: {} };
const preview = { title: "Nova", description: "A companion", sections: ["model", "honcho"], omitted: ["telegram"], missing_skills: ["custom-skill"], memory_enabled: false, ambient_enabled: false };

beforeEach(async () => {
  vi.clearAllMocks();
  api.previewProfile.mockResolvedValue(preview);
  api.importProfile.mockResolvedValue({ ok: true, name: "nova", summary: preview });
  container = document.createElement("div"); document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<ProfileTransfer profiles={[{ name: "default" }, { name: "second" }]} onImported={imported} />));
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); });

async function upload(content = JSON.stringify(fixture), size = content.length) {
  const input = container.querySelector<HTMLInputElement>("input[type=file]")!;
  Object.defineProperty(input, "files", { configurable: true, value: [{ name: "nova.luna-profile.json", size, text: async () => content }] });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
}
function button(text: string) {
  return [...container.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent?.includes(text))!;
}
async function name(value: string) {
  const input = container.querySelector<HTMLInputElement>("#import-profile-name")!;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
  await act(async () => input.dispatchEvent(new Event("input", { bubbles: true })));
}

describe("profile transfer", () => {
  it("previews before creating a new profile, with services off and missing skills visible", async () => {
    await upload();
    expect(api.previewProfile).toHaveBeenCalledWith(fixture);
    expect(api.importProfile).not.toHaveBeenCalled();
    expect(container.textContent).toContain("custom-skill");
    expect(container.textContent).toContain("memory and proactive wakes stay off");
    expect(button("Create imported profile").disabled).toBe(true);
    await name("default");
    expect(button("Create imported profile").disabled).toBe(true);
    await name("nova");
    await act(async () => button("Create imported profile").click());
    expect(api.importProfile).toHaveBeenCalledWith("nova", fixture);
    expect(imported).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Imported nova");
  });

  it("keeps the preview and chosen name when the destination already exists", async () => {
    api.importProfile.mockRejectedValueOnce(new Error("A profile with that name already exists"));
    await upload(); await name("nova");
    await act(async () => button("Create imported profile").click());
    expect(container.querySelector("[role=alert]")?.textContent).toContain("already exists");
    expect(container.querySelector<HTMLInputElement>("#import-profile-name")?.value).toBe("nova");
    expect(imported).not.toHaveBeenCalled();
  });

  it("rejects oversized or invalid files before calling the API", async () => {
    await upload("{}", 2 * 1024 * 1024 + 1);
    expect(container.querySelector("[role=alert]")?.textContent).toContain("2 MiB");
    await upload("not json");
    expect(api.previewProfile).not.toHaveBeenCalled();
    expect(api.importProfile).not.toHaveBeenCalled();
  });

  it("exports the explicitly selected profile and downloads the complete JSON file", async () => {
    api.exportProfile.mockResolvedValue(fixture);
    const createUrl = vi.fn(() => "blob:profile");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createUrl });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    let filename = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { filename = this.download; });
    const select = container.querySelector<HTMLSelectElement>("#export-profile")!;
    await act(async () => { select.value = "second"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    await act(async () => button("Export profile").click());
    expect(api.exportProfile).toHaveBeenCalledWith("second");
    expect(filename).toBe("second.luna-profile.json");
    expect(createUrl).toHaveBeenCalledOnce();
  });
});
