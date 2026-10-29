// @vitest-environment jsdom
// Regression tests for the Behaviour page's threshold editors.
//
// Two bugs pinned here.
//
// Threshold bounds: every slider was rendered with a hardcoded `max={1}`, so a threshold whose real
// range is 0–1440 (minutes since Luna last spoke) painted pinned to the far right, and dragging it
// left wrote 0 — silently zeroing a wake cooldown in config.yaml with no confirm and no undo. A
// slider now requires backend-supplied bounds, and edits commit on release rather than per pixel.
//
// WakePolicyCard saves: 11 fields were split across four Save buttons, each writing only its own
// slice of the policy. Pressing "Save budget" dropped the room-voice textarea 20 lines above it, and
// the route chain's Save dropped the mention/reaction policy — silently, with a success toast. There
// is now one save that writes the whole policy.

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import type { ReactNode } from "react";

import { BehaviourPower, ThresholdRow, WakePolicyCard } from "./BehaviourPage";
import { unsavedRegistry } from "@/lib/dirty-registry";
import type { BehaviourBundle, ThresholdValue } from "@/lib/luna-api";

let container: HTMLDivElement;
let root: Root;

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<MemoryRouter>{ui}</MemoryRouter>));
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

function entry(over: Partial<ThresholdValue> = {}): ThresholdValue {
  return {
    value: 10,
    default: 10,
    overridden: false,
    type: "float",
    unknown: false,
    min: 0,
    max: 1440,
    step: 1,
    description: "Minutes since Luna last spoke before she may self-wake.",
    ...over,
  };
}

const noop = () => {};

/**
 * Set a React-controlled input's value the way React itself expects.
 *
 * Assigning `input.value` directly trips React's value tracker, which then believes nothing changed
 * and swallows the synthetic onChange. Going through the prototype setter and dispatching `input`
 * is the standard way to drive a controlled input from a test. The setter is looked up per element
 * type because `HTMLInputElement.prototype` and `HTMLTextAreaElement.prototype` are unrelated
 * interfaces — calling one on the other throws.
 */
