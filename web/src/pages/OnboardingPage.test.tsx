// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  soul: vi.fn(), report: vi.fn(), choice: vi.fn(), assign: vi.fn(), env: vi.fn(), config: vi.fn(), platform: vi.fn(), status: vi.fn(), start: vi.fn(), connection: vi.fn(), actionStatus: vi.fn(), showToast: vi.fn(), setEnd: vi.fn(),
}));
vi.mock("@/contexts/usePageHeader", () => ({ usePageHeader: () => ({ setEnd: mocks.setEnd }) }));
vi.mock("@nous-research/ui/hooks/use-toast", () => ({ useToast: () => ({ showToast: mocks.showToast }) }));
vi.mock("@nous-research/ui/ui/components/toast", () => ({ Toast: () => null }));
vi.mock("@/lib/luna-onboarding", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/luna-onboarding")>(),
  onboardingApi: { get: mocks.report, choice: mocks.choice, personas: async () => ({ personas: [{ id: "generic", name: "Companion", description: "A fixture", content: "# Fixture persona" }] }) },
}));
vi.mock("@/lib/api", () => ({ getManagementProfile: () => "test-profile", api: { updateProfileSoul: mocks.soul, setModelAssignment: mocks.assign, getModelOptions: vi.fn(), setEnvVar: mocks.env, saveConfig: mocks.config, updateMessagingPlatform: mocks.platform, getStatus: mocks.status, startGateway: mocks.start, testMessagingPlatform: mocks.connection, getActionStatus: mocks.actionStatus } }));
vi.mock("@/components/OpenCodeSetup", () => ({ default: () => <div>Free model setup</div> }));
vi.mock("@/components/OAuthProvidersCard", () => ({ OAuthProvidersCard: () => <div>Browser account login</div> }));
vi.mock("@/components/MemoryReasoningSelector", () => ({ MemoryReasoningSelector: () => <div>Independent memory model settings</div> }));
vi.mock("@/components/ModelPickerDialog", () => ({ ModelPickerDialog: ({ onApply }: { onApply: (value: object) => void }) =>
  <button onClick={() => onApply({ provider: "openai-codex", model: "subscription-fixture", confirmExpensiveModel: true })}>Apply test model</button> }));
import OnboardingPage from "./OnboardingPage";

let host: HTMLDivElement;
let root: Root;
const steps = [
  { id: "provider", title: "Model", status: "todo", configured: true, provider: "opencode-engine", model: "opencode/fixture", detail: "Choose a model" },
  { id: "honcho", title: "Memory", status: "todo", detail: "Optional memory" },
  { id: "character", title: "Character", status: "todo", detail: "Choose a character" },
];
beforeEach(async () => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/onboarding");
  mocks.report.mockResolvedValue({ steps });
  mocks.choice.mockResolvedValue({ steps: steps.map(step => step.id === "honcho" ? { ...step, status: "skipped" } : step) });
  mocks.assign.mockResolvedValue({ ok: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<MemoryRouter><OnboardingPage /></MemoryRouter>));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function click(text: string) {
  const button = [...host.querySelectorAll("button")].find(el => (el.textContent === text || el.getAttribute("aria-label") === text));
  expect(button, text).toBeTruthy();
  await act(async () => button!.click());
}
it("shows one step, supports back/next, and persists optional skips", async () => {
  expect(host.textContent).toContain("Free model setup");
  expect(host.textContent).not.toContain("Independent memory model settings");
  await click("Next");
  expect(host.textContent).toContain("Independent memory model settings");
  expect(host.textContent).not.toContain("Free model setup");
  expect(window.location.hash).toBe("#step-honcho");
  await click("Skip for now");
  expect(mocks.choice).toHaveBeenCalledWith("honcho", "skipped");
  await click("Back");
  expect(host.textContent).toContain("Free model setup");
});
it("offers browser subscription login and assigns the live picker selection with price confirmation", async () => {
  await click("Sign in");
  expect(host.textContent).toContain("Browser account login");
  expect(host.querySelector('input[type="password"]')).toBeNull();
  await click("Choose companion model");
  await click("Apply test model");
  expect(mocks.assign).toHaveBeenCalledWith({ scope: "main", provider: "openai-codex", model: "subscription-fixture", confirm_expensive_model: true });
  expect(mocks.report).toHaveBeenCalledTimes(2);
});

it("applies the selected persona to the active profile", async () => {
  await click("3. Character");
  await click("Apply persona");
  expect(mocks.soul).toHaveBeenCalledWith("test-profile", "# Fixture persona");
});


it("requires owner and group IDs and grants the default admin DM access without removing existing users", async () => {
  mocks.report.mockResolvedValue({ steps: [...steps, { id: "telegram", title: "Telegram", status: "todo", detail: "", token_present: true, allowed_user_ids: ["234567"], groups: ["-100234567"], admin_ids: ["234567"], group_admin_ids: ["234567"] }] });
  await click("Check setup"); await click("4. Telegram");
  const save = [...host.querySelectorAll("button")].find(el => el.textContent === "Save & connect")!;
  async function fill(label: string, value: string) {
    const input = [...host.querySelectorAll("label")].find(el => el.textContent?.includes(label))?.querySelector("input");
    expect(input).toBeTruthy();
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
      input!.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  vi.useFakeTimers();
  mocks.status.mockResolvedValueOnce({ gateway_running: false }).mockResolvedValueOnce({ gateway_running: false }).mockResolvedValue({ gateway_running: true, gateway_pid: 42, gateway_state: "running" });
  mocks.start.mockResolvedValue({ name: "gateway-start" });
  mocks.actionStatus.mockResolvedValue({ running: true });
  mocks.connection.mockResolvedValue({ ok: true, state: "connected" });
  await fill("Your Telegram user ID", "not-a-user");
  expect(save.disabled).toBe(true);
  await fill("Your Telegram user ID", "345678");
  await fill("Group chat ID", "345678");
  expect(save.disabled).toBe(true);
  await fill("Group chat ID", "-100345678");
  await click("Save & connect");
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  vi.useRealTimers();
  expect(mocks.platform).toHaveBeenCalledWith("telegram", { enabled: true });
  expect(mocks.start).toHaveBeenCalledOnce();
  expect(host.textContent).toContain("Telegram connected. Send your bot a message.");
  expect(mocks.env).toHaveBeenCalledWith("TELEGRAM_ALLOWED_USERS", "234567,345678");
  expect(mocks.env).not.toHaveBeenCalledWith("TELEGRAM_BOT_TOKEN", expect.anything());
  expect(mocks.config).toHaveBeenCalledWith(expect.objectContaining({ telegram: {
    group_allowed_chats: ["-100234567", "-100345678"], allow_admin_from: ["234567", "345678"], group_allow_admin_from: ["234567", "345678"],
  } }));
});
