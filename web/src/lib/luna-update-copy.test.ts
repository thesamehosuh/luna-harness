import { describe, expect, it } from "vitest";
import { lunaReleaseUpdateDescription } from "./luna-update-copy";
import type { UpdateCheckResponse } from "./api";

const release: UpdateCheckResponse = { install_method: "luna-release", current_version: "0.1.0-alpha.9", latest_version: "0.1.0-alpha.10", behind: -1, update_available: true, can_apply: true, update_command: "Luna release update", message: null };

describe("Luna release update guidance", () => {
  it("explains the actual release flow and explicit companion lifecycle", () => {
    const copy = lunaReleaseUpdateDescription(release)!;
    expect(copy).toContain("Luna 0.1.0-alpha.10");
    expect(copy).toContain("Stop your companion in Control Center");
    expect(copy).toContain("Quit and reopen Luna");
    expect(copy).not.toContain("gateway restarts");
  });
  it("shows a completed installation instead of offering another install", () => {
    expect(lunaReleaseUpdateDescription({ ...release, restart_required: true, update_available: false, message: "Reopen Luna to use alpha.10" })).toBe("Reopen Luna to use alpha.10");
  });
  it("does not offer an older or already installed published release", () => {
    expect(lunaReleaseUpdateDescription({ ...release, update_available: false, message: "You're on the latest published Luna version." })).toBe("You're on the latest published Luna version.");
  });
  it("leaves the engine's unrelated deployment types to their own guidance", () => {
    expect(lunaReleaseUpdateDescription({ ...release, install_method: "docker" })).toBeNull();
  });
});
