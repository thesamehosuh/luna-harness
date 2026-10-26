// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { Select } from "./Select";
it("keeps the selected label visible while saving and after options refresh", async () => {
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  const render = (disabled: boolean) => root.render(<Select label="Model" value="current" disabled={disabled} options={[{ value: "current", label: "Current model" }]} onValueChange={() => {}} />);
  try {
    await act(async () => render(false));
    expect(host.querySelector('button')?.textContent).toContain("Current model");
    await act(async () => render(true));
    expect(host.querySelector('button')?.textContent).toContain("Current model");
    await act(async () => render(false));
    expect(host.querySelector('button')?.textContent).toContain("Current model");
  } finally { await act(async () => root.unmount()); host.remove(); }
});
