// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), list: vi.fn(), saveNotes: vi.fn(), savePerson: vi.fn(), setEnd: vi.fn() }));
vi.mock("@/lib/groups-api", () => ({ groupsApi: mocks }));
vi.mock("@/contexts/usePageHeader", () => ({ usePageHeader: () => ({ setEnd: mocks.setEnd }) }));
vi.mock("@/hooks/useUnsavedChanges", () => ({ useUnsavedChanges: () => undefined }));
import GroupsPage from "./GroupsPage";

const room = { id: "a", platform: "telegram", chat_id: "-101", thread_id: "", name: "Game night", members: 1, note_chars: 10 };
const person = { platform: "telegram", user_id: "2", display_name: "Alex", pronouns: "", role: "", aliases: [], overridden: false, revision: "person-old" };
const bundle = { groups: [room], group: { ...room, people: [person], notes: { entries: ["Friday games"], chars: 12, revision: "notes-old" } }, policy: { notes_enabled: true, people_enabled: true, write_approval: false, reviews_enabled: true, review_interval: 10, note_limit: 2200, owner_configured: true } };
let host: HTMLDivElement, root: Root;
beforeEach(async () => {
  vi.clearAllMocks(); mocks.get.mockResolvedValue(structuredClone(bundle));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<MemoryRouter initialEntries={["/groups?group=a"]}><GroupsPage /></MemoryRouter>));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function click(text: string) {
  const button = [...host.querySelectorAll("button")].find(item => item.textContent === text || item.getAttribute("aria-label") === text);
  expect(button).toBeTruthy(); await act(async () => button!.click());
}
it("preserves the draft and its original revision when a member save returns newer agent notes", async () => {
  const textarea = host.querySelector('textarea[aria-label="Group memory notes"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, "Unsaved room plan");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("Edit Alex in this group");
  mocks.savePerson.mockResolvedValue({ ...bundle, group: { ...bundle.group, notes: { entries: ["Agent's newer note"], chars: 18, revision: "notes-new" } } });
  await click("Save group entry");
  expect((textarea as HTMLTextAreaElement).value).toBe("Unsaved room plan");
  mocks.saveNotes.mockRejectedValue(new Error("The companion updated these notes. Reload before saving your changes."));
  await click("Save group notes");
  expect(mocks.saveNotes).toHaveBeenCalledWith("a", ["Unsaved room plan"], "notes-old");
  expect(host.textContent).toContain("Reload before saving");
});
