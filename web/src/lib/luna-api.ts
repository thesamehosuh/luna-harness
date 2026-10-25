/**
 * Client for the Luna companion API (/api/luna/*) — Behaviour + People dashboard pages.
 *
 * Thin wrapper over fetchJSON (session token / cookie auth / profile scoping included).
 */
import { fetchJSON } from "@/lib/api";

// ── Types (mirror luna/lib/luna_cli/web_routers.py) ─────────────────────────

export interface VerdictEvent {
  kind: string;
  at: string;
  tag: string;
  event: string;
  action: string;
  route: string;
  reason: string;
  who: string;
  value: string;
  addressed: string;
  openq: string;
  fit: string;
  msgfit: string;
  emoji: string;
  emojiconf: string;
  wait: string;
  raw: string;
}

export interface VerdictsResponse {
  events: VerdictEvent[];
  path: string;
  exists: boolean;
}

export interface WakeRow {
  kind: string;
  trigger_message_id: string | null;
  created_at: string;
  value: number | string | null;
  emoji: string | null;
  reason: string;
}

export interface ThresholdValue {
  value: number | string | boolean | null;
  default: number | string | boolean | null;
  overridden: boolean;
  type: string;
  unknown: boolean;
  /** Inclusive lower bound from the backend's cascade range table. Absent when the backend
   *  could not resolve one — the caller must then render a plain number input, never a slider
   *  with a guessed range. */
  min?: number;
  /** Inclusive upper bound. See `min`. */
  max?: number;
  /** Increment for a slider or number input. */
  step?: number;
  /** One line on what this threshold does, from the cascade schema. */
  description?: string | null;
}

export interface ThresholdsResponse {
  keys: string[];
  values: Record<string, ThresholdValue>;
  config_path: string;
}

export interface ThresholdWriteResult {
  ok: boolean;
  error: string | null;
  message?: string;
}

export interface ThresholdsWriteResponse {
  results: Record<string, ThresholdWriteResult>;
  state: ThresholdsResponse;
}

export interface CostResponse {
  unknown_cost_calls?: number;
  calls: number;
  total_usd: number;
  input_tokens: number;
  by_route: Array<{ route: string; calls: number; usd: number }>;
  window: string;
}

export interface JevHealth {
  status: string;
  detail: string;
  retry_after_seconds?: number | null;
}

export interface HealthResponse {
  home: string;
  config_path: string;
  config_exists: boolean;
  db_path: string;
  db_exists: boolean;
  log_path: string;
  log_exists: boolean;
  gateway_running: boolean | null;
  wakes_total: number | null;
  last_wake_at: string | null;
  settled_gated_recent: number;
  jev: JevHealth;
}

export interface ReplayResponse {
  ok: boolean;
  exit_code?: number;
  report?: unknown;
  output?: string;
  errors?: string;
  error?: string;
}

export interface IdentityRow {
  platform: string;
  user_id: string;
  peer_id: string;
  display_name: string | null;
  pronouns: string | null;
  aliases: string[];
  role: string | null;
  user_id_alt: string | null;
  is_manual: boolean;
  first_seen: string | null;
  updated_at: string | null;
}

export interface IdentityUpsert {
  platform: string;
  user_id: string;
  peer_id?: string | null;
  display_name?: string | null;
  pronouns?: string | null;
  aliases?: string[] | null;
  role?: string | null;
  user_id_alt?: string | null;
}

export interface AuditResponse {
  unmapped: Array<Record<string, unknown>>;
  colliding: Array<Record<string, unknown>>;
  orphans: Array<Record<string, unknown>>;
  ok: boolean;
}

export interface SyncResponse {
  aliases_written: number;
  cards: Array<Record<string, unknown>>;
  room: Record<string, unknown>;
}

// ── Character + Behaviour (P4) ─────────────────────────────────────────────

export interface SoulSection {
  title: string;
  body: string;
}

export interface Soul {
  title: string;
  intro: string;
  sections: SoulSection[];
  footer: string;
  exists?: boolean;
  path?: string;
  /** The verbatim SOUL.md text, returned by the backend for import/export. */
  raw?: string;
}

export interface OutputLimits {
  emoji_filter: boolean | string;
  strip_emoji: boolean;
  allowed_emoji: string[];
  max_lines: number | string;
  max_chars?: number;
  language?: string;
  style_filter?: boolean;
  sentence_breaks?: boolean;
}

export interface Skin {
  name: string;
  description: string;
  colors: Record<string, string>;
  active?: boolean;
  builtin?: boolean;
}

export interface SkillRow {
  name: string;
  category: string;
  auto_loaded: boolean;
  has_instructions: boolean;
}

export interface PersonaPreset {
  id: string;
  name: string;
  description: string;
  content: string;
}

export interface CharacterBundle {
  revision?: string;
  soul: Soul;
  output: OutputLimits;
  skins: Skin[];
  current_skin: string;
  skills: SkillRow[];
  auto_load: string[];
  presets: PersonaPreset[];
}

export interface PreviewResult {
  surface: string;
  input: string;
  output: string;
  changed: boolean;
  notes: string[];
  limits: OutputLimits;
}

export interface JevConfig {
  timeout_seconds?: number | null;
  route: string[];
  providers: Record<
    string,
    {
      base_url?: string;
      model?: string;
      api_key_env?: string;
      endpoint?: string;
      /** Accepted by `write_behaviour` (`behaviour.py`) but absent from this type until now — which
       *  is how the wake-policy form could silently drop it on save. */
      instructions?: string;
      tier?: string;
    }
  >;
}

