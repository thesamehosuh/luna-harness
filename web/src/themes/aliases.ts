/** Retired built-in ids map forward so browser and server preferences survive upgrades. */
export const THEME_NAME_ALIASES: Readonly<Record<string, string>> = {
  default: "sakura-dusk",
  "luna-teal": "sakura-dusk",
  "default-large": "sakura-dusk",
  "nous-blue": "sakura-dusk",
  midnight: "sakura-dusk",
  ember: "sakura-dusk",
  cyberpunk: "sakura-dusk",
  rose: "sakura-dusk",
  "lens-5i": "sakura-dusk",
};

export function migrateThemeName(name: string, customThemeNames?: ReadonlySet<string>): string {
  if (customThemeNames?.has(name)) return name;
  return THEME_NAME_ALIASES[name] ?? name;
}
