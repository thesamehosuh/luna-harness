// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ fetch: vi.fn(), getConfig: vi.fn(), getSchema: vi.fn(), saveConfig: vi.fn() }));
vi.mock("@/lib/api", () => ({ fetchJSON: mocks.fetch, api: mocks }));
vi.mock("@/components/MemoryReasoningSelector", () => ({ MemoryReasoningSelector: () => null }));
vi.mock("@/hooks/useUnsavedChanges", () => ({ useUnsavedChanges: () => undefined }));
import MemoryPage from "./MemoryPage";
let host: HTMLDivElement, root: Root;
beforeEach(async () => {
  vi.clearAllMocks();
  mocks.getConfig.mockResolvedValue({ memory: { memory_enabled: true, user_profile_enabled: true, memory_char_limit: 2200, user_char_limit: 1375, nudge_interval: 10, write_approval: false } });
  mocks.getSchema.mockResolvedValue({ fields: {} });
  mocks.fetch.mockImplementation(async (url: string) => url.endsWith("/settings") ? { fields: [], status: { enabled: true, workspace: "fixture", ai_peer: "fixture", session_strategy: "per-session", base_url: "http://localhost:9" } } : url.endsWith("/progress") ? { stage: "ready" } : { ok: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<MemoryRouter initialEntries={["/memory?tab=settings"]}><MemoryPage /></MemoryRouter>));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
it("toggles Honcho without changing the independent note-file choices", async () => {
  const toggle = host.querySelector('[aria-label="Enable Honcho memory"]')!;
  expect(toggle).toBeTruthy(); await act(async () => (toggle as HTMLButtonElement).click());
  const call = mocks.fetch.mock.calls.find(([url]) => url === "/api/luna/memory/service")!;
  expect(JSON.parse(call[1].body)).toEqual({ enabled: false, timeout: 180 });
  expect(mocks.saveConfig).not.toHaveBeenCalled();
  const noteLabel = [...host.querySelectorAll("label")].find(label => label.textContent === "Enable MEMORY.md notes")!;
  const noteToggle = document.getElementById(noteLabel.htmlFor)!;
  expect(noteToggle.getAttribute("aria-checked")).toBe("true");
});
