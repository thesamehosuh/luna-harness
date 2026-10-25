// @vitest-environment jsdom
/**
 * The cron editor modals' unsaved-changes behaviour.
 *
 * The bug: `useModalBehavior` closes on Escape, and the backdrop and the X button closed directly, so
 * all three paths dropped a composed job on the floor. A half-written prompt or schedule is real work
 * — often several minutes of it — with no prompt, no confirmation, and nothing in the toast history
 * afterwards.
 *
 * These pin the *baselines* and the release semantics, which is where a guard like this actually
 * goes wrong: a baseline of "nothing" marks every freshly-opened modal dirty (and blocks the first
 * navigation away), and a missing release leaves the whole dashboard permanently dirty.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { isDraftDirty, useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import { unsavedRegistry } from "@/lib/dirty-registry";

const cronApi = vi.hoisted(() => ({
  getCronJobs: vi.fn(),
  getProfiles: vi.fn(),
  getCronDeliveryTargets: vi.fn(),
  getSkills: vi.fn(),
  getToolsets: vi.fn(),
  getModelOptions: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, ...cronApi } };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  document.body.innerHTML = "";
  for (const fn of Object.values(cronApi)) fn.mockReset();
  cronApi.getCronJobs.mockResolvedValue([]);
  cronApi.getProfiles.mockResolvedValue({ profiles: [{ name: "default" }, { name: "secondary" }] });
  cronApi.getCronDeliveryTargets.mockResolvedValue({
    targets: [{ id: "local", name: "Local", home_target_set: true, home_env_var: null }],
  });
  cronApi.getSkills.mockResolvedValue([]);
  cronApi.getToolsets.mockResolvedValue([]);
  cronApi.getModelOptions.mockResolvedValue({ providers: [] });
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

/** Mirror of `EMPTY_CRON_JOB_FORM` in CronPage; the identity is what these tests are about. */
const BLANK = {
  name: "",
  prompt: "",
  schedule: "",
  deliver: "local",
  skills: [] as string[],
  provider: "",
  model: "",
  base_url: "",
  script: "",
  no_agent: false,
  context_from: "",
  continuity: false,
  enabled_toolsets: [] as string[],
  workdir: "",
  scheduleState: {
    mode: "interval",
    intervalValue: 30,
    intervalUnit: "minutes",
    timeOfDay: "09:00",
    weekdays: [1, 2, 3, 4, 5],
    dayOfMonth: 1,
    onceAt: "",
    custom: "",
  },
};

/** What `editorFormFromJob` produces for a stored job, which is the edit modal's baseline. */
function formFromStoredJob() {
  return {
    ...BLANK,
    name: "Daily summary",
    prompt: "Summarise the day.",
    schedule: "0 9 * * *",
    deliver: "telegram",
    model: "gpt-4o-mini",
  };
}

describe("cron create modal dirty baseline", () => {
  it("a freshly-opened create modal is not dirty", () => {
    // The baseline is the blank form, not `undefined`. Comparing against "nothing" would mark every
    // modal open as unsaved and block the very first navigation away from the page.
    expect(isDraftDirty({ ...BLANK, scheduleState: { ...BLANK.scheduleState } }, BLANK)).toBe(false);
  });

  it("is dirty once a single field is typed", () => {
    expect(isDraftDirty({ ...BLANK, prompt: "run the report" }, BLANK)).toBe(true);
  });

  it("is dirty when only the target profile changes", () => {
    expect(
      isDraftDirty(
        { profile: "secondary", form: BLANK },
        { profile: "default", form: BLANK },
      ),
    ).toBe(true);
  });

  it("is dirty when only the schedule builder moved", () => {
    // The schedule is two fields — the cron string and the builder's structured state — so a change
    // to either has to register. This is the field most likely to be forgotten.
    expect(
      isDraftDirty(
        { ...BLANK, scheduleState: { ...BLANK.scheduleState, timeOfDay: "17:30" } },
        BLANK,
      ),
    ).toBe(true);
  });

  it("is clean again after the user clears their edits", () => {
    const edited = { ...BLANK, prompt: "oops", schedule: "0 9 * * *" };
    expect(isDraftDirty({ ...edited, prompt: "", schedule: "" }, BLANK)).toBe(false);
  });
});

