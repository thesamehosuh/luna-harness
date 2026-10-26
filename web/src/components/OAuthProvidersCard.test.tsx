// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { I18nProvider } from "@/i18n";
const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { getOAuthProviders: mocks.get } }));
import { OAuthProvidersCard } from "./OAuthProvidersCard";
it("shows browser login first without terminal instructions or credential previews", async () => {
  mocks.get.mockResolvedValue({ providers: [
    { id: "other", name: "Other account", flow: "device_code", status: { logged_in: false }, cli_command: "terminal command" },
    { id: "external", name: "External tool", flow: "external", status: { logged_in: false }, cli_command: "external command" },
    { id: "openai-codex", name: "Codex", flow: "device_code", status: { logged_in: true, token_preview: "private-preview-sentinel" } },
  ] });
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<I18nProvider><OAuthProvidersCard /></I18nProvider>));
    const text = host.textContent!;
    expect(text).toContain("ChatGPT (OpenAI Codex)");
    expect(text.indexOf("ChatGPT")).toBeLessThan(text.indexOf("Other account"));
    expect(text).not.toMatch(/terminal command|external command|External tool|private-preview-sentinel/);
  } finally { await act(async () => root.unmount()); host.remove(); }
});
