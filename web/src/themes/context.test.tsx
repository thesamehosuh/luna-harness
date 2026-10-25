// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  getThemes: vi.fn(),
  setTheme: vi.fn(),
  getFontPref: vi.fn(),
  setFontPref: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMocks,
}));

import { ThemeProvider } from "./context";

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  delete window.__LUNA_DASHBOARD_APPEARANCE__;
  const stored = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      clear: () => stored.clear(),
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => stored.set(key, String(value)),
      removeItem: (key: string) => stored.delete(key),
    },
  });
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-dashboard-theme");
  window.localStorage.clear();
  apiMocks.getThemes.mockReset().mockResolvedValue({ active: "sakura-day", themes: [] });
  apiMocks.setTheme.mockReset().mockResolvedValue({ ok: true });
  apiMocks.getFontPref.mockReset().mockResolvedValue({ font: "theme" });
  apiMocks.setFontPref.mockReset().mockResolvedValue({ ok: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("ThemeProvider applies themes to the document root", () => {
  it("starts a fresh browser in Sakura Dusk before preferences arrive", async () => {
    apiMocks.getThemes.mockReturnValue(new Promise(() => {}));
    await act(async () => root.render(<ThemeProvider><div /></ThemeProvider>));
    expect(document.documentElement.dataset.dashboardTheme).toBe("sakura-dusk");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(document.documentElement.style.getPropertyValue("--background-base")).toBe("#17132b");
  });

  it("uses the installed profile's theme before async preferences arrive", async () => {
    window.localStorage.setItem("hermes-dashboard-theme", "sakura-dusk");
    window.__LUNA_DASHBOARD_APPEARANCE__ = { theme: "sakura-day", font: "theme" };
    apiMocks.getThemes.mockReturnValue(new Promise(() => {}));
    await act(async () => root.render(<ThemeProvider><div /></ThemeProvider>));
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(document.documentElement.dataset.dashboardTheme).toBe("sakura-day");
    expect(document.documentElement.style.getPropertyValue("--color-primary")).toBe("#a65370");
  });

  it("emits Sakura Day's color scheme, palette, and theme id", async () => {
    window.localStorage.setItem("hermes-dashboard-theme", "sakura-day");
    await act(async () => root.render(<ThemeProvider><div /></ThemeProvider>));

    const html = document.documentElement;
    expect(html.style.colorScheme).toBe("light");
    expect(html.dataset.dashboardTheme).toBe("sakura-day");
    expect(html.style.getPropertyValue("--background-base")).toBe("#fbf0f8");
    expect(html.style.getPropertyValue("--color-primary")).toBe("#a65370");
  });

  it("keeps a user theme named like a retired preset when server prefs load", async () => {
    apiMocks.getThemes.mockResolvedValue({
      active: "rose",
      themes: [{
        name: "rose",
        label: "My Rosé",
        definition: {
          name: "rose",
          label: "My Rosé",
          description: "Custom",
          palette: {
            background: { hex: "#fbf0f8", alpha: 1 },
            midground: { hex: "#1e1830", alpha: 1 },
            foreground: { hex: "#ffffff", alpha: 0 },
            warmGlow: "transparent",
            noiseOpacity: 0,
          },
          typography: {
            fontSans: "sans-serif",
            fontMono: "monospace",
            baseSize: "15px",
            lineHeight: "1.5",
            letterSpacing: "0",
          },
          layout: { radius: "0.5rem", density: "comfortable" },
          colorScheme: "light",
        },
      }],
    });
    window.localStorage.setItem("hermes-dashboard-theme", "rose");
    await act(async () => root.render(<ThemeProvider><div /></ThemeProvider>));

    expect(document.documentElement.dataset.dashboardTheme).toBe("rose");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
