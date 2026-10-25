// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OpenCodeSetup from "./OpenCodeSetup";
import { opencodeApi } from "@/lib/luna-opencode";

vi.mock("@/lib/luna-opencode", () => ({ opencodeApi: {
  status: vi.fn(), install: vi.fn(), models: vi.fn(), select: vi.fn(), probe: vi.fn(),
} }));

const status = { installed: true, version: "2.1.2", recommended_version: "2.1.2", selected: "" };
const models = [{ id: "opencode/test-free", name: "Test Free", free: true, vision: false }];
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(opencodeApi.status).mockResolvedValue(status);
  vi.mocked(opencodeApi.models).mockResolvedValue({ ...status, models });
  vi.mocked(opencodeApi.probe).mockResolvedValue({ ok: true, detail: "OK", model: models[0].id });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
async function render(onSaved?: () => void) {
  await act(async () => root.render(<OpenCodeSetup onSaved={onSaved} />));
}
async function click(label: string) {
  const button = [...container.querySelectorAll("button")].find((entry) => entry.textContent?.includes(label));
  expect(button).toBeDefined();
  await act(async () => button?.click());
}

describe("native OpenCode setup", () => {
  it("installs and loads the live free catalog without an API key", async () => {
    vi.mocked(opencodeApi.status).mockResolvedValue({ ...status, installed: false });
    vi.mocked(opencodeApi.install).mockResolvedValue(status);
    await render();
    expect(opencodeApi.models).not.toHaveBeenCalled();
    await click("Install OpenCode");
    expect(opencodeApi.install).toHaveBeenCalledOnce();
    expect(container.querySelector("select")?.value).toBe("opencode/test-free");
    expect(container.querySelector('input[type="password"]')).toBeNull();
  });

  it("saves the catalog model and refreshes the parent only after success", async () => {
    const onSaved = vi.fn();
    vi.mocked(opencodeApi.select).mockResolvedValue({ ok: true, model: models[0] });
    await render(onSaved);
    await click("Use this model");
    expect(opencodeApi.select).toHaveBeenCalledWith("opencode/test-free");
    expect(opencodeApi.probe).toHaveBeenCalledWith("opencode/test-free");
    expect(vi.mocked(opencodeApi.probe).mock.invocationCallOrder[0]).toBeGreaterThan(vi.mocked(opencodeApi.select).mock.invocationCallOrder[0]);
    expect(onSaved).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Model saved");
  });

  it("retains a saved model and reports its quota failure without marking setup verified", async () => {
    vi.mocked(opencodeApi.select).mockResolvedValue({ ok: true, model: models[0] });
    vi.mocked(opencodeApi.probe).mockResolvedValue({ ok: false, detail: "Free usage limit reached", model: models[0].id });
    const onSaved = vi.fn();
    await render(onSaved);
    await click("Use this model");
    expect(onSaved).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Model saved");
    expect(container.textContent).toContain("Free usage limit reached");
    expect(container.textContent).not.toContain("Model replied:");
  });

  it("shows provider quota failures without claiming a working probe", async () => {
    vi.mocked(opencodeApi.probe).mockResolvedValue({ ok: false, detail: "Free usage limit reached", model: models[0].id });
    await render();
    await click("Test model");
    expect(container.textContent).toContain("Free usage limit reached");
    expect(container.textContent).not.toContain("Model replied:");
    expect(opencodeApi.select).not.toHaveBeenCalled();
  });

  it("keeps errors visible and does not save an unavailable model", async () => {
    vi.mocked(opencodeApi.select).mockRejectedValue(new Error("Model is no longer free"));
    const onSaved = vi.fn();
    await render(onSaved);
    await click("Use this model");
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("no longer free");
    expect(onSaved).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("Model saved");
  });
});