describe("cron edit modal dirty baseline", () => {
  it("an edit modal opened on a stored job is not dirty", () => {
    // The baseline is the job's own form, not the blank one. Comparing against the blank form would
    // mark every opened edit modal dirty the instant it appeared.
    const baseline = formFromStoredJob();
    expect(isDraftDirty({ ...baseline, scheduleState: { ...baseline.scheduleState } }, baseline)).toBe(
      false,
    );
  });

  it("is dirty once one field of the job is edited", () => {
    const baseline = formFromStoredJob();
    expect(isDraftDirty({ ...baseline, prompt: "Summarise the week." }, baseline)).toBe(true);
  });

  it("is clean when the user types a value back to what was stored", () => {
    const baseline = formFromStoredJob();
    const edited = { ...baseline, prompt: "changed" };
    expect(isDraftDirty({ ...edited, prompt: baseline.prompt }, baseline)).toBe(false);
  });
});

describe("registration lifetime matches the modal", () => {
  function Modal({ dirty }: { dirty: boolean }) {
    useUnsavedChanges({
      id: "cron-create",
      label: "New Cron Job",
      dirty,
      onSave: () => {},
      onDiscard: () => {},
      registry: unsavedRegistry,
    });
    return <span>job editor</span>;
  }

  async function render(ui: React.ReactNode) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(ui));
  }

  it("holds the guard while the modal is open with edits", async () => {
    await render(<Modal dirty />);
    expect(unsavedRegistry.list().map((e) => e.label)).toEqual(["New Cron Job"]);
  });

  it("releases the guard when the modal closes", async () => {
    await render(<Modal dirty />);
    // Closing the modal is what unmounts this subtree. A leaked entry would make the whole dashboard
    // look dirty for the rest of the session.
    await act(async () => root.render(<span>closed</span>));
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("never registers at all while the form is untouched", async () => {
    await render(<Modal dirty={false} />);
    expect(unsavedRegistry.isDirty()).toBe(false);
  });
});

describe("CronPage create target guard", () => {
  async function renderPage() {
    const [{ default: CronPage }, { I18nProvider }, { PageHeaderProvider }, { UnsavedChangesProvider }, { MemoryRouter }] =
      await Promise.all([
        import("./CronPage"),
        import("@/i18n"),
        import("@/contexts/PageHeaderProvider"),
        import("@/contexts/UnsavedChanges"),
        import("react-router"),
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
                <CronPage />
              </PageHeaderProvider>
            </MemoryRouter>
          </I18nProvider>
        </UnsavedChangesProvider>,
      ),
    );
    await waitFor(() => buttonWithText("Create") !== undefined);
  }

  const buttonWithText = (text: string) =>
    [...document.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").trim().toLowerCase() === text.toLowerCase(),
    ) as HTMLButtonElement | undefined;

  const click = (button: HTMLButtonElement | undefined) => {
    if (!button) throw new Error("button not found");
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  };

  const waitFor = async (condition: () => boolean) => {
    for (let i = 0; i < 100 && !condition(); i += 1) {
      await act(async () => new Promise((resolve) => setTimeout(resolve, 10)));
    }
    expect(condition()).toBe(true);
  };

  it("guards a changed create target even before any job fields are edited", async () => {
    await renderPage();
    await act(async () => click(buttonWithText("Create")));
    const profileSelect = document.querySelector('#cron-profile [role="combobox"]') as HTMLButtonElement | null;
    expect(profileSelect).not.toBeNull();
    await act(async () => click(profileSelect ?? undefined));
    const secondary = [...document.querySelectorAll('[role="option"]')].find((option) =>
      (option.textContent ?? "").trim() === "secondary",
    );
    expect(secondary).toBeTruthy();
    await act(async () =>
      secondary?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })),
    );

    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => click(document.querySelector('[aria-label="Close"]') as HTMLButtonElement));
    expect(document.querySelector('[role="alertdialog"]')).not.toBeNull();
  });
});
