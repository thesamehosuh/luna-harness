import { useCallback, useEffect, useMemo, useState } from "react";
import { Play, Plus, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/ui/h2";
import { Card, CardContent } from "@/components/ui/Card";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { BlossomBranch } from "@/components/BlossomBranch";
import { usePageHeader } from "@/contexts/usePageHeader";
import { errorMessage } from "@/lib/api-error";
import { isDraftDirty, useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import {
  canSlider,
  clampThreshold,
  groupThresholdKeys,
  lunaApi,
  thresholdLabel,
  thresholdStep,
  type BehaviourBundle,
  type ConversationPolicy,
  type HealthResponse,
  type JevConfig,
  type ThresholdValue,
  type ThresholdsResponse,
  type VerdictEvent,
} from "@/lib/luna-api";

const inputClass = "rounded-xl border border-border bg-background/70 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

/** Keys the backend accepts per provider that this form does not render. Preserved on write. */
const PROVIDER_PASSTHROUGH = ["endpoint", "instructions", "tier", "timeout_seconds"] as const;

/** The non-rendered provider keys of one loaded entry, kept so a save cannot delete them. */
function providerExtras(entry: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of PROVIDER_PASSTHROUGH) {
    const value = entry[key];
    if (value !== undefined && value !== null && value !== "") out[key] = value;
  }
  return out;
}

/**
 * The wake policy exactly as `WakePolicyCard` reads it out of a loaded bundle, in the same shape its
 * draft patch takes. Having both sides built by the same normalisation rules is what makes the dirty
 * comparison meaningful: the form round-trips strings through join/split (a route list becomes
 * `"a, b"`, a reaction list becomes `"a b"`), so the baseline has to be normalised the same way or
 * a freshly-loaded card would read as edited.
 */
function policyBaseline(behaviour: BehaviourBundle) {
  return {
    ...(behaviour.conversation ? { conversation: { ...behaviour.conversation } } : {}),
    dry_run: behaviour.dry_run !== false,
    room_register: behaviour.room_register ?? "",
    watched_chats: behaviour.watched_chats ?? [],
    budget: { ...behaviour.budget },
    mention_fallback: (behaviour.mention_fallback ?? []).map((s) => s.trim()).filter(Boolean),
    reactions: { allowed: (behaviour.reactions?.allowed ?? []).filter(Boolean) },
    jev: {
      timeout_seconds: Number(behaviour.jev?.timeout_seconds ?? 20),
      route: behaviour.jev?.route ?? [],
      providers: Object.fromEntries(
        Object.entries(behaviour.jev?.providers ?? {}).map(([name, entry]) => [
          name,
          // The draft drops empty sub-fields rather than sending them as ""; match that here or a
          // provider with one blank column would look edited.
          Object.fromEntries(
            Object.entries({
              ...providerExtras(entry),
              base_url: entry.base_url ?? "",
              model: entry.model ?? "",
              api_key_env: entry.api_key_env ?? "",
            }).filter(([, value]) => value !== ""),
          ),
        ]),
      ),
    } as JevConfig,
  };
}

function HealthStrip({ health }: { health: HealthResponse }) {
  const gateway =
    health.gateway_running === null ? "unknown" : health.gateway_running ? "running" : "stopped";
  const jevTone =
    health.jev.status === "healthy" ? "default" : health.jev.status === "down" ? "destructive" : "secondary";
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-2 py-3 text-sm">
        <span className="font-medium">Wake pipeline</span>
        <Badge tone={health.gateway_running ? "default" : "secondary"}>gateway: {gateway}</Badge>
        <Badge tone={jevTone}>jev: {health.jev.status}</Badge>
        <Badge tone="secondary">wakes: {health.wakes_total ?? 0}</Badge>
        {health.last_wake_at && (
          <span className="text-muted-foreground">last wake {health.last_wake_at}</span>
        )}
        <span className="ml-auto text-muted-foreground">{health.jev.detail}</span>
      </CardContent>
    </Card>
  );
}