function setInputValue(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto =
    input instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

/** React maps onBlur to the bubbling `focusout`, not `blur`. */
function blurInput(input: HTMLInputElement) {
  input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
}

const sliderIn = (c: HTMLElement) => c.querySelector<HTMLInputElement>('input[type="range"]')!;
const numberIn = (c: HTMLElement) => c.querySelector<HTMLInputElement>('input[type="number"]')!;

describe("ThresholdRow slider bounds", () => {
  it("renders the slider against the backend's range, not a guessed one", async () => {
    await render(
      <ThresholdRow name="min_minutes_since_luna" entry={entry()} saving={false} onCommit={noop} onReset={noop} />,
    );
    const slider = sliderIn(container);
    expect(slider).not.toBeNull();
    expect(slider.min).toBe("0");
    expect(slider.max).toBe("1440");
    expect(slider.step).toBe("1");
  });

  it("can represent the shipped default", async () => {
    await render(
      <ThresholdRow name="min_minutes_since_luna" entry={entry({ value: 45, default: 45 })} saving={false} onCommit={noop} onReset={noop} />,
    );
    const slider = sliderIn(container);
    const value = Number(slider.value);
    expect(value).toBe(45);
    expect(value).toBeGreaterThanOrEqual(Number(slider.min));
    expect(value).toBeLessThanOrEqual(Number(slider.max));
  });

  it("renders no slider when the backend could not resolve a range", async () => {
    await render(
      <ThresholdRow
        name="some_future_key"
        entry={entry({ min: undefined, max: undefined })}
        saving={false}
        onCommit={noop}
        onReset={noop}
      />,
    );
    expect(container.querySelector('input[type="range"]')).toBeNull();
    // The number input is the fallback, and it is bounded only where bounds are known.
    expect(numberIn(container)).not.toBeNull();
  });

  it("labels the slider with the human label, not the raw config key", async () => {
    await render(
      <ThresholdRow name="min_minutes_since_luna" entry={entry()} saving={false} onCommit={noop} onReset={noop} />,
    );
    const slider = sliderIn(container);
    expect(slider.getAttribute("aria-label")).toBe("min minutes since luna");
    expect(slider.getAttribute("aria-label")).not.toBe("min_minutes_since_luna");
  });
});

describe("ThresholdRow commit semantics", () => {
  it("does not write while the slider is being dragged", async () => {
    const onCommit = vi.fn();
    await render(
      <ThresholdRow name="min_minutes_since_luna" entry={entry()} saving={false} onCommit={onCommit} onReset={noop} />,
    );
    const slider = sliderIn(container);

    // A drag fires input per step; the old control wrote to config.yaml on every one of them.
    await act(async () => {
      for (const v of ["300", "200", "100", "50"]) setInputValue(slider, v);
    });
    expect(onCommit).not.toHaveBeenCalled();
    expect(slider.value).toBe("50");
  });

  it("writes once on release", async () => {
    const onCommit = vi.fn();
    await render(
      <ThresholdRow name="min_minutes_since_luna" entry={entry()} saving={false} onCommit={onCommit} onReset={noop} />,
    );
    const slider = sliderIn(container);

    await act(async () => {
      setInputValue(slider, "45");
      slider.dispatchEvent(new Event("pointerup", { bubbles: true }));
    });
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith(45);
  });

  it("does not write when the value is unchanged", async () => {
    const onCommit = vi.fn();
    await render(
      <ThresholdRow name="min_minutes_since_luna" entry={entry()} saving={false} onCommit={onCommit} onReset={noop} />,
    );
    await act(async () => {
      sliderIn(container).dispatchEvent(new Event("pointerup", { bubbles: true }));
    });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("clamps a typed value into range rather than sending it out of bounds", async () => {
    const onCommit = vi.fn();
    await render(
      <ThresholdRow name="min_minutes_since_luna" entry={entry()} saving={false} onCommit={onCommit} onReset={noop} />,
    );
    const number = numberIn(container);

    await act(async () => setInputValue(number, "99999"));
    await act(async () => blurInput(number));
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith(1440);
  });

  it("never writes NaN from an emptied number field", async () => {
    const onCommit = vi.fn();
    await render(
      <ThresholdRow name="min_new_messages" entry={entry({ value: 3, default: 3, type: "int", min: 1, max: 1000 })} saving={false} onCommit={onCommit} onReset={noop} />,
    );
    const number = numberIn(container);
    await act(async () => setInputValue(number, ""));
    await act(async () => blurInput(number));
    for (const call of onCommit.mock.calls) {
      expect(Number.isFinite(call[0])).toBe(true);
    }
  });
});

/** A bundle shaped like the backend's, with every group populated. */
function bundle(): BehaviourBundle {
  return {
    enabled: true,
    dry_run: true,
    room_register: "short lines, lowercase",
    settle_seconds: 20,
    poll_seconds: 30,
    stale_after_minutes: 10,
    budget: { min_minutes_since_luna: 45, max_per_day: 6, max_per_week: 24 },
    mention_fallback: ["^hey luna", "luna\b"],
    reactions: { allowed: ["👀", "🔥"] },
    jev: {
      timeout_seconds: 20,
      route: ["local", "cloud"],
      providers: {
        local: {
          base_url: "http://localhost:11434/v1",
          model: "qwen3",
          // Keys the form does not render. The backend accepts six per provider and replaces the
          // map wholesale on write, so a save that omitted these deleted them from config.yaml.
          tier: "fast",
          endpoint: "/v1/chat/completions",
          instructions: "answer in one line",
        },
        cloud: { model: "gpt-4o-mini", api_key_env: "OPENAI_API_KEY" },
      },
    },
  };
}

const buttonWith = (c: HTMLElement, text: string) =>
  [...c.querySelectorAll("button")].find((b) =>
    (b.textContent ?? "").toLowerCase().includes(text.toLowerCase()),
  );

/** The room-voice textarea, identified by its label text rather than by DOM position. */
const registerArea = (c: HTMLElement) =>
  [...c.querySelectorAll("textarea")].find((ta) =>
    (ta.closest("label")?.textContent ?? "").includes("room voice"),
  )!;

function editableBundle(): BehaviourBundle {
  return { ...bundle(), decision: { questions: {}, rules: [] },
    reactions: { allowed: ["💜"], criteria: { "💜": "support" } },
    reaction_defaults: { "👍": "agreement" },
    wake_prompts: {}, wake_prompt_defaults: { directed: "Answer this person.", message: "Join with {contribution_type}." },
    question_defaults: [{ id: "message_would_fit", type: "noul", instructions: "Would a reply help?", criteria: { true: "welcome", false: "intrusive" } }],
  };
}

describe("Behaviour customization", () => {
  it("shows an immediate accessible power switch with preview status", async () => {
    const onChange = vi.fn();
    await render(<BehaviourPower enabled={false} dryRun={true} busy={false} onChange={onChange} />);
    expect(container.textContent).toContain("Off");
    await act(async () => container.querySelector<HTMLButtonElement>('[role="switch"]')!.click());
    expect(onChange).toHaveBeenCalledWith(true);
    await act(async () => root.render(<BehaviourPower enabled={true} dryRun={true} busy={true} onChange={onChange} />));
    expect(container.textContent).toContain("On · preview only");
    expect(container.querySelector<HTMLButtonElement>('[role="switch"]')!.disabled).toBe(true);
  });

  it("keeps new defaults clean and saves prompts, rubrics, emoji meanings, and conditions together", async () => {
    const onSave = vi.fn();
    await render(<WakePolicyCard behaviour={editableBundle()} saving={false} onSave={onSave} />);
    expect(unsavedRegistry.isDirty()).toBe(false);
    const field = (name: string) => [...container.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea")].find(el => el.closest("label")?.textContent?.includes(name))!;
    await act(async () => setInputValue(field("When to use"), "quiet encouragement"));
    await act(async () => buttonWith(container, "Wake prompts")!.click());
    await act(async () => setInputValue(container.querySelector<HTMLTextAreaElement>("#wake-message")!, "Offer one useful thought."));
    await act(async () => buttonWith(container, "Jev judgments")!.click());
    await act(async () => setInputValue(field("Question prompt"), "Would music advice help?"));
    await act(async () => setInputValue(field("true"), "a welcome music tip"));
    await act(async () => buttonWith(container, "Custom conditions")!.click());
    await act(async () => buttonWith(container, "Add condition")!.click());
    expect(container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.disabled).toBe(true);
    expect(await unsavedRegistry.saveAll()).toBe(false);
    await act(async () => setInputValue(field("Condition name"), "Music"));
    await act(async () => setInputValue(field("Question Jev"), "Is candidate.text about music?"));
    await act(async () => container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.click());
    const patch = onSave.mock.calls[0][0];
    expect(patch.reactions.criteria["💜"]).toBe("quiet encouragement");
    expect(patch.wake_prompts.message).toBe("Offer one useful thought.");
    expect(patch.decision.questions.message_would_fit).toEqual({ instructions: "Would music advice help?", criteria: { true: "a welcome music tip", false: "intrusive" } });
    expect(patch.decision.rules[0]).toMatchObject({ name: "Music", instructions: "Is candidate.text about music?", action: "both", enabled: true });
  });

  it("adds and removes reactions and conditions and restores prompt defaults", async () => {
    const onSave = vi.fn();
    await render(<WakePolicyCard behaviour={editableBundle()} saving={false} onSave={onSave} />);
    await act(async () => setInputValue(container.querySelector<HTMLInputElement>('input[placeholder="Paste an emoji"]')!, "🌸"));
    await act(async () => buttonWith(container, "Add reaction")!.click());
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label^="Remove reaction"]')!.click());
    await act(async () => buttonWith(container, "Custom conditions")!.click());
    await act(async () => buttonWith(container, "Add condition")!.click());
    await act(async () => buttonWith(container, "Remove condition")!.click());
    await act(async () => buttonWith(container, "Wake prompts")!.click());
    await act(async () => setInputValue(container.querySelector<HTMLTextAreaElement>("#wake-message")!, "Changed"));
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="Reset message wake prompt"]')!.click());
    expect(container.querySelector<HTMLTextAreaElement>("#wake-message")!.value).toBe("Join with {contribution_type}.");
    await act(async () => container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.click());
    expect(onSave.mock.calls[0][0].reactions).toEqual({ allowed: ["🌸"], criteria: {} });
    expect(onSave.mock.calls[0][0].decision.rules).toEqual([]);
    expect(onSave.mock.calls[0][0].wake_prompts).toEqual({});
  });

  it("removes routes from the fallback order and keeps a draft through a power change", async () => {
    const onSave = vi.fn();
    const data = editableBundle();
    await render(<WakePolicyCard behaviour={data} saving={false} onSave={onSave} />);
    await act(async () => setInputValue(registerArea(container), "my voice"));
    await act(async () => root.render(<MemoryRouter><WakePolicyCard behaviour={{ ...data, enabled: false, revision: "new" }} saving={false} onSave={onSave} /></MemoryRouter>));
    expect(registerArea(container).value).toBe("my voice");
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="Remove route local"]')!.click());
    await act(async () => container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.click());
    expect(onSave.mock.calls[0][0].jev.route).toEqual(["cloud"]);
    expect(onSave.mock.calls[0][0].jev.providers).not.toHaveProperty("local");
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("enabled");
  });
});

describe("WakePolicyCard has one save, not four", () => {
  it("saves explicit watched groups and supports clearing the last selection", async () => {
    const onSave = vi.fn();
    await render(<WakePolicyCard behaviour={{ ...bundle(), watched_chats: ["test-room"], available_chats: ["test-room", "other-room"] }} saving={false} onSave={onSave} />);
    const field = [...container.querySelectorAll("fieldset")].find((el) => el.querySelector(":scope > legend")?.textContent?.includes("Groups where"))!;
    const checks = [...field.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(checks.map((el) => el.checked)).toEqual([true, false]);
    await act(async () => checks[0].click());
    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.click());
    expect(onSave.mock.calls[0][0].watched_chats).toEqual([]);
  });
  it("saves group coordination with the same guarded draft and shows activity separately", async () => {
    const onSave = vi.fn();
    const data = { ...bundle(), conversation: {
      enabled: true, settle_seconds: 1, response_gap_seconds: 2, max_pending: 16,
      max_age_seconds: 60, max_answer_age_seconds: 120, max_turns_per_burst: 3,
      burst_idle_seconds: 8, max_turns_per_minute: 6, max_parallel_rooms: 4, overload_notice: true,
    }, conversation_status: { active: [], waiting: [], recent: [] } };
    await render(<WakePolicyCard behaviour={data} saving={false} onSave={onSave} />);
    expect(unsavedRegistry.isDirty()).toBe(false);
    const input = [...container.querySelectorAll<HTMLInputElement>('input[type="number"]')]
      .find((el) => el.closest("label")?.textContent?.includes("Answers per burst"))!;
    await act(async () => setInputValue(input, "2"));
    await act(async () => setInputValue(registerArea(container), "still keep this voice"));
    expect(unsavedRegistry.isDirty()).toBe(true);
    await act(async () => container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.click());
    expect(onSave.mock.calls[0][0].conversation.max_turns_per_burst).toBe(2);
    expect(onSave.mock.calls[0][0].room_register).toBe("still keep this voice");
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("conversation_status");
    expect(container.textContent).toContain("0 answering · 0 waiting");
  });
  it("renders no per-group Save buttons", async () => {
    await render(
      <WakePolicyCard behaviour={bundle()} saving={false} onSave={vi.fn()} />,
    );
    for (const legacy of ["Save budget", "Save mention/reaction policy", "Save route chain"]) {
      expect(buttonWith(container, legacy)).toBeUndefined();
    }
    expect(container.querySelectorAll('[data-wake-policy-save]')).toHaveLength(1);
  });

  it("disables the save until something is edited", async () => {
    await render(
      <WakePolicyCard behaviour={bundle()} saving={false} onSave={vi.fn()} />,
    );
    const save = container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!;
    expect(save.disabled).toBe(true);
    expect(container.querySelector("[data-wake-policy-dirty]")).toBeNull();
  });

  it("a freshly-loaded card is not dirty — the round-trip normalisation is symmetric", async () => {
    // The form turns list fields into joined strings; if the baseline were not normalised the same
    // way, every freshly-loaded card would read as edited and arm the leave-prompt on arrival.
    await render(
      <WakePolicyCard behaviour={bundle()} saving={false} onSave={vi.fn()} />,
    );
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("edits the room voice arm the dirty state", async () => {
    await render(
      <WakePolicyCard behaviour={bundle()} saving={false} onSave={vi.fn()} />,
    );
    await act(async () => setInputValue(registerArea(container) as HTMLTextAreaElement, "new voice"));
    expect(unsavedRegistry.isDirty()).toBe(true);
    expect(container.querySelector("[data-wake-policy-dirty]")).not.toBeNull();
    expect(container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.disabled).toBe(false);
  });

  it("one save writes every group — an edit in a group whose button used to own it is included", async () => {
    const onSave = vi.fn();
    await render(<WakePolicyCard behaviour={bundle()} saving={false} onSave={onSave} />);

    // This is the exact scenario the old layout destroyed: change the room voice, then press the
    // budget save. Only the budget was written; the voice was silently dropped.
    await act(async () => setInputValue(registerArea(container) as HTMLTextAreaElement, "new voice"));
    await act(async () =>
      container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.click(),
    );

    expect(onSave).toHaveBeenCalledTimes(1);
    const patch = onSave.mock.calls[0][0];
    expect(patch.room_register).toBe("new voice");
    expect(patch.budget).toEqual({
      min_minutes_since_luna: 45,
      max_per_day: 6,
      max_per_week: 24,
    });
    expect(patch.mention_fallback).toEqual(["^hey luna", "luna\b"]);
    expect(patch.reactions).toEqual({ allowed: ["👀", "🔥"] });
    expect(patch.jev.route).toEqual(["local", "cloud"]);
    expect(patch.jev.timeout_seconds).toBe(20);
    expect(patch.jev.providers).toEqual({
      local: {
        base_url: "http://localhost:11434/v1",
        model: "qwen3",
        // Preserved verbatim: the form cannot express these, so it must not destroy them.
        tier: "fast",
        endpoint: "/v1/chat/completions",
        instructions: "answer in one line",
      },
      cloud: { model: "gpt-4o-mini", api_key_env: "OPENAI_API_KEY" },
    });
  });

  it("editing the room voice alone must not drop provider keys the form cannot show", async () => {
    // The regression from collapsing the four save buttons: a save of one group writes the whole
    // patch, so any key the patch omits is deleted from config.yaml. `endpoint`/`tier`/`instructions`
    // are hand-written config the form never renders.
    const onSave = vi.fn();
    await render(<WakePolicyCard behaviour={bundle()} saving={false} onSave={onSave} />);
    await act(async () => setInputValue(registerArea(container) as HTMLTextAreaElement, "new voice"));
    await act(async () =>
      container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!.click(),
    );
    const providers = (onSave.mock.calls[0][0] as { jev: { providers: Record<string, Record<string, unknown>> } })
      .jev.providers;
    expect(providers.local.endpoint).toBe("/v1/chat/completions");
    expect(providers.local.tier).toBe("fast");
    expect(providers.local.instructions).toBe("answer in one line");
  });

  it("still counts a loaded provider with unrendered keys as clean", async () => {
    // The dirty check has to stay symmetric: if the baseline dropped these keys while the draft kept
    // them, a freshly-loaded card would read as edited.
    await render(<WakePolicyCard behaviour={bundle()} saving={false} onSave={vi.fn()} />);
    expect(unsavedRegistry.isDirty()).toBe(false);
  });

  it("does not write when nothing changed", async () => {
    const onSave = vi.fn();
    await render(<WakePolicyCard behaviour={bundle()} saving={false} onSave={onSave} />);
    const save = container.querySelector<HTMLButtonElement>("[data-wake-policy-save]")!;
    await act(async () => save.click());
    expect(onSave).not.toHaveBeenCalled();
  });

  it("registers a guard whose save path is the card's own save", async () => {
    const onSave = vi.fn(async () => true);
    await render(<WakePolicyCard behaviour={bundle()} saving={false} onSave={onSave} />);
    await act(async () => setInputValue(registerArea(container) as HTMLTextAreaElement, "new voice"));

    expect(unsavedRegistry.list().map((e) => e.label)).toEqual(["wake policy"]);
    expect(await unsavedRegistry.saveAll()).toBe(true);
    expect(onSave).toHaveBeenCalledOnce();
  });
});
