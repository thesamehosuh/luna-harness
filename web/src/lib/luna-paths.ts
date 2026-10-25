/**
 * The one place the dashboard is allowed to name a Luna path or command.
 *
 * These used to be typed as JSX literals (`~/.hermes/.env`, `hermes update`, `hermes>`), which made
 * every one of them an independent copy that could go stale and quietly misreport where the user's
 * files actually are — the dashboard naming the engine's home while the CLI reads Luna's. `EnvPage`
 * showed `~/.hermes/.env` next to a backend that was serving a real path two requests away.
 *
 * `lunaHome()` is backend-sourced: the server injects `window.__LUNA_BRAND__` into index.html at
 * serve time, using the same resolver the `luna` CLI uses for its own home. So the dashboard and the
 * terminal cannot disagree. Server-injected rather than fetched, because these render on first paint
 * — a fetch would show a fallback and then correct it.
 *
 * The defaults below are only a safety net for contexts with no injected brand: unit tests, and the
 * `dashboard_ui` component contracts. They are the documented Luna defaults, so a miss degrades to
 * correct-in-the-common-case rather than to the engine's old paths.
 */

declare global {
  interface Window {
    /** Injected into index.html by the server; see `luna-paths.ts`. */
    __LUNA_BRAND__?: {
      home?: string;
      bin?: string;
      consolePrompt?: string;
      updateCommand?: string;
      dashboardCommand?: string;
      docsUrl?: string;
    };
  }
}

const FALLBACK_BRAND = {
  home: "~/.luna",
  bin: "luna",
  consolePrompt: "luna> ",
  updateCommand: "luna update",
  dashboardCommand: "luna dashboard",
  // Empty by default. The Docs page falls back to the in-dashboard /help rather than iframing a
  // third-party site that does not document Luna. The backend only forwards http(s) values.
  docsUrl: "",
} as const;

function brand<K extends keyof typeof FALLBACK_BRAND>(key: K): string {
  const injected = typeof window === "undefined" ? undefined : window.__LUNA_BRAND__?.[key];
  // An empty string from the server is not a real value; fall through rather than render "".
  return typeof injected === "string" && injected.length > 0 ? injected : FALLBACK_BRAND[key];
}

/** The Luna home directory — `$LUNA_HOME` → `$HERMES_HOME` → `~/.luna`, resolved server-side. */
export function lunaHome(): string {
  return brand("home");
}

/** The CLI executable name. `lunaBin()` is `"luna"`, so `lunaHome()`/`lunaBin()` read as a pair. */
export function lunaBin(): string {
  return brand("bin");
}

/** A path inside the Luna home, e.g. `lunaHomePath(".env")` → `~/.luna/.env`. */
export function lunaHomePath(...segments: string[]): string {
  const home = lunaHome().replace(/\/+$/, "");
  return segments.length === 0 ? home : `${home}/${segments.join("/")}`;
}

/** `luna update` — as a command a user could paste. */
export function lunaUpdateCommand(): string {
  return brand("updateCommand");
}

/** `luna dashboard` — as a command a user could paste. */
export function lunaDashboardCommand(): string {
  return brand("dashboardCommand");
}

/** Operator-configured docs site (`luna.docs.url`), or "" when unset. Never a literal URL. */
export function lunaDocsUrl(): string {
  return brand("docsUrl");
}

/** The console prompt the embedded terminal shows: `luna> `. */
export function lunaConsolePrompt(): string {
  return brand("consolePrompt");
}

/** `luna <subcommand>` — for "run `luna skills search`" style copy. */
export function lunaCommand(subcommand: string): string {
  return `${lunaBin()} ${subcommand}`;
}
