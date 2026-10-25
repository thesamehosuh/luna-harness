import { describe, expect, it } from "vitest";
import {
  completionPercent,
  firstIncomplete,
  needsFirstRun,
  pendingSteps,
  type StepReport,
} from "./luna-onboarding";

function step(id: string, status: "done" | "todo"): StepReport {
  return { id, title: id, status, detail: "" };
}

describe("wizard step helpers", () => {
  const steps = [
    step("provider", "done"),
    step("telegram", "todo"),
    step("honcho", "done"),
    step("character", "todo"),
    step("wake_test", "todo"),
  ];

  it("lists pending steps in wizard order", () => {
    expect(pendingSteps(steps)).toEqual(["telegram", "character", "wake_test"]);
    expect(firstIncomplete(steps)).toBe("telegram");
  });

  it("reports null first-incomplete when everything is done", () => {
    expect(firstIncomplete(steps.map((s) => step(s.id, "done")))).toBeNull();
  });

  it("computes completion percent", () => {
    expect(completionPercent(steps)).toBe(40);
    expect(completionPercent([])).toBe(0);
    expect(completionPercent(steps.map((s) => step(s.id, "done")))).toBe(100);
  });

  it("requires a model connection independently of optional Telegram", () => {
    expect(needsFirstRun(steps)).toBe(false); // provider is done
    expect(needsFirstRun(steps.map((s) => step(s.id, "todo")))).toBe(true);
    expect(
      needsFirstRun([step("provider", "todo"), step("telegram", "done")]),
    ).toBe(true);
    expect(needsFirstRun([{ ...step("provider", "todo"), configured: true }, step("telegram", "todo")])).toBe(false);
    expect(needsFirstRun([step("provider", "todo"), { ...step("telegram", "todo"), status: "skipped" }])).toBe(true);
    expect(needsFirstRun([step("honcho", "todo")])).toBe(false);
  });
});
