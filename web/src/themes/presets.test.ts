import { contrastRatio } from "@hermes/shared";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { BUILTIN_THEMES } from "./presets";
import { THEME_NAME_ALIASES, migrateThemeName } from "./aliases";
import { buildThemeList, indexUserThemeDefs } from "./theme-list";

describe("built-in theme accessibility", () => {
  it.each(Object.entries(BUILTIN_THEMES))("%s keeps text and accents legible on its canvas", (_name, theme) => {
    const canvas = theme.palette.background.hex;
    const text = theme.palette.midground.hex;
    const accent = theme.colorOverrides?.primary ?? text;

    expect(contrastRatio(text, canvas)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(accent, canvas)).toBeGreaterThanOrEqual(3);
    const accentText = theme.colorOverrides?.primaryForeground ?? canvas;
    expect(contrastRatio(accentText, accent)).toBeGreaterThanOrEqual(4.5);
    expect(theme.colorScheme).toMatch(/^(dark|light)$/);
  });

  it.each(Object.entries(BUILTIN_THEMES))("%s gives semantic colors 3:1 contrast", (_name, theme) => {
    const canvas = theme.palette.background.hex;
    for (const semantic of ["success", "warning", "destructive"] as const) {
      const color = theme.colorOverrides?.[semantic];
      expect(color, `${semantic} color`).toBeTruthy();
      expect(contrastRatio(color!, canvas), `${semantic} contrast`).toBeGreaterThanOrEqual(3);
    }
  });

  it("uses the requested Sakura Dusk palette as the dashboard default", () => {
    const dusk = BUILTIN_THEMES["sakura-dusk"];
    expect(dusk.palette.background.hex).toBe("#17132b");
    expect(dusk.colorOverrides?.card).toBe("#211b36");
    expect(dusk.colorOverrides?.primary).toBe("#eeafce");
    expect(dusk.colorOverrides?.ring).toBe("#b8a8dd");
    expect(dusk.colorOverrides?.warning).toBe("#f3d6ab");
    expect(dusk.palette.midground.hex).toBe("#f6eefa");
  });
});

describe("retired theme preference migration", () => {
  it("moves every retired built-in id to Sakura Dusk", () => {
    expect(Object.keys(THEME_NAME_ALIASES).sort()).toEqual(
      ["cyberpunk", "default", "default-large", "ember", "lens-5i", "luna-teal", "midnight", "nous-blue", "rose"].sort(),
    );
    for (const oldName of Object.keys(THEME_NAME_ALIASES)) {
      expect(migrateThemeName(oldName)).toBe("sakura-dusk");
    }
  });

  it("leaves current built-ins and user theme names alone", () => {
    expect(migrateThemeName("sakura-day")).toBe("sakura-day");
    expect(migrateThemeName("mono")).toBe("mono");
    expect(migrateThemeName("my-custom-theme")).toBe("my-custom-theme");
  });

  it("preserves a user theme whose name matches a retired built-in id", () => {
    expect(migrateThemeName("rose", new Set(["rose"]))).toBe("rose");
    expect(migrateThemeName("rose", new Set(["custom-theme"]))).toBe("sakura-dusk");
  });
});

// `builtin-theme-ids.json` is the hand-off between this file and
// `hermes_cli/web_server_dashboard.py::_BUILTIN_THEME_IDS`. The backend needs the ids (to stop a user
// YAML shadowing a built-in) but must not own the labels, so neither side reads the other's source:
// this test pins presets.ts to the manifest, and luna/tests/contract/test_dashboard_theme_ids.py pins the
// Python tuple to it. Add a preset and this fails until its id is recorded.
const manifest = JSON.parse(
  readFileSync(fileURLToPath(new URL("./builtin-theme-ids.json", import.meta.url)), "utf8"),
) as { ids: string[] };

