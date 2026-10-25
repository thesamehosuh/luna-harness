// @vitest-environment jsdom
/**
 * B5 — the compose-modals sweep.
 *
 * B2 guarded the five surfaces named in POLISH_PLAN. The same bug class remained in every other
 * dialog built on `useModalBehavior`: Escape, the backdrop and the X all reached the state setter
 * directly, so a draft died with the modal. Each of these tests renders the real page and asserts the
 * one thing that matters — that a populated draft keeps the modal open — plus that closing works when
 * there is nothing to lose.
 *
 * The baselines are imported from the pages rather than re-declared, so a drift in a real default
 * shows up here instead of hiding behind a copy that no longer matches.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";

import { unsavedRegistry } from "@/lib/dirty-registry";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ── api mock ─────────────────────────────────────────────────────────────────────────────────────
//
// ONE mock for `@/lib/api`. Four separate `vi.mock` calls for the same specifier do not merge —
// the last one wins, so every page under test would have seen only its own stub.

const api = vi.hoisted(() => ({
  getWebhooks: vi.fn(),
  createWebhook: vi.fn(),
  setWebhookEnabled: vi.fn(),
  deleteWebhook: vi.fn(),
  watchRestart: vi.fn(),

  getMessagingPlatforms: vi.fn(),
  updateMessagingPlatform: vi.fn(),
  testMessagingPlatform: vi.fn(),

  getProfiles: vi.fn(),
  getActiveProfile: vi.fn(),
  getProfileSoul: vi.fn(),
  updateProfileSoul: vi.fn(),
  getProfileSetupCommand: vi.fn(),
  getModelsForProvider: vi.fn(),

  getMcpServers: vi.fn(),
  getMcpCatalog: vi.fn(),
  addMcpServer: vi.fn(),
  testMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  authenticateMcpServer: vi.fn(),
  restartGatewayForMcp: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, ...api } };
});

// ── harness ─────────────────────────────────────────────────────────────────────────────────────

let container: HTMLDivElement;
let root: Root;

async function renderPage(name: "WebhooksPage" | "ChannelsPage" | "ProfilesPage" | "McpPage") {
  const mod = await import(`./${name}`);
  const Page = mod.default;
  // `UnsavedChangesProvider` is required, not optional: without it `useUnsavedChangesGuard` returns
  // its no-op fallback and every guarded close proceeds immediately — which is exactly the documented
  // behaviour, and exactly what makes this suite fail loudly if the wiring is dropped.
  const [{ I18nProvider }, { PageHeaderProvider }, { UnsavedChangesProvider }] = await Promise.all([
    import("@/i18n"),
    import("@/contexts/PageHeaderProvider"),
    import("@/contexts/UnsavedChanges"),
  ]);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <UnsavedChangesProvider>
        <I18nProvider>
          <MemoryRouter>
            <PageHeaderProvider pluginTabs={[]}>
              <Page />
            </PageHeaderProvider>
          </MemoryRouter>
        </I18nProvider>
      </UnsavedChangesProvider>,
    ),
  );
}

/**
 * Searched across `document`, not `container`: these pages put their primary action in the page
 * *header* (via `PageHeaderProvider`'s `setEnd`), which renders outside the page's own subtree, and
 * some dialogs portal to the body.
 */
const buttonWith = (text: string) =>
  [...document.querySelectorAll("button")].find((b) =>
    (b.textContent ?? "").trim().toLowerCase().includes(text.toLowerCase()),
  ) as HTMLButtonElement | undefined;

/**
 * Inputs and textareas only — a <select> matched here would make `setValue` throw.
 *
 * Labels are matched through `label[for]` → element `id` as well as inline text, because most of
 * these fields are `<Label htmlFor="webhook-name">Name</Label>` next to a sibling `<Input id=…>` —
 * there is no wrapping label and no aria-label to find them by.
 */
const inputNamed = (label: string) => {
  const needle = label.toLowerCase();
  return [...document.querySelectorAll("input, textarea")].find((el) => {
    const own = [
      el.getAttribute("aria-label"),
      el.getAttribute("placeholder"),
      el.getAttribute("name"),
      el.closest("label")?.textContent,
    ];
    if (el.id) {
      const labelEl =
        document.querySelector(`label[for="${el.id}"]`) ??
        [...document.querySelectorAll("label")].find((l) => l.htmlFor === el.id);
      if (labelEl) own.push(labelEl.textContent);
    }
    return own
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(needle);
  }) as HTMLInputElement | HTMLTextAreaElement | null;
};

