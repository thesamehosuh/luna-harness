import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { BUILTIN_THEMES, defaultTheme } from "./presets";
import {
  FONT_CHOICES,
  THEME_DEFAULT_FONT_ID,
  getFontChoice,
  type FontChoice,
} from "./fonts";
import type { DashboardTheme, ThemeListEntry } from "./types";
import { applyTheme, setFontOverride } from "./theme-runtime";
import { buildThemeList, indexUserThemeDefs } from "./theme-list";
import { migrateThemeName } from "./aliases";
import { api } from "@/lib/api";

declare global {
  interface Window {
    __LUNA_DASHBOARD_APPEARANCE__?: { theme: string; font: string; definition?: DashboardTheme | null };
  }
}

/** LocalStorage key — pre-applied before the React tree mounts to avoid
 *  a visible flash of the default palette on theme-overridden installs. */
const STORAGE_KEY = "hermes-dashboard-theme";

/** LocalStorage key for the font override (independent of theme). Holds a
 *  font id from the catalog in `fonts.ts`, or the `THEME_DEFAULT_FONT_ID`
 *  sentinel / absent = "use the active theme's font". Pre-applied before
 *  the React tree mounts (see `main.tsx`) to avoid a font flash. */
const FONT_STORAGE_KEY = "hermes-dashboard-font";

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function ThemeProvider({ children }: { children: ReactNode }) {
  /** Name of the currently active theme (built-in id or user YAML name). */
  const [themeName, setThemeName] = useState<string>(() => {
    if (typeof window === "undefined") return "sakura-dusk";
    const stored = window.__LUNA_DASHBOARD_APPEARANCE__?.theme ?? window.localStorage.getItem(STORAGE_KEY) ?? "sakura-dusk";
    const definition = window.__LUNA_DASHBOARD_APPEARANCE__?.definition;
    const migrated = migrateThemeName(stored, new Set(definition ? [definition.name] : []));
    // Write the migrated name back so future reads converge on the new
    // key and we eventually retire the alias entry.
    if (migrated !== stored) {
      window.localStorage.setItem(STORAGE_KEY, migrated);
    }
    return migrated;
  });

  /** All selectable themes (shown in the picker). Starts as just the built-ins — the client owns
   *  those, labels included — and the API call below adds user themes on top. */
  const [availableThemes, setAvailableThemes] = useState<ThemeListEntry[]>(() =>
    buildThemeList([]),
  );

  /** Full definitions for user themes keyed by name — the API provides
   *  these so custom YAMLs apply without a client-side stub. */
  const [userThemeDefs, setUserThemeDefs] = useState<
    Record<string, DashboardTheme>
  >(() => {
    const definition = typeof window === "undefined" ? null : window.__LUNA_DASHBOARD_APPEARANCE__?.definition;
    return definition ? { [definition.name]: definition } : {};
  });

  /** Active font-override id (independent of theme). `THEME_DEFAULT_FONT_ID`
   *  = no override. Seeded from localStorage so it's applied flash-free. */
  const [fontId, setFontId] = useState<string>(() => {
    if (typeof window === "undefined") return THEME_DEFAULT_FONT_ID;
    const stored = window.__LUNA_DASHBOARD_APPEARANCE__?.font ?? window.localStorage.getItem(FONT_STORAGE_KEY);
    const valid = stored && getFontChoice(stored) ? stored : THEME_DEFAULT_FONT_ID;
    setFontOverride(valid);
    return valid;
  });

  // Resolve a theme name to a full DashboardTheme, falling back to default
  // only when neither a built-in nor a user theme is found.
  const resolveTheme = useCallback(
    (name: string): DashboardTheme => {
      return (
        BUILTIN_THEMES[name] ??
        userThemeDefs[name] ??
        defaultTheme
      );
    },
    [userThemeDefs],
  );

  // Apply the active theme (and re-assert the font override at its tail)
  // whenever the theme, the resolver, OR the font override changes. Folding
  // font into the same effect means clearing the override re-runs applyTheme,
  // which restores the theme's own font; setting it re-asserts the override.
  useEffect(() => {
    setFontOverride(fontId);
    applyTheme(resolveTheme(themeName));
  }, [themeName, resolveTheme, fontId]);

  // Load user themes from the server once on mount. Built-ins are already in `availableThemes`
  // (the client owns them, labels included); this call only appends the user's YAML themes.
  useEffect(() => {
    let cancelled = false;
    api
      .getThemes()
      .then((resp) => {
        if (cancelled) return;
        if (resp.themes?.length) {
          // `buildThemeList` re-derives every built-in's label from `presets.ts` and ignores any
          // label the server sends for one, so the two can no longer disagree.
          setAvailableThemes(buildThemeList(resp.themes));
          // Index any definitions the server shipped (user themes).
          const defs = indexUserThemeDefs(resp.themes);
          if (Object.keys(defs).length > 0) setUserThemeDefs(defs);
          // Retired built-in names are now available to user YAML themes. A real custom theme
          // with a legacy name takes precedence over the migration alias.
          if (resp.active) {
            const migratedActive = migrateThemeName(resp.active, new Set(Object.keys(defs)));
            if (migratedActive !== themeName) {
              setThemeName(migratedActive);
              window.localStorage.setItem(STORAGE_KEY, migratedActive);
            }
            if (migratedActive !== resp.active) {
              api.setTheme(migratedActive).catch(() => {});
            }
          }
        }
        if (resp.active && !resp.themes?.length) {
          const migratedActive = migrateThemeName(resp.active);
          if (migratedActive !== themeName) {
            setThemeName(migratedActive);
            window.localStorage.setItem(STORAGE_KEY, migratedActive);
          }
          // If the server is still persisting the stale key, push the
          // migrated value back so it converges too — otherwise every
          // future page load would re-trigger this branch.
          if (migratedActive !== resp.active) {
            api.setTheme(migratedActive).catch(() => {});
          }
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load the server-persisted font override once on mount. The server is
  // the source of truth across browsers; localStorage just avoids the flash.
  useEffect(() => {
    let cancelled = false;
    api
      .getFontPref()
      .then((resp) => {
        if (cancelled) return;
        const serverId =
          resp?.font && getFontChoice(resp.font) ? resp.font : THEME_DEFAULT_FONT_ID;
        if (serverId !== fontId) {
          setFontId(serverId);
          if (typeof window !== "undefined") {
            window.localStorage.setItem(FONT_STORAGE_KEY, serverId);
          }
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setTheme = useCallback(
    (name: string) => {
      // Accept any name the server told us exists OR any built-in.
      const knownNames = new Set<string>([
        ...Object.keys(BUILTIN_THEMES),
        ...availableThemes.map((t) => t.name),
        ...Object.keys(userThemeDefs),
      ]);
      const migrated = knownNames.has(name) ? name : migrateThemeName(name);
      const next = knownNames.has(migrated) ? migrated : "sakura-dusk";
      setThemeName(next);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, next);
      }
      api.setTheme(next).catch(() => {});
    },
    [availableThemes, userThemeDefs],
  );

  const setFont = useCallback((id: string) => {
    const next = getFontChoice(id) ? id : THEME_DEFAULT_FONT_ID;
    setFontId(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(FONT_STORAGE_KEY, next);
    }
    api.setFontPref(next).catch(() => {});
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: resolveTheme(themeName),
      themeName,
      availableThemes,
      setTheme,
      fontId,
      fontChoices: FONT_CHOICES,
      setFont,
    }),
    [themeName, availableThemes, setTheme, resolveTheme, fontId, setFont],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: defaultTheme,
  themeName: "sakura-dusk",
  availableThemes: buildThemeList([]),
  setTheme: () => {},
  fontId: THEME_DEFAULT_FONT_ID,
  fontChoices: FONT_CHOICES,
  setFont: () => {},
});

interface ThemeContextValue {
  availableThemes: ThemeListEntry[];
  setTheme: (name: string) => void;
  theme: DashboardTheme;
  themeName: string;
  /** Active font-override id (`THEME_DEFAULT_FONT_ID` = no override). */
  fontId: string;
  /** Curated font catalog for the picker. */
  fontChoices: FontChoice[];
  /** Set the font override (independent of theme). */
  setFont: (id: string) => void;
}