describe("built-in theme ids match the cross-language manifest", () => {
  it("BUILTIN_THEMES keys are exactly the manifest's ids", () => {
    expect([...Object.keys(BUILTIN_THEMES)].sort()).toEqual([...manifest.ids].sort());
  });

  it("each preset's own name agrees with its key", () => {
    for (const [key, theme] of Object.entries(BUILTIN_THEMES)) {
      expect(theme.name).toBe(key);
    }
  });

  it("every preset has a label and a description to show", () => {
    for (const [name, theme] of Object.entries(BUILTIN_THEMES)) {
      expect(theme.label, `${name} label`).toBeTruthy();
      expect(theme.description, `${name} description`).toBeTruthy();
    }
  });
});

// The regression this whole exercise exists for: the backend used to ship its own label alongside
// each id, said "Hermes Teal", and the picker said "Luna Teal" — one dashboard, two names. The API
// no longer sends labels, so also prove the client ignores one if it ever appears.
describe("buildThemeList treats presets.ts as the label authority", () => {
  it("ignores a server-supplied label for a built-in", () => {
    const merged = buildThemeList([
      { name: "sakura-dusk", label: "Hermes Teal", description: "the canonical Hermes look" },
    ]);
    const entry = merged.find((t) => t.name === "sakura-dusk");
    expect(entry?.label).toBe(BUILTIN_THEMES["sakura-dusk"].label);
    expect(entry?.label).not.toBe("Hermes Teal");
    expect(entry?.description).toBe(BUILTIN_THEMES["sakura-dusk"].description);
  });

  it("lists every built-in even when the server sends none", () => {
    expect(buildThemeList([]).map((t) => t.name)).toEqual(Object.keys(BUILTIN_THEMES));
  });

  it("hides retired presets advertised by an older server", () => {
    expect(buildThemeList(Object.keys(THEME_NAME_ALIASES).map((name) => ({ name })))
      .map((theme) => theme.name)).toEqual(Object.keys(BUILTIN_THEMES));
  });

  it("keeps custom definitions named after retired presets", () => {
    const definition = { ...BUILTIN_THEMES.mono, name: "rose", label: "My rose" };
    expect(buildThemeList([{ name: "rose", label: "My rose", definition }])
      .find((theme) => theme.name === "rose")).toEqual({
        name: "rose", label: "My rose", description: "", definition,
      });
  });

  it("keeps built-in order stable regardless of server ordering", () => {
    const shuffled = buildThemeList([
      { name: "mono" },
      { name: "sakura-dusk" },
      { name: "sakura-day" },
    ]);
    expect(shuffled.map((t) => t.name)).toEqual(Object.keys(BUILTIN_THEMES));
  });

  it("appends a user theme with the label from its YAML, falling back to its name", () => {
    const merged = buildThemeList([
      { name: "sakura-dusk" },
      { name: "mine", label: "My Theme", description: "hand-rolled" },
      { name: "nameless" },
    ]);
    const user = merged.filter((t) => t.name === "mine");
    expect(user).toHaveLength(1);
    expect(user[0].label).toBe("My Theme");
    expect(user[0].description).toBe("hand-rolled");
    const nameless = merged.find((t) => t.name === "nameless");
    expect(nameless?.label).toBe("nameless");
    expect(nameless?.description).toBe("");
  });

  it("does not duplicate a built-in the server also listed", () => {
    const names = buildThemeList([{ name: "sakura-dusk" }, { name: "mono" }]).map((t) => t.name);
    expect(names.filter((n) => n === "sakura-dusk")).toHaveLength(1);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe("indexUserThemeDefs only indexes shipped definitions", () => {
  it("keys definitions by name and ignores label-only entries", () => {
    const definition = BUILTIN_THEMES.mono;
    const defs = indexUserThemeDefs([
      { name: "sakura-dusk" },
      { name: "mine", label: "Mine", definition },
    ]);
    expect(Object.keys(defs)).toEqual(["mine"]);
    expect(defs.mine).toBe(definition);
  });
});
