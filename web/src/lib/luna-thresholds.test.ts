import { describe, expect, it } from "vitest";
import {
  canSlider,
  clampThreshold,
  groupThresholdKeys,
  thresholdLabel,
  thresholdStep,
} from "./luna-thresholds";

describe("groupThresholdKeys", () => {
  it("groups cascade fields into named sections, sorted, with an Other bucket", () => {
    const groups = groupThresholdKeys([
      "state_max_chars",
      "reaction_min_fit",
      "message_min_value",
      "safety_max_sensitive",
      "w_add_value",
      "weird_new_field",
      "timeliness_band",
      "min_new_messages",
    ]);
    const byName = Object.fromEntries(groups.map((g) => [g.name, g.keys]));
    expect(byName["Wake gates"]).toEqual(["message_min_value", "min_new_messages"]);
    expect(byName["Reactions"]).toEqual(["reaction_min_fit"]);
    expect(byName["Safety ceilings"]).toEqual(["safety_max_sensitive"]);
    expect(byName["Timing"]).toEqual(["timeliness_band"]);
    expect(byName["Scoring weights"]).toEqual(["w_add_value"]);
    expect(byName["Capacity"]).toEqual(["state_max_chars"]);
    expect(byName["Other"]).toEqual(["weird_new_field"]);
  });

  it("omits empty groups and keeps every key exactly once", () => {
    const groups = groupThresholdKeys(["message_min_value"]);
    expect(groups.map((g) => g.name)).toEqual(["Wake gates"]);
    expect(groups.flatMap((g) => g.keys)).toEqual(["message_min_value"]);
  });
});

describe("thresholdLabel", () => {
  it("renders snake_case keys as words, dropping the config path", () => {
    expect(thresholdLabel("luna.ambient.thresholds.message_min_value")).toBe(
      "message min value",
    );
    expect(thresholdLabel("reaction_min_fit")).toBe("reaction min fit");
  });
});

describe("thresholdStep", () => {
  it("steps ints by 1 and floats by 0.01", () => {
    expect(thresholdStep("int")).toBe(1);
    expect(thresholdStep("float")).toBe(0.01);
  });
});

describe("canSlider", () => {
  it("allows a slider only when the backend supplied a real range", () => {
    expect(canSlider({ min: 0, max: 1440 })).toBe(true);
    expect(canSlider({ min: 0, max: 1 })).toBe(true);
  });

  it("refuses a slider when bounds are missing, which is the bug this exists to prevent", () => {
    // The old control rendered `max={1}` regardless, which pinned a minutes value of 10 to the
    // far right and wrote 0 on a leftward drag.
    expect(canSlider({})).toBe(false);
    expect(canSlider({ min: 0 })).toBe(false);
    expect(canSlider({ max: 1440 })).toBe(false);
    expect(canSlider({ min: undefined, max: undefined })).toBe(false);
  });

  it("refuses degenerate or non-finite ranges", () => {
    expect(canSlider({ min: 5, max: 5 })).toBe(false);
    expect(canSlider({ min: 10, max: 1 })).toBe(false);
    expect(canSlider({ min: Number.NaN, max: 10 })).toBe(false);
    expect(canSlider({ min: Number.POSITIVE_INFINITY, max: 10 })).toBe(false);
  });
});

describe("clampThreshold", () => {
  it("leaves an in-range value alone", () => {
    expect(clampThreshold(45, { min: 0, max: 1440 })).toBe(45);
    expect(clampThreshold(0.6, { min: 0, max: 1 })).toBe(0.6);
  });

  it("clamps to the declared bounds", () => {
    expect(clampThreshold(99999, { min: 0, max: 1440 })).toBe(1440);
    expect(clampThreshold(-5, { min: 1, max: 1000 })).toBe(1);
    expect(clampThreshold(1.5, { min: 0, max: 1 })).toBe(1);
  });

  it("passes through when no bound is declared on that side", () => {
    expect(clampThreshold(500, {})).toBe(500);
    // No `max` declared, so a high value is not clamped…
    expect(clampThreshold(500, { min: 0 })).toBe(500);
    // …and no `min` declared, so a low value is not clamped either.
    expect(clampThreshold(-500, { max: 100 })).toBe(-500);
    // A declared side still clamps.
    expect(clampThreshold(500, { max: 100 })).toBe(100);
  });
});