/**
 * One threshold: a labelled description, a range control, and a reset.
 *
 * Edits land in local draft state and are committed on release (pointer/key up) or blur, never per
 * pixel of a drag — the previous version wrote to `config.yaml` on every `onChange`, so dragging a
 * slider fired a network write per step and fought the user mid-drag.
 *
 * The range comes from the backend's cascade bounds. A threshold with no resolvable bound renders a
 * number input only: a slider needs a real range, and inventing one is what let a minutes value of
 * 10 render against `max=1` and write 0 on a leftward drag.
 */
export function ThresholdRow({
  name,
  entry,
  saving,
  onCommit,
  onReset,
}: {
  name: string;
  entry: ThresholdValue;
  saving: boolean;
  onCommit: (value: number) => void;
  onReset: () => void;
}) {
  const committed = Number(entry.value ?? entry.default ?? 0);
  const [draft, setDraft] = useState<number>(committed);
  const label = thresholdLabel(name);

  // Adopt the server's value when it changes, but never clobber a field the user is mid-edit on.
  // Comparing during render (rather than in an effect) keeps the adopted value in the same commit
  // as the prop change, so the number never paints once with the stale draft.
  const [dirty, setDirty] = useState(false);
  const [lastCommitted, setLastCommitted] = useState(committed);
  if (committed !== lastCommitted) {
    setLastCommitted(committed);
    if (!dirty) setDraft(committed);
  }

  const isNumber =
    entry.type === "int" || entry.type === "float" || typeof entry.value === "number";
  const step = entry.step ?? thresholdStep(entry.type);
  const slider = isNumber && canSlider(entry);

  const commit = (raw: number) => {
    const next = clampThreshold(raw, entry);
    setDraft(next);
    setDirty(false);
    if (next !== committed) onCommit(next);
  };

  if (!isNumber) {
    return (
      <div className="flex items-center gap-3 py-1.5">
        <div className="w-64 shrink-0">
          <div className="text-sm">{label}</div>
        </div>
        <code className="text-sm">{String(entry.value)}</code>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 py-1.5">
      <div className="w-64 shrink-0">
        <div className="text-sm">{label}</div>
        <div className="text-xs text-muted-foreground">
          {entry.description ?? `default ${String(entry.default)}`}
          {entry.overridden && <span className="ml-1 text-warning">overridden</span>}
          {entry.unknown && <span className="ml-1">not a known cascade field</span>}
        </div>
      </div>
      {slider ? (
        <input
          type="range"
          min={entry.min}
          max={entry.max}
          step={step}
          value={draft}
          disabled={saving}
          onChange={(e) => {
            setDirty(true);
            setDraft(Number(e.target.value));
          }}
          onPointerUp={() => commit(draft)}
          onKeyUp={() => commit(draft)}
          onBlur={() => commit(draft)}
          className="w-52"
          aria-label={label}
          aria-valuetext={`${draft} (default ${String(entry.default)})`}
        />
      ) : null}
      <input
        type="number"
        min={entry.min}
        max={entry.max}
        step={step}
        value={draft}
        disabled={saving}
        onChange={(e) => {
          setDirty(true);
          const next = Number(e.target.value);
          // An empty or half-typed field parses to NaN; hold the last good draft rather than
          // writing NaN into config.yaml.
          if (Number.isFinite(next)) setDraft(next);
        }}
        onBlur={(e) => {
          const next = Number(e.currentTarget.value);
          commit(Number.isFinite(next) ? next : committed);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
        className="w-24 rounded border bg-transparent px-2 py-1 text-sm"
        aria-label={`${label} value`}
      />
      <Button ghost
        size="sm"
        disabled={saving || !entry.overridden}
        onClick={onReset}
        title={`Reset ${label} to its code default`}
        aria-label={`Reset ${label} to its code default`}
      >
        <RotateCcw className="h-3.5 w-3.5" />
      </Button>
      {saving && <Spinner className="h-3.5 w-3.5" />}
    </div>
  );
}

/**
 * The wake-policy form: 11 fields that used to be split across four Save buttons.
 * That layout was a data-loss bug, not just clutter. `onSave` took a partial patch, so saving one
 * group wrote that group and silently dropped the edits sitting in the others. It now writes the
 * whole policy as one patch, and the button is live only when the draft differs from what was
 * loaded. The threshold editors elsewhere on the page are untouched — they commit per field on
 * release by design (see `ThresholdRow`).
 */
export function WakePolicyCard({
  behaviour,
  saving,
  onSave,
}: {
  behaviour: BehaviourBundle;
  saving: boolean;
  onSave: (updates: Record<string, unknown>) => void | Promise<boolean>;
}) {
  const [dryRun, setDryRun] = useState(behaviour.dry_run !== false);
  const [conversation, setConversation] = useState(behaviour.conversation);
  const [watchedChats, setWatchedChats] = useState((behaviour.watched_chats ?? []).join(", "));
  const [register, setRegister] = useState(behaviour.room_register ?? "");
  const [budget, setBudget] = useState<Record<string, number | null>>({ ...behaviour.budget });
  const [mentions, setMentions] = useState((behaviour.mention_fallback ?? []).join("\n"));
  const [reactions, setReactions] = useState((behaviour.reactions?.allowed ?? []).join(" "));
  const [route, setRoute] = useState((behaviour.jev?.route ?? []).join(", "));
  const [timeout, setTimeoutSeconds] = useState(Number(behaviour.jev?.timeout_seconds ?? 20));
  const [providers, setProviders] = useState(() =>
    Object.entries(behaviour.jev?.providers ?? {}).map(([name, entry]) => ({
      name,
      base_url: entry.base_url ?? "",
      model: entry.model ?? "",
      api_key_env: entry.api_key_env ?? "",
      // The backend accepts six keys per provider and replaces the map wholesale on write
      // (`behaviour.py`: base_url, model, api_key_env, endpoint, instructions, tier). This form
      // renders three of them, so the other three are carried verbatim. Dropping them meant any
      // wake-policy save silently deleted a hand-written `endpoint`/`tier`/`instructions` from
      // config.yaml — a regression introduced when the four save buttons were collapsed into one.
      extra: providerExtras(entry),
    })),
  );

  const jev: JevConfig = {
    timeout_seconds: timeout,
    route: route.split(",").map((s) => s.trim()).filter(Boolean),
    providers: Object.fromEntries(
      providers
        .filter((p) => p.name.trim())
        .map((p) => [
          p.name.trim(),
          {
            ...(p.extra ?? {}),
            ...(p.base_url.trim() ? { base_url: p.base_url.trim() } : {}),
            ...(p.model.trim() ? { model: p.model.trim() } : {}),
            ...(p.api_key_env.trim() ? { api_key_env: p.api_key_env.trim() } : {}),
          },
        ]),
    ),
  };

  // One patch, built from the whole draft, and the value it was loaded with. Building it as a
  // single object is the point: with four per-group Save buttons each writing only its own slice,
  // pressing "Save budget" dropped the room-voice textarea 20 lines above it, and the route
  // chain's Save dropped the mention/reaction policy. Both were silent.
  const updates = useMemo(
    () => ({
      ...(conversation ? { conversation } : {}),
      dry_run: dryRun,
      room_register: register,
      watched_chats: watchedChats.split(/[\s,]+/).filter(Boolean),
      budget: { ...budget },
      mention_fallback: mentions.split("\n").map((s) => s.trim()).filter(Boolean),
      reactions: { allowed: reactions.split(/\s+/).filter(Boolean) },
      jev,
    }),
    // `jev` is rebuilt on every render, so depend on the parts that actually build it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [conversation, dryRun, register, watchedChats, budget, mentions, reactions, timeout, route, providers],
  );

  const baseline = useMemo(() => policyBaseline(behaviour), [behaviour]);

  const dirty = isDraftDirty(updates, baseline);

  useUnsavedChanges({
    id: "behaviour-wake-policy",
    label: "wake policy",
    dirty,
    // Returned, not discarded: the arrow body previously had no `return`, so `saveAll` received
    // `undefined`, resolved immediately, and the navigation ran while the PUT was still in flight.
    onSave: async () => (await onSave(updates)) !== false,
    onDiscard: () => {
      setConversation(baseline.conversation);
      setDryRun(baseline.dry_run);
      setRegister(baseline.room_register);
      setWatchedChats(baseline.watched_chats.join(", "));
      setBudget({ ...baseline.budget });
      setMentions(baseline.mention_fallback.join("\n"));
      setReactions(baseline.reactions.allowed.join(" "));
      setRoute(baseline.jev.route.join(", "));
      setTimeoutSeconds(Number(baseline.jev.timeout_seconds ?? 20));
      setProviders(
        Object.entries(baseline.jev.providers).map(([name, entry]) => ({
          name,
          base_url: entry.base_url ?? "",
          model: entry.model ?? "",
          api_key_env: entry.api_key_env ?? "",
          extra: providerExtras(entry),
        })),
      );
    },
  });

  return (
    <Card>
      <CardContent className="p-5 md:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <H2 className="text-base">Wake policy</H2>
          {dirty && (
            <span className="text-xs text-warning" data-wake-policy-dirty>
              unsaved changes &middot; one save writes all of it
            </span>
          )}
          <Button
            size="sm"
            className="ml-auto"
            disabled={saving || !dirty}
            onClick={() => onSave(updates)}
            data-wake-policy-save
          >
            {saving ? "Saving\u2026" : "Save wake policy"}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Dry-run decides but never sends. Cooldowns and caps keep wakes rare; the route chain
          is who judges (first healthy route answers).
        </p>

        {conversation && (
          <fieldset className="my-5 space-y-3 rounded-xl border border-border p-4">
            <legend className="px-1 text-sm font-medium">Group conversation</legend>
            <p className="text-xs text-muted-foreground">Take turns within each group or topic. Replies address one person at a time. Busy bursts receive a few selected answers; skipped questions need a fresh tag. Direct messages keep their own flow.</p>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={conversation.enabled} onChange={(e) => setConversation({ ...conversation, enabled: e.target.checked })} />
                Coordinate group replies
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={conversation.overload_notice} onChange={(e) => setConversation({ ...conversation, overload_notice: e.target.checked })} />
                Acknowledge a busy burst once
              </label>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {([
                ["max_turns_per_burst", "Answers per burst"],
                ["max_turns_per_minute", "Answers per minute, per topic"],
                ["settle_seconds", "Collect nearby messages (seconds)"],
                ["response_gap_seconds", "Pause between answers (seconds)"],
                ["burst_idle_seconds", "Quiet time before a new burst (seconds)"],
                ["max_pending", "Maximum waiting requests"],
                ["max_age_seconds", "Discard waiting requests after (seconds)"],
                ["max_answer_age_seconds", "Stop an answer after (seconds)"],
                ["max_parallel_rooms", "Groups or topics answering at once"],
              ] as [keyof ConversationPolicy, string][]).map(([key, label]) => (
                <label key={key} className="text-xs text-muted-foreground">
                  {label}
                  <input className={`${inputClass} mt-1 w-full`} type="number"
                    min={behaviour.conversation_bounds?.[key]?.[0]}
                    max={behaviour.conversation_bounds?.[key]?.[1]}
                    step={key === "settle_seconds" || key === "response_gap_seconds" ? 0.1 : 1}
                    value={Number(conversation[key])}
                    onChange={(e) => setConversation({ ...conversation, [key]: e.target.valueAsNumber })} />
                </label>
              ))}
            </div>
            {behaviour.conversation_status && (
              <div className="space-y-1 text-xs text-muted-foreground" role="status">
                <p>{behaviour.conversation_status.active.length} answering · {behaviour.conversation_status.waiting.length} waiting. Refresh to update activity.</p>
                {behaviour.conversation_status.recent.slice(0, 5).map((decision) => (
                  <p key={`${decision.platform}:${decision.chat_id}:${decision.thread_id}:${decision.message_id}`}>
                    {decision.platform} · {decision.chat_id}{decision.thread_id ? ` / topic ${decision.thread_id}` : ""} · person {decision.user_id}: {decision.state.replaceAll("_", " ")} ({decision.reason.replaceAll("_", " ")})
                  </p>
                ))}
              </div>
            )}
          </fieldset>
        )}

        <div className="flex flex-wrap items-center gap-4 pt-3 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            dry-run (decide but never send)
          </label>
        </div>
        <label className="mt-2 block text-xs text-muted-foreground">
          room voice (how the room talks, which shapes the companion’s judgments)
          <textarea
            className={`${inputClass} mt-1 h-16 w-full`}
            value={register}
            onChange={(e) => setRegister(e.target.value)}
          />
        </label>

        <fieldset className="mt-3 text-xs text-muted-foreground">
          <legend>Groups where your companion may speak up</legend>
          {(behaviour.available_chats ?? []).map((chat) => (
            <label key={chat} className="mt-2 flex items-center gap-2">
              <input type="checkbox" checked={watchedChats.split(/[\s,]+/).includes(String(chat))}
                onChange={(event) => {
                  const current = watchedChats.split(/[\s,]+/).filter(Boolean);
                  setWatchedChats((event.target.checked ? [...current, String(chat)] : current.filter((value) => value !== String(chat))).join(", "));
                }} />
              Group {chat}
            </label>
          ))}
          <p className="mt-2">Allow groups in Channels first, then choose which to watch. Each topic is evaluated separately.
            With no selection, ambient wakes watch no groups.</p>
        </fieldset>

        <div className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Budget & cooldowns (minutes / max per day / week)
        </div>
        <div className="grid grid-cols-1 gap-3 pt-2 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(budget).map(([key, value]) => (
            <label key={key} className="text-xs text-muted-foreground">
              {thresholdLabel(key)}
              <input
                className={`${inputClass} mt-1 w-full`}
                type="number"
                value={value ?? ""}
                onChange={(e) => setBudget({ ...budget, [key]: e.target.value === "" && (key.endsWith("max_per_day") || key.endsWith("max_per_week")) ? null : Number(e.target.value) })}
              />
            </label>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs text-muted-foreground">
            mention fallback regexes (one per line; empty = stay silent when jev is down)
            <textarea
              className={`${inputClass} mt-1 h-20 w-full font-mono`}
              value={mentions}
              onChange={(e) => setMentions(e.target.value)}
            />
          </label>
          <label className="text-xs text-muted-foreground">
            allowed reaction emoji (space separated; empty = reactions off)
            <input
              className={`${inputClass} mt-1 w-full`}
              value={reactions}
              onChange={(e) => setReactions(e.target.value)}
            />
          </label>
        </div>

        <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          jev route chain (names resolve into providers below)
        </div>
        <label className="mt-1 block text-xs text-muted-foreground">
          route order (comma separated)
          <input className={`${inputClass} mt-1 w-full max-w-xl`} value={route} onChange={(e) => setRoute(e.target.value)} />
        </label>
        <div className="mt-2 space-y-1">
          {providers.map((provider, index) => (
            <div key={index} className="flex flex-col gap-2 rounded-xl border border-border p-3 sm:flex-row sm:flex-wrap sm:items-center sm:border-0 sm:p-0">
              <input
                className={`${inputClass} w-full font-mono sm:w-36`}
                placeholder="name"
                value={provider.name}
                onChange={(e) =>
                  setProviders(providers.map((p, i) => (i === index ? { ...p, name: e.target.value } : p)))
                }
              />
              <input
                className={`${inputClass} w-full font-mono sm:w-64`}
                placeholder="base_url"
                value={provider.base_url}
                onChange={(e) =>
                  setProviders(providers.map((p, i) => (i === index ? { ...p, base_url: e.target.value } : p)))
                }
              />
              <input
                className={`${inputClass} w-full font-mono sm:w-40`}
                placeholder="model"
                value={provider.model}
                onChange={(e) =>
                  setProviders(providers.map((p, i) => (i === index ? { ...p, model: e.target.value } : p)))
                }
              />
              <input
                className={`${inputClass} w-full font-mono sm:w-48`}
                placeholder="api_key_env"
                value={provider.api_key_env}
                onChange={(e) =>
                  setProviders(providers.map((p, i) => (i === index ? { ...p, api_key_env: e.target.value } : p)))
                }
              />
              <Button ghost
                size="sm"
                onClick={() => setProviders(providers.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-center gap-2">
          <Button outlined
            size="sm"
            onClick={() =>
              setProviders([
                ...providers,
                // `extra` is empty for a newly-added route; a fresh entry has nothing to preserve.
                { name: "", base_url: "", model: "", api_key_env: "", extra: {} },
              ])
            }
          >
            <Plus className="mr-1 h-3.5 w-3.5" /> Add route
          </Button>
          <label className="text-xs text-muted-foreground">
            Judgment deadline (seconds, across all routes)
            <input
              className={`${inputClass} ml-2 w-16`}
              type="number"
              value={timeout}
              onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
            />
          </label>
        </div>
      </CardContent>
    </Card>
  );
}

/** The scored weights behind one verdict — the audit surface that replaced the message text. */
function scoreSummary(e: VerdictEvent): string {
  const parts: string[] = [];
  if (e.value) parts.push(`v ${e.value}`);
  if (e.emoji) parts.push(e.emoji);
  const weights: Array<[string, string]> = [
    ["fit", e.fit], ["msgfit", e.msgfit], ["openq", e.openq],
    ["addressed", e.addressed], ["emojiconf", e.emojiconf], ["wait", e.wait],
  ];
  for (const [label, value] of weights) {
    if (value) parts.push(`${label} ${value}`);
  }
  return parts.join(" · ");
}

function VerdictFeed({ events }: { events: VerdictEvent[] }) {
  if (!events.length) {
    return <p className="py-2 text-sm text-muted-foreground">No verdict events yet.</p>;
  }
  return (
    <div className="max-h-80 overflow-auto rounded-xl border border-border" role="region" aria-label="Recent wake decisions" tabIndex={0}>
      <table className="w-full min-w-[700px] text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1 pr-2">at</th>
            <th className="pr-2">event</th>
            <th className="pr-2">route</th>
            <th className="pr-2">weights</th>
            <th className="pr-2">who</th>
            <th>reason</th>
          </tr>
        </thead>
        <tbody>
          {events
            .slice()
            .reverse()
            .map((e, i) => (
              <tr key={`${e.at}-${i}`} className="border-t">
                <td className="py-1 pr-2 font-mono text-xs">{e.at}</td>
                <td className="pr-2">
                  <Badge tone={e.kind === "jev_error" ? "destructive" : "secondary"}>
                    {e.kind === "verdict" ? e.action || e.kind : e.kind}
                  </Badge>
                </td>
                <td className="pr-2">{e.route}</td>
                <td className="pr-2 font-mono text-xs">{scoreSummary(e)}</td>
                <td className="max-w-40 truncate pr-2 font-mono text-xs">{e.who}</td>
                <td className="max-w-72 truncate text-muted-foreground">{e.reason}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

export default function BehaviourPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [thresholds, setThresholds] = useState<ThresholdsResponse | null>(null);
  const [behaviour, setBehaviour] = useState<BehaviourBundle | null>(null);
  const [events, setEvents] = useState<VerdictEvent[]>([]);
  const [wakes, setWakes] = useState<Array<Record<string, unknown>>>([]);
  const [cost, setCost] = useState<{ calls: number; total_usd: number; unknown_cost_calls?: number; by_route: Array<{ route: string; calls: number; usd: number }> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [policyKey, setPolicyKey] = useState(0);
  const [replaying, setReplaying] = useState(false);
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  const load = useCallback(async () => {
    try {
      const [h, t, v, w, c, b] = await Promise.all([
        lunaApi.getHealth(),
        lunaApi.getThresholds(),
        lunaApi.getVerdicts(40),
        lunaApi.getWakes(20),
        lunaApi.getCost(0),
        lunaApi.getBehaviour(),
      ]);
      setHealth(h);
      setThresholds(t);
      setEvents(v.events);
      setWakes(w.wakes as unknown as Array<Record<string, unknown>>);
      setCost(c);
      setBehaviour(b);
    } catch (e) {
      showToast(`Could not load wake behaviour: ${errorMessage(e)}`, "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  // Keep the verdict feed current while the page is open (poll, like the analytics
  // surfaces — EventSource cannot carry the session-token header).
  useEffect(() => {
    const timer = window.setInterval(() => {
      lunaApi
        .getVerdicts(40)
        .then((res) => setEvents(res.events))
        .catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    setEnd(
      <Button outlined size="sm" onClick={load}>
        <RefreshCw className="mr-1 h-3.5 w-3.5" /> Refresh
      </Button>,
    );
    return () => setEnd(null);
  }, [load, setEnd]);

  const groups = useMemo(
    () => (thresholds ? groupThresholdKeys(thresholds.keys) : []),
    [thresholds],
  );

  const writeThreshold = async (key: string, value: number | null) => {
    setSavingKey(key);
    try {
      const res = await lunaApi.setThresholds({ [key]: value });
      const result = res.results[key];
      if (result && !result.ok) {
        showToast(result.error ?? `Could not save ${thresholdLabel(key)}`, "error");
      } else {
        setThresholds(res.state);
      }
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setSavingKey(null);
    }
  };

  /**
   * Writes the whole policy. Returns whether every key landed.
   *
   * Two things it must not do, both of which it did:
   *  - report success on a partial write. `put_behaviour` raises only when *every* key fails, so a
   *    200 can carry rejected keys (a `jev.route` naming an unknown provider, say). Reporting
   *    success there left the rejected group's edits gone from a reloaded card, behind a green toast.
   *  - remount the card on a partial failure. `setBehaviour` + `policyKey` reload the form from
   *    disk, which is right after a clean write and wrong here: it discards the rejected edits with no
   *    way back. Leaving the card mounted keeps them visible and retryable.
   */
  const savePolicy = async (updates: Record<string, unknown>): Promise<boolean> => {
    setSavingPolicy(true);
    try {
      const res = await lunaApi.saveBehaviour(updates, behaviour?.revision);
      const failed = Object.entries(res.results ?? {}).filter(([, v]) => !v.ok);
      if (failed.length > 0) {
        showToast(
          `Wake policy partly saved — rejected: ${failed
            .map(([key, v]) => `${key}${v.error ? ` (${v.error})` : ""}`)
            .join(", ")}`,
          "error",
        );
        return false;
      }
      setBehaviour(res.behaviour);
      setPolicyKey((k) => k + 1);
      showToast("Wake policy saved", "success");
      return true;
    } catch (e) {
      showToast(errorMessage(e), "error");
      return false;
    } finally {
      setSavingPolicy(false);
    }
  };

  const runReplay = async () => {
    setReplaying(true);
    try {
      const res = await lunaApi.replay(25, 10);
      showToast(res.ok ? res.output ?? "Offline replay finished (no model calls)" : `Replay failed: ${res.error ?? res.errors ?? ""}`, res.ok ? "success" : "error");
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setReplaying(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-6">
        <Spinner /> Loading wake behaviour…
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <header className="relative overflow-hidden rounded-3xl border border-border/70 bg-card px-6 py-8 md:px-8 md:py-10">
        <BlossomBranch className="pointer-events-none absolute right-0 top-0 hidden w-80 opacity-40 lg:block" />
        <div className="relative max-w-3xl">
          <H2 className="max-w-xl text-3xl font-normal lg:text-4xl">Make space for the right moment.</H2>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">Tune when your companion joins a group conversation, how they handle reactions, and which decisions stay quiet. Silence remains the default.</p>
        </div>
      </header>

      {health && <HealthStrip health={health} />}

      {behaviour && (
        <WakePolicyCard
          key={policyKey}
          behaviour={behaviour}
          saving={savingPolicy}
          onSave={savePolicy}
        />
      )}

      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-2">
            <H2 className="text-base">Cost</H2>
            {cost && (
              <span className="min-w-0 flex-1 text-sm leading-relaxed text-muted-foreground">
                {cost.calls} metered calls · ${cost.total_usd.toFixed(6)}
                {cost.unknown_cost_calls ? ` · ${cost.unknown_cost_calls} calls with unknown price` : ""}
                {cost.by_route.slice(0, 3).map((r) => ` · ${r.route}: $${r.usd.toFixed(6)}`)}
              </span>
            )}
            <Button outlined size="sm" className="self-start sm:ml-auto" onClick={runReplay} disabled={replaying}>
              <Play className="mr-1 h-3.5 w-3.5" />
              {replaying ? "Replaying…" : "What-if replay"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Replay recomposes stored Jev scores using current thresholds. No history leaves this device and no model calls are made. Timing and delivery are not simulated.
          </p>
        </CardContent>
      </Card>

      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <H2 className="text-base">Thresholds</H2>
          <p className="text-xs text-muted-foreground">
            Changes take effect on the next poll. Reset restores a setting’s default. Lower
            thresholds can make your companion speak more often, so adjust them gradually.
          </p>
          {thresholds &&
            groups.map((group) => (
              <div key={group.name} className="mt-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {group.name}
                </div>
                {group.keys.map((key) => (
                  <ThresholdRow
                    key={key}
                    name={key}
                    entry={thresholds.values[key]}
                    saving={savingKey === key}
                    onCommit={(value) => writeThreshold(key, value)}
                    onReset={() => writeThreshold(key, null)}
                  />
                ))}
              </div>
            ))}
        </CardContent>
      </Card>

      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <H2 className="text-base">Verdict feed</H2>
          <p className="text-xs text-muted-foreground">
            Recent decisions from the wake system. Message text is never shown here.
          </p>
          <VerdictFeed events={events} />
        </CardContent>
      </Card>

      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <H2 className="text-base">Wake ledger</H2>
          {!wakes.length ? (
            <p className="py-2 text-sm text-muted-foreground">No wakes recorded yet.</p>
          ) : (
            <div className="mt-3 overflow-x-auto rounded-xl border border-border" role="region" aria-label="Wake ledger, horizontally scrollable" tabIndex={0}>
              <table className="w-full min-w-[680px] text-sm">
              <thead>
                <tr className="bg-muted/50 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2">Time</th>
                  <th className="pr-2">Kind</th>
                  <th className="pr-2">Trigger</th>
                  <th className="pr-2">Value</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {wakes.map((row, i) => (
                  <tr key={i} className="border-t border-border/70 hover:bg-muted/30">
                    <td className="px-3 py-2 pr-2 font-mono text-xs">{String(row.created_at)}</td>
                    <td className="pr-2">
                      {String(row.emoji ?? "")} {String(row.kind)}
                    </td>
                    <td className="pr-2">{String(row.trigger_message_id ?? "-")}</td>
                    <td className="pr-2">{row.value == null ? "-" : String(row.value)}</td>
                    <td className="max-w-96 truncate text-muted-foreground">{String(row.reason ?? "")}</td>
                  </tr>
                ))}
              </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Toast toast={toast} />
    </div>
  );
}