export interface ConversationPolicy {
  enabled: boolean;
  settle_seconds: number;
  response_gap_seconds: number;
  max_pending: number;
  max_age_seconds: number;
  max_answer_age_seconds: number;
  max_turns_per_burst: number;
  burst_idle_seconds: number;
  max_turns_per_minute: number;
  max_parallel_rooms: number;
  overload_notice: boolean;
}

export interface ConversationDecision {
  platform: string;
  chat_id: string;
  thread_id: string;
  user_id: string;
  message_id: string;
  state: string;
  reason: string;
  at: number;
}

export interface BehaviourBundle {
  watched_chats?: string[];
  available_chats?: string[];
  revision?: string;
  conversation?: ConversationPolicy;
  conversation_bounds?: Partial<Record<keyof ConversationPolicy, [number, number]>>;
  conversation_status?: { active: ConversationDecision[]; waiting: ConversationDecision[]; recent: ConversationDecision[] };
  enabled: boolean | null;
  dry_run: boolean | null;
  room_register: string;
  settle_seconds: number | null;
  poll_seconds: number | null;
  stale_after_minutes: number | null;
  budget: Record<string, number | null>;
  mention_fallback: string[];
  reactions: { allowed: string[] };
  jev: JevConfig;
}

// ── Client ─────────────────────────────────────────────────────────────────

export interface ProfileTransferPreview {
  title: string;
  description: string;
  sections: string[];
  omitted: string[];
  missing_skills: string[];
  memory_enabled: false;
  ambient_enabled: false;
}

export const lunaApi = {
  getPeopleDirectory: () => fetchJSON<{ text: string; count: number }>("/api/luna/people"),
  exportProfile: (name: string) =>
    fetchJSON<Record<string, unknown>>(`/api/luna/profiles/${encodeURIComponent(name)}/export`),
  previewProfile: (bundle: unknown) =>
    fetchJSON<ProfileTransferPreview>("/api/luna/profiles/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bundle }),
    }),
  importProfile: (name: string, bundle: unknown) =>
    fetchJSON<{ ok: boolean; name: string; summary: ProfileTransferPreview }>("/api/luna/profiles/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, bundle }),
    }),
  getHealth: () => fetchJSON<HealthResponse>("/api/luna/health"),
  getVerdicts: (limit = 50) =>
    fetchJSON<VerdictsResponse>(`/api/luna/verdicts?limit=${limit}`),
  getWakes: (limit = 50) =>
    fetchJSON<{ wakes: WakeRow[] }>(`/api/luna/wakes?limit=${limit}`),
  getThresholds: () => fetchJSON<ThresholdsResponse>("/api/luna/thresholds"),
  setThresholds: (values: Record<string, unknown>) =>
    fetchJSON<ThresholdsWriteResponse>("/api/luna/thresholds", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    }),
  getCost: (days = 0) => fetchJSON<CostResponse>(`/api/luna/cost?days=${days}`),
  replay: (limit = 25, recent = 10) =>
    fetchJSON<ReplayResponse>("/api/luna/replay", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit, recent }),
    }),
  getIdentity: (platform?: string) =>
    fetchJSON<{ identities: IdentityRow[] }>(
      platform ? `/api/luna/identity?platform=${encodeURIComponent(platform)}` : "/api/luna/identity",
    ),
  upsertIdentity: (body: IdentityUpsert) =>
    fetchJSON<{ ok: boolean; identity: IdentityRow }>("/api/luna/identity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  mergeIdentity: (primary: string, alt: string, platform?: string) =>
    fetchJSON<Record<string, unknown>>("/api/luna/identity/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ primary, alt, platform }),
    }),
  getAudit: () => fetchJSON<AuditResponse>("/api/luna/peers/audit"),
  syncPeers: () =>
    // Content-Type must be set: the endpoint rejects anything but application/json so a
    // cross-origin no-cors form/fetch (which sends no content type) cannot trigger a sync.
    fetchJSON<SyncResponse>("/api/luna/peers/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }),

  getCharacter: () => fetchJSON<CharacterBundle>("/api/luna/character"),
  saveCharacter: (body: Record<string, unknown>, revision?: string) =>
    fetchJSON<{ bundle: CharacterBundle }>("/api/luna/character", {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(revision ? { "If-Match": revision } : {}) },
      body: JSON.stringify(body),
    }),
  saveSkinColors: (name: string, colors: Record<string, string>, description?: string) =>
    fetchJSON<{ bundle: CharacterBundle }>("/api/luna/character", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skin: name, skin_colors: colors, skin_description: description }),
    }),
  previewShaping: (text: string, surface = "group") =>
    fetchJSON<PreviewResult>("/api/luna/character/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, surface }),
    }),
  getBehaviour: () => fetchJSON<BehaviourBundle>("/api/luna/behaviour"),
  saveBehaviour: (body: Record<string, unknown>, revision?: string) =>
    // `results` is per-key. `put_behaviour` only raises when *every* key failed, so a 200 can still
    // carry rejected keys — and the caller cannot tell a clean write from a partial one without it.
    fetchJSON<{
      behaviour: BehaviourBundle;
      results?: Record<string, { ok: boolean; error?: string }>;
    }>("/api/luna/behaviour", {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(revision ? { "If-Match": revision } : {}) },
      body: JSON.stringify(body),
    }),
};

export {
  canSlider,
  clampThreshold,
  groupThresholdKeys,
  thresholdLabel,
  thresholdStep,
  type ThresholdGroup,
} from "@/lib/luna-thresholds";
