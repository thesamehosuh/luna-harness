// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ModelPickerDialog } from "./ModelPickerDialog";
import type { ModelOptionsResult } from "@hermes/shared";

const catalog: ModelOptionsResult = { provider: "unconfigured", model: "", providers: [
  { slug: "unconfigured", name: "Needs key", authenticated: false, is_current: true, models: [], warning: "run `hermes model` to configure" },
  { slug: "connected", name: "My account", authenticated: true, models: ["fixture-small", "fixture-expensive"] },
  { slug: "other", name: "Other provider", authenticated: false, models: ["fixture-locked"], warning: "run `hermes model` to configure" },
] };
let root: Root;
let host: HTMLDivElement;
const apply = vi.fn();
const close = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function render() {
  await act(async () => root.render(<MemoryRouter><ModelPickerDialog alwaysGlobal loader={async () => catalog} onApply={apply} onClose={close} /></MemoryRouter>));
}
async function click(label: string) {
  const button = [...document.querySelectorAll("button")].find(el => el.textContent === label);
  expect(button, label).toBeTruthy();
  await act(async () => button!.click());
}
it("opens a working connection and keeps auxiliary selectors from changing the free companion engine", async () => {
  await render();
  expect(document.body.textContent).toContain("fixture-small");
  expect(document.body.textContent).not.toContain("Other provider");
  expect(document.body.textContent).not.toContain("hermes model");
  expect(document.body.textContent).not.toContain("Set up free chat");
  await click("fixture-small"); await click("Use model");
  expect(apply).toHaveBeenCalledWith({ provider: "connected", model: "fixture-small", persistGlobal: true, confirmExpensiveModel: false });
});
it("preserves price confirmation before a saved selection is accepted", async () => {
  apply.mockResolvedValueOnce({ confirm_required: true, confirm_message: "High price fixture" }).mockResolvedValueOnce({});
  await render(); await click("fixture-expensive"); await click("Use model");
  expect(close).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain("High price fixture");
  await click("Switch anyway");
  expect(apply).toHaveBeenLastCalledWith({ provider: "connected", model: "fixture-expensive", persistGlobal: true, confirmExpensiveModel: true });
  expect(close).toHaveBeenCalledOnce();
});
it("provides an in-dashboard connection action and prevents selecting an unauthenticated model", async () => {
  await render(); await click("All providers");
  const provider = [...document.querySelectorAll("button")].find(el => el.textContent?.startsWith("Other provider"));
  await act(async () => provider!.click());
  expect(document.querySelector<HTMLAnchorElement>('a[href="/controls#model"]')).toBeTruthy();
  expect(document.body.textContent).not.toContain("hermes model");
  expect([...document.querySelectorAll("button")].find(el => el.textContent === "fixture-locked")?.disabled).toBe(true);
  expect([...document.querySelectorAll("button")].find(el => el.textContent === "Use model")?.disabled).toBe(true);
  expect(apply).not.toHaveBeenCalled();
});
