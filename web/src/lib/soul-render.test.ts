/**
 * `renderSoul` must stay byte-identical to `render_soul` in `luna/lib/luna_cli/character.py`.
 *
 * It exists because B3 fixed Export to write what the page currently shows rather than the last-saved
 * `soul.raw`. That made export depend on a client-side reimplementation of the backend's formatter —
 * and the golden test here is the guard against it drifting. If the two ever disagree, an exported
 * persona re-imports as a *different* persona, silently, which is worse than the bug it replaced.
 */

import { describe, it, expect } from "vitest";

import { countLines, renderSoul, soulPreview, soulsDiffer } from "./soul-render";

describe("renderSoul matches the Python renderer", () => {
  // Golden values produced by running `render_soul` in the repo's venv, not hand-written.
  it("renders a full soul byte-for-byte", () => {
    expect(
      renderSoul({
        title: "Luna",
        intro: "A calm companion.",
        sections: [
          { title: "Voice", body: "brief, warm" },
          { title: "Extra", body: "" },
        ],
        footer: "she is around",
      }),
    ).toBe("# Luna\n\nA calm companion.\n\n## Voice\n\nbrief, warm\n\n## Extra\n\n---\n\nshe is around\n");
  });

  it("falls back to the default title and emits only the heading when everything is blank", () => {
    expect(renderSoul({ title: "", intro: "", sections: [], footer: "" })).toBe("# Companion\n");
  });

  it("keeps a heading with an empty body — dropping it would change the parsed soul", () => {
    // The Python appends `## title` unconditionally and gates only the body.
    const out = renderSoul({ title: "Luna", intro: "", sections: [{ title: "Empty", body: "" }], footer: "" });
    expect(out).toContain("## Empty");
    expect(out).not.toContain("## Empty\n\n\n");
  });

  it("omits a blank intro and a blank footer rather than emitting empty blocks", () => {
    const out = renderSoul({ title: "Luna", intro: "   ", sections: [], footer: "" });
    expect(out).toBe("# Luna\n");
  });

  it("puts a `---` divider before the footer only", () => {
    const withFooter = renderSoul({ title: "Luna", intro: "", sections: [], footer: "bye" });
    expect(withFooter).toBe("# Luna\n\n---\n\nbye\n");
    const without = renderSoul({ title: "Luna", intro: "", sections: [], footer: "" });
    expect(without).not.toContain("---");
  });

  it("ends with exactly one newline", () => {
    const out = renderSoul({ title: "Luna", intro: "x", sections: [{ title: "s", body: "b" }], footer: "f" });
    expect(out.endsWith("\n")).toBe(true);
    expect(out.endsWith("\n\n")).toBe(false);
  });

  it("strips surrounding whitespace from every field", () => {
    const out = renderSoul({
      title: "  Luna  ",
      intro: "  hi  ",
      sections: [{ title: "  Voice  ", body: "  warm  " }],
      footer: "  bye  ",
    });
    expect(out).toBe("# Luna\n\nhi\n\n## Voice\n\nwarm\n\n---\n\nbye\n");
  });
});

describe("countLines", () => {
  it("counts a trailing-newline document as wc -l would", () => {
    // Blank lines count, matching `wc -l`, so the number in the dialog agrees with what a user sees
    // when they open the file in an editor.
    expect(countLines("# Luna\n\nhi\n")).toBe(3);
    expect(countLines("# Luna\nhi\n")).toBe(2);
  });

  it("counts a single line with no newline", () => {
    expect(countLines("# Luna")).toBe(1);
  });

  it("is zero for nothing — so a confirmation never claims to replace 0 lines of 0", () => {
    expect(countLines("")).toBe(0);
  });
});

describe("soulPreview", () => {
  it("returns the opening lines only", () => {
    expect(soulPreview("a\nb\nc\nd", 2)).toEqual(["a", "b"]);
  });

  it("is empty for nothing", () => {
    expect(soulPreview("")).toEqual([]);
  });
});

describe("soulsDiffer", () => {
  it("treats trailing whitespace as no difference", () => {
    expect(soulsDiffer("# Luna\n", "# Luna")).toBe(false);
  });

  it("sees a real content change", () => {
    expect(soulsDiffer("# Luna\n\nold\n", "# Luna\n\nnew\n")).toBe(true);
  });
});
