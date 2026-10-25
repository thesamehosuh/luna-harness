import type { ComponentType } from "react";
import {
  Activity, BarChart3, BookOpen, Brain, Clock, Cpu, FileText, FolderOpen,
  KeyRound, LifeBuoy, MessageSquare, Package, Plug, Puzzle, Radio,
  Rocket, Settings, ShieldCheck, Sparkles, Terminal, Users, Webhook, Wrench,
} from "lucide-react";
import type { Translations } from "@/i18n/types";

export type NavGroup = "companion" | "workspace" | "connections" | "settings";
export interface NavItem {
  path: string;
  label: string;
  labelKey?: keyof Translations["app"]["nav"];
  icon: ComponentType<{ className?: string }>;
  group?: NavGroup;
}

export const NAV_GROUPS: { id: NavGroup; label: string }[] = [
  { id: "companion", label: "Your companion" },
  { id: "workspace", label: "Workspace" },
  { id: "connections", label: "Connections" },
  { id: "settings", label: "Manage" },
];

/** Labels, title resolution and sidebar grouping share the same route metadata. */
export const DASHBOARD_NAV: NavItem[] = [
  { path: "/character", label: "Character", icon: Sparkles, group: "companion" },
  { path: "/behaviour", label: "Behaviour", icon: Activity, group: "companion" },
  { path: "/people", label: "People", icon: Users, group: "companion" },
  { path: "/memory", label: "Memory", icon: Brain, group: "companion" },
  { path: "/sessions", labelKey: "sessions", label: "Sessions", icon: MessageSquare, group: "workspace" },
  { path: "/files", label: "Files", icon: FolderOpen, group: "workspace" },
  { path: "/cron", labelKey: "cron", label: "Cron", icon: Clock, group: "workspace" },
  { path: "/analytics", labelKey: "analytics", label: "Analytics", icon: BarChart3, group: "workspace" },
  { path: "/channels", label: "Channels", icon: Radio, group: "connections" },
  { path: "/models", labelKey: "models", label: "Models", icon: Cpu, group: "connections" },
  { path: "/skills", labelKey: "skills", label: "Skills", icon: Package, group: "connections" },
  { path: "/plugins", labelKey: "plugins", label: "Plugins", icon: Puzzle, group: "connections" },
  { path: "/mcp", label: "MCP", icon: Plug, group: "connections" },
  { path: "/webhooks", label: "Webhooks", icon: Webhook, group: "connections" },
  { path: "/pairing", label: "Pairing", icon: ShieldCheck, group: "connections" },
  { path: "/profiles", labelKey: "profiles", label: "Profiles", icon: Users, group: "settings" },
  { path: "/config", labelKey: "config", label: "Config", icon: Settings, group: "settings" },
  { path: "/env", labelKey: "keys", label: "Keys", icon: KeyRound, group: "settings" },
  { path: "/logs", labelKey: "logs", label: "Logs", icon: FileText, group: "settings" },
  { path: "/system", label: "System", icon: Wrench, group: "settings" },
  { path: "/onboarding", label: "Setup", icon: Rocket, group: "settings" },
  { path: "/help", label: "Help", icon: LifeBuoy, group: "settings" },
  { path: "/docs", labelKey: "documentation", label: "Documentation", icon: BookOpen, group: "settings" },
];

export const CHAT_NAV_ITEM: NavItem = {
  path: "/chat", labelKey: "chat", label: "Chat", icon: Terminal, group: "workspace",
};

export function navLabel(item: NavItem, t: Translations): string {
  return (item.labelKey && t.app.nav[item.labelKey]) || item.label;
}

export function navGroupLabel(group: NavGroup, t: Translations): string {
  return t.app.navSections?.[group] ?? NAV_GROUPS.find((entry) => entry.id === group)!.label;
}