function setValue(el: Element, value: string) {
  // The setter is looked up on the element's OWN prototype. Reusing HTMLInputElement's for a
  // textarea or a <select> throws "called on an object that is not a valid instance".
  const proto = Object.getPrototypeOf(el) as object;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (!setter) throw new Error(`no value setter for ${el.tagName}`);
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

const pressEscape = () =>
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

async function waitFor(cond: () => boolean, timeoutMs = 5000) {
  const start = Date.now();
  while (!cond()) {
    if (Date.now() - start > timeoutMs) throw new Error("waitFor: never became true");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
}

const click = (el: Element | undefined) => {
  if (!el) throw new Error("element not rendered");
  el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
};

beforeEach(() => {
  document.body.innerHTML = "";
  for (const fn of Object.values(api)) fn.mockReset();
  // `enabled: true` — the "New subscription" button is `disabled={!enabled || enabling}`, so a false
  // here leaves it inert and the click silently does nothing.
  api.getWebhooks.mockResolvedValue({ enabled: true, subscriptions: [] });
  api.watchRestart.mockResolvedValue({ ok: true, needed: false });
  api.getMessagingPlatforms.mockResolvedValue({
    platforms: [],
    env_path: "~/.luna/.env",
    gateway_start_command: "luna gateway start",
  });
  api.getProfiles.mockResolvedValue({ profiles: [] });
  api.getActiveProfile.mockResolvedValue({ current: "default", active: "default" });
  api.getProfileSoul.mockResolvedValue({ content: "# Luna\n\nthe saved soul\n" });
  api.getModelsForProvider.mockResolvedValue({ models: [] });
  api.getMcpServers.mockResolvedValue({ servers: [] });
  api.getMcpCatalog.mockResolvedValue({ entries: [], diagnostics: [] });
  vi.stubGlobal("ResizeObserver", class {
    disconnect() {}
    observe() {}
    unobserve() {}
  });
  // ProfilesPage probes `prefers-reduced-motion` on mount; jsdom has no matchMedia.
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

// ── WebhooksPage ────────────────────────────────────────────────────────────────────────────────

describe("B5 — WebhooksPage create modal", () => {
  async function openModal() {
    await renderPage("WebhooksPage");
    await waitFor(() => buttonWith("New subscription") !== undefined);
    await act(async () => click(buttonWith("New subscription")));
    await waitFor(() => container.querySelector('[role="dialog"]') !== null);
  }

  it("keeps a typed subscription open when Escape is pressed", async () => {
    await openModal();
    const name = inputNamed("name");
    expect(name).not.toBeNull();
    await act(async () => setValue(name!, "my-hook"));

    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => pressEscape());

    // A held close: the modal is still there and the draft is still armed.
    expect(unsavedRegistry.isDirty()).toBe(true);
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  });

  it("does not arm the guard for an untouched modal", async () => {
    await openModal();
    expect(unsavedRegistry.isDirty()).toBe(false);
    await act(async () => pressEscape());
    await waitFor(() => container.querySelector('[role="dialog"]') === null);
  });

  it("Discard clears the draft", async () => {
    await openModal();
    await act(async () => setValue(inputNamed("name")!, "my-hook"));
    const entry = unsavedRegistry.list().find((e) => e.id === "webhooks-create");
    expect(entry).toBeDefined();
    entry!.onDiscard?.();
    await act(async () => {});
    // Reverting to the blank form un-arms the guard; the modal is still open because nothing asked it
    // to close.
    expect(unsavedRegistry.isDirty()).toBe(false);
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  });
});

// ── ChannelsPage ─────────────────────────────────────────────────────────────────────────────────

describe("B5 — ChannelsPage credential modal", () => {
  const platform = {
    id: "telegram",
    name: "Telegram",
    kind: "telegram",
    // The credential dialog is reached through the quick-setup panel's "Manual setup" row, and the
    // panel only renders when the operator has configured a quick-setup service
    // (luna.telegram.onboarding_service_url). Set here so this fixture exercises the panel.
    onboarding_available: true,
    enabled: false,
    gateway_running: false,
    gateway_url: "",
    available: false,
    configured: false,
    auth_kind: "token",
    env_vars: [
      { key: "TELEGRAM_BOT_TOKEN", label: "Bot token", prompt: "Paste the bot token", required: true, is_set: false },
    ],
  };

  async function openModal() {
    api.getMessagingPlatforms.mockResolvedValue({
      platforms: [platform],
      env_path: "~/.luna/.env",
      gateway_start_command: "luna gateway start",
    });
    await renderPage("ChannelsPage");
    // "Manual setup" is the row button that opens the credential dialog in this fixture's state; the
    // label varies with whether the platform is already configured.
    await waitFor(() => buttonWith("Manual setup") !== undefined);
    await act(async () => click(buttonWith("Manual setup")));
    await waitFor(() => container.querySelector('[role="dialog"]') !== null);
  }

  it("keeps a pasted token open when Escape is pressed", async () => {
    // The sharpest case in the sweep: a pasted bot token or API key has to be fetched and typed again,
    // and there is no undo.
    await openModal();
    const token = inputNamed("bot token") ?? inputNamed("token");
    expect(token).not.toBeNull();
    await act(async () => setValue(token!, "123456:SECRET"));

    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => pressEscape());
    expect(unsavedRegistry.isDirty()).toBe(true);
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  });

  it("does not arm the guard before anything is typed", async () => {
    await openModal();
    expect(unsavedRegistry.isDirty()).toBe(false);
  });
});

// ── ProfilesPage ────────────────────────────────────────────────────────────────────────────────

describe("B5 — ProfilesPage SOUL editor", () => {
  async function openSoulEditor() {
    api.getProfiles.mockResolvedValue({
      profiles: [{ name: "default", description: "", is_current: true, skills_count: 0 }],
    });
    await renderPage("ProfilesPage");
    await waitFor(() => container.textContent!.includes("default"));
    // The SOUL action lives inside a per-row actions menu, and the trigger carries its name in
    // `aria-label` rather than in text, so match on either.
    const menu = [...document.querySelectorAll("button")].find((b) =>
      `${b.textContent ?? ""} ${b.getAttribute("aria-label") ?? ""}`.toLowerCase().includes("actions"),
    );
    await act(async () => click(menu));
    await waitFor(() => document.querySelector('[role="menuitem"]') !== null);
    const edit = [...document.querySelectorAll('[role="menuitem"]')].find((b) =>
      (b.textContent ?? "").toLowerCase().includes("soul"),
    ) as HTMLButtonElement | undefined;
    await act(async () => click(edit));
    await waitFor(() => container.querySelector('[role="dialog"]') !== null);
  }

  it("keeps edited SOUL text open when Escape is pressed", async () => {
    await openSoulEditor();
    const editor = container.querySelector<HTMLTextAreaElement>('[role="dialog"] textarea');
    expect(editor).not.toBeNull();
    await act(async () => setValue(editor!, "# Luna\n\nmy careful edits\n"));

    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => pressEscape());
    expect(unsavedRegistry.isDirty()).toBe(true);
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  });

  it("is clean when the editor opens and is left alone", async () => {
    // The baseline is the content loaded from disk — if it were the empty string, every opened editor
    // would read as edited and arm the prompt on arrival.
    await openSoulEditor();
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("Discard closes the editor and releases the guard", async () => {
    await openSoulEditor();
    const editor = container.querySelector<HTMLTextAreaElement>('[role="dialog"] textarea');
    await act(async () => setValue(editor!, "# Luna\n\nmy careful edits\n"));
    const entry = unsavedRegistry.list().find((e) => e.id === "profiles-editor");
    expect(entry).toBeDefined();
    entry!.onDiscard?.();
    await act(async () => {});
    await waitFor(() => unsavedRegistry.isDirty() === false);
  });
});

// ── McpPage ─────────────────────────────────────────────────────────────────────────────────────

describe("B5 — McpPage add-server modal", () => {
  async function openModal() {
    await renderPage("McpPage");
    await waitFor(() => buttonWith("Add Server") !== undefined);
    await act(async () => click(buttonWith("Add Server")));
    await waitFor(() => container.querySelector('[role="dialog"]') !== null);
  }

  it("keeps a typed command open when Escape is pressed", async () => {
    await openModal();
    // The `command` field only renders for the stdio transport, so the always-present Name field is
    // used to dirty the form — the guard keys off the whole draft, not off any one field.
    const name = inputNamed("name");
    expect(name).not.toBeNull();
    await act(async () => setValue(name!, "filesystem"));

    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => pressEscape());
    expect(unsavedRegistry.isDirty()).toBe(true);
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  });

  it("does not arm the guard for an untouched modal", async () => {
    await openModal();
    expect(unsavedRegistry.isDirty()).toBe(false);
    await act(async () => pressEscape());
    await waitFor(() => container.querySelector('[role="dialog"]') === null);
  });
});
