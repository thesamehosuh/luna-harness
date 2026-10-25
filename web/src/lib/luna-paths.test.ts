// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import {
  lunaBin,
  lunaCommand,
  lunaConsolePrompt,
  lunaDashboardCommand,
  lunaHome,
  lunaHomePath,
  lunaUpdateCommand,
} from "./luna-paths";

/**
 * The regression these guard: `EnvPage` rendered a hard-coded `~/.hermes/.env` while the backend was
 * serving the real path, so the page named the engine's home on a Luna install. The literals are
 * gone; what remains is that the backend's injected value actually wins.
 */
describe("luna paths come from the server-injected brand", () => {
  afterEach(() => {
    delete window.__LUNA_BRAND__;
  });

  it("falls back to the documented Luna defaults with no injected brand", () => {
    expect(lunaHome()).toBe("~/.luna");
    expect(lunaBin()).toBe("luna");
    expect(lunaUpdateCommand()).toBe("luna update");
    expect(lunaDashboardCommand()).toBe("luna dashboard");
    expect(lunaConsolePrompt()).toBe("luna> ");
  });

  it("prefers the injected home, so a named profile cannot be misreported", () => {
    window.__LUNA_BRAND__ = { home: "/srv/profiles/coder" };
    expect(lunaHome()).toBe("/srv/profiles/coder");
    expect(lunaHomePath(".env")).toBe("/srv/profiles/coder/.env");
  });

  it("joins home paths without doubling the separator", () => {
    window.__LUNA_BRAND__ = { home: "/srv/profiles/coder/" };
    expect(lunaHomePath(".env")).toBe("/srv/profiles/coder/.env");
    expect(lunaHomePath("backups", "b.zip")).toBe("/srv/profiles/coder/backups/b.zip");
  });

  it("ignores an empty injected value rather than rendering nothing", () => {
    // A blank from the server is not a real value; rendering "" would produce `<code></code>`.
    window.__LUNA_BRAND__ = { home: "", bin: "" };
    expect(lunaHome()).toBe("~/.luna");
    expect(lunaBin()).toBe("luna");
  });

  it("builds subcommands from the injected binary name", () => {
    window.__LUNA_BRAND__ = { bin: "luna-dev" };
    expect(lunaCommand("skills search")).toBe("luna-dev skills search");
  });

  it("never produces an engine path or command name", () => {
    // The whole point: no value reachable from this module may say `.hermes` or `hermes`.
    window.__LUNA_BRAND__ = { home: "/srv/profiles/coder", bin: "luna" };
    const rendered = [
      lunaHome(),
      lunaBin(),
      lunaHomePath(".env"),
      lunaUpdateCommand(),
      lunaDashboardCommand(),
      lunaConsolePrompt(),
      lunaCommand("gateway start"),
    ].join(" ");
    expect(rendered).not.toMatch(/hermes/i);
  });
});
