import type { Translations } from "@/i18n/types";

import { CHAT_NAV_ITEM, DASHBOARD_NAV, navLabel } from "./navigation";

export function resolvePageTitle(
  pathname: string,
  t: Translations,
  pluginTabs: { path: string; label: string }[],
): string {
  const normalized = pathname.replace(/\/$/, "") || "/";
  if (normalized === "/") {
    return t.app.nav.sessions;
  }
  const plugin = pluginTabs.find((p) => p.path === normalized);
  if (plugin) {
    return plugin.label;
  }
  if (normalized === "/profiles/new") return t.profiles?.newProfile ?? "New profile";
  const item = [...DASHBOARD_NAV, CHAT_NAV_ITEM].find((entry) => entry.path === normalized);
  if (item) return navLabel(item, t);
  // Derive title from pathname: "/profiles" → "Profiles"
  const segment = normalized.slice(1);
  if (segment) {
    return segment.charAt(0).toUpperCase() + segment.slice(1);
  }
  return t.app.webUi;
}
