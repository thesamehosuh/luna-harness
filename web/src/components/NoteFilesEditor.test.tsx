// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn(), save: vi.fn() }));
vi.mock("@/lib/note-files-api", () => ({ noteFilesApi: api }));
vi.mock("@/hooks/useUnsavedChanges", () => ({ useUnsavedChanges: () => undefined }));
import { NoteFilesEditor } from "./NoteFilesEditor";
let host: HTMLDivElement, root: Root;
const file = { id: "people", name: "PEOPLE.md", scope: "Shared directory and group entries", kind: "people", description: "Names and group roles", limit: 262144, enabled: true, content: "# People\n\n## telegram / 1\n- Name: Rowan\n", revision: "a".repeat(64) };
beforeEach(async () => {
  vi.clearAllMocks();
  api.list.mockResolvedValue({ files: [file, { ...file, id: "memory", name: "MEMORY.md", kind: "notes", scope: "Owner DM" }] });
  api.read.mockResolvedValue(file);
  api.save.mockImplementation(async (_id: string, content: string) => ({ ...file, content, revision: "b".repeat(64) }));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<MemoryRouter initialEntries={["/memory?file=people"]}><NoteFilesEditor /></MemoryRouter>));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function edit(value: string) {
  const field = host.querySelector('textarea')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
function button(text: string) { return [...host.querySelectorAll("button")].find(button => button.textContent === text)!; }
it("opens a deep-linked file and saves the actual Markdown with its revision", async () => {
  expect(api.read).toHaveBeenCalledWith("people");
  expect(host.querySelector('textarea')?.value).toBe(file.content);
  const changed = file.content.replace("Rowan", "Robin"); await edit(changed);
  await act(async () => button("Save PEOPLE.md").click());
  expect(api.save).toHaveBeenCalledWith("people", changed, file.revision);
  expect(host.textContent).toContain("PEOPLE.md saved.");
});
it("keeps a conflicting draft and offers discard without silently replacing it", async () => {
  api.save.mockRejectedValue(new Error("The companion changed this file. Reload before saving."));
  const changed = file.content + "- Role: Game host\n"; await edit(changed);
  expect(button("Reload saved file").disabled).toBe(true);
  await act(async () => button("Save PEOPLE.md").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("changed this file");
  expect(host.querySelector('textarea')?.value).toBe(changed);
  await act(async () => button("Discard changes").click());
  expect(host.querySelector('textarea')?.value).toBe(file.content);
  expect(button("Reload saved file").disabled).toBe(false);
});
