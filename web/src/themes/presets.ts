import lunaTokens from "../../../luna/assets/ui/themes.json";
import { parseColor, THEME_PRESET_PALETTES, type ThemePresetPalette } from "@hermes/shared";
import type { DashboardTheme, ThemePalette, ThemeTypography, ThemeLayout } from "./types";

/**
 * Built-in dashboard themes — and the single label authority for them.
 *
 * Each theme defines its own palette, typography, and layout so switching
 * themes produces visible changes beyond just color — fonts, density, and
 * corner-radius all shift to match the theme's personality.
 *
 * `GET /api/dashboard/themes` sends built-ins as bare ids, deliberately: this file owns the label and
 * description, so there is no second copy for the backend to disagree with. (It used to send them,
 * and shipped "Hermes Teal" while this file said "Luna Teal" — the same dashboard, two names.)
 * `hermes_cli/web_server_dashboard.py::_BUILTIN_THEME_IDS` mirrors only the *ids*, to keep a user
 * YAML from shadowing a built-in; the two id sets are pinned equal from both sides via
 * `builtin-theme-ids.json` (asserted in `presets.test.ts` and `luna/tests/contract/test_dashboard_theme_ids.py`).
 *
 * Mono takes its grayscale from `@hermes/shared` `THEME_PRESET_PALETTES` so
 * the dashboard and desktop retain one accessibility palette.
 */

// ---------------------------------------------------------------------------
// Shared typography / layout presets
// ---------------------------------------------------------------------------

/** Default system stack — neutral, safe fallback for every platform. */
const SYSTEM_SANS =
  'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const SYSTEM_MONO =
  'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace';

const DEFAULT_TYPOGRAPHY: ThemeTypography = {
  fontSans: SYSTEM_SANS,
  fontMono: SYSTEM_MONO,
  baseSize: "15px",
  lineHeight: "1.55",
  letterSpacing: "0",
};

const DEFAULT_LAYOUT: ThemeLayout = {
  radius: "0.5rem",
  density: "comfortable",
};

/**
 * Project a shared (desktop-shaped) preset palette onto the dashboard's
 * 3-slot model. The dashboard's `midground` is its text + primary-fill
 * colour, which is the desktop's `primary`; its `warmGlow` is the brand
 * accent stroke, which is the desktop's `midground` (falling back to `ring`).
 * `foreground` stays the dashboard's invisible white overlay. Dark palettes
 * are the dashboard's home turf, so a preset shipping `darkColors` is read
 * from that side.
 */
export function webPresetFromShared(
  preset: ThemePresetPalette,
): Omit<ThemePalette, "noiseOpacity"> {
  const colors = preset.darkColors ?? preset.colors;
  const [r, g, b] = parseColor(colors.midground ?? colors.ring) ?? [255, 255, 255];
  return {
    background: { hex: colors.background, alpha: 1 },
    midground: { hex: colors.primary, alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: `rgba(${r}, ${g}, ${b}, 0.3)`,
  };
}

// ---------------------------------------------------------------------------
// Themes
// ---------------------------------------------------------------------------

export const sakuraDuskTheme: DashboardTheme = {
  name: "sakura-dusk",
  label: "Sakura Dusk",
  description: "Blossom pink and warm gold against a deep violet night",
  palette: {
    background: { hex: "#17132b", alpha: 1 },
    midground: { hex: "#f6eefa", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(243, 214, 171, 0.24)",
    noiseOpacity: 0.18,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: '"Manrope", system-ui, sans-serif',
    fontDisplay: '"DM Serif Display", Georgia, serif',
    fontMono: `"JetBrains Mono", ${SYSTEM_MONO}`,
    letterSpacing: "-0.005em",
  },
  layout: { ...DEFAULT_LAYOUT, radius: "0.75rem" },
  colorScheme: "dark",
  colorOverrides: lunaTokens["sakura-dusk"].colors,
  seriesColors: { inputTokenAccent: "#eeafce", outputTokenAccent: "#b8a8dd" },
  terminalBackground: "#17132b",
  terminalForeground: "#f6eefa",
  swatchColors: ["#17132b", "#eeafce", "#f3d6ab"],
};

/** Kept as the default export for callers that only need the fallback theme. */
export const defaultTheme = sakuraDuskTheme;

export const sakuraDayTheme: DashboardTheme = {
  name: "sakura-day",
  label: "Sakura Day",
  description: "Soft blossom paper, plum ink, and muted rose",
  palette: {
    background: { hex: "#fbf0f8", alpha: 1 },
    midground: { hex: "#1e1830", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(185, 106, 132, 0.12)",
    noiseOpacity: 0,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: '"Manrope", system-ui, sans-serif',
    fontDisplay: '"DM Serif Display", Georgia, serif',
    fontMono: `"JetBrains Mono", ${SYSTEM_MONO}`,
    letterSpacing: "-0.005em",
  },
  layout: { ...DEFAULT_LAYOUT, radius: "0.75rem" },
  colorScheme: "light",
  colorOverrides: lunaTokens["sakura-day"].colors,
  seriesColors: { inputTokenAccent: "#a65370", outputTokenAccent: "#715689" },
  terminalBackground: "#fbf0f8",
  terminalForeground: "#1e1830",
  swatchColors: ["#fbf0f8", "#a65370", "#1e1830"],
};

export const monoTheme: DashboardTheme = {
  name: "mono",
  label: "Mono",
  description: "Clean grayscale — minimal and focused",
  palette: {
    ...webPresetFromShared(THEME_PRESET_PALETTES.mono),
    noiseOpacity: 0.6,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: '"Manrope", system-ui, sans-serif',
    fontMono: `"JetBrains Mono", ${SYSTEM_MONO}`,
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0",
  },
  colorScheme: "dark",
  colorOverrides: {
    success: "#a0d5ad",
    warning: "#e8d39f",
    destructive: "#f09a9a",
  },
  terminalBackground: "#0e0e0e",
  terminalForeground: "#eaeaea",
};

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  "sakura-dusk": sakuraDuskTheme,
  "sakura-day": sakuraDayTheme,
  mono: monoTheme,
};
