// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  report: vi.fn(), choice: vi.fn(), assign: vi.fn(), showToast: vi.fn(), setEnd: vi.fn(),
}));
vi.mock("@/contexts/usePageHeader", () => ({ usePageHeader: () => ({ setEnd: mocks.setEnd }) }));
vi.mock("@nous-research/ui/hooks/use-toast", () => ({ useToast: () => ({ showToast: mocks.showToast }) }));
vi.mock("@nous-research/ui/ui/components/toast", () => ({ Toast: () => null }));
vi.mock("@/lib/luna-onboarding", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/luna-onboarding")>(),
  onboardingApi: { get: mocks.report, choice: mocks.choice, personas: async () => ({ personas: [] }) },
}));
vi.mock("@/lib/api", () => ({ api: { setModelAssignment: mocks.assign, getModelOptions: vi.fn() } }));
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
  const button = [...host.querySelectorAll("button")].find(el => el.textContent === text);
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
  const select = host.querySelector("select")!;
  await act(async () => { select.value = "Subscription / connected account"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(host.textContent).toContain("Browser account login");
  expect(host.querySelector('input[type="password"]')).toBeNull();
  await click("Choose companion model");
  await click("Apply test model");
  expect(mocks.assign).toHaveBeenCalledWith({ scope: "main", provider: "openai-codex", model: "subscription-fixture", confirm_expensive_model: true });
  expect(mocks.report).toHaveBeenCalledTimes(2);
});
