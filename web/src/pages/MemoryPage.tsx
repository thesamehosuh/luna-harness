import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { NoteFilesEditor } from "@/components/NoteFilesEditor";
import { AutoField } from "@/components/AutoField";
import { MemoryReasoningSelector } from "@/components/MemoryReasoningSelector";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { H2 } from "@/components/ui/h2";
import { api, fetchJSON } from "@/lib/api";
import { errorMessage } from "@/lib/api-error";
import { useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import { Switch } from "@nous-research/ui/ui/components/switch";

type Field = { key: string; label: string; schema: Record<string, unknown>; value: unknown };
type Report = {
  fields: Field[];
  status: { enabled: boolean; host: string; workspace: string; ai_peer: string; user_peer: string | null; base_url: string; auth_configured: boolean; session_strategy: string };
  verification: { ok: boolean; stale?: boolean; at: string; checks: Record<string, boolean> } | null;
};
type ServiceProgress = { stage: string; detail?: string };
const PRIMARY = new Set(["dialecticCadence", "dialecticReasoningLevel", "dialecticDepth", "contextTokens", "contextCadence", "recallMode", "writeFrequency", "observationMode"]);
const FILE_CONTROLS = [
  ["memory_enabled", "Enable MEMORY.md notes"], ["user_profile_enabled", "Enable USER.md and people maintenance"],
  ["memory_char_limit", "Note limit per private or group MEMORY.md"], ["user_char_limit", "Private USER.md character limit"],
  ["nudge_interval", "Review saved files every N conversation turns (0 disables)"], ["write_approval", "Require approval for MEMORY.md and USER.md updates"],
] as const;

export default function MemoryPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "settings" ? "settings" : "files";
  const [report, setReport] = useState<Report | null>(null);
  const [service, setService] = useState<ServiceProgress | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [memory, setMemory] = useState<Record<string, unknown>>({});
  const [memoryDraft, setMemoryDraft] = useState<Record<string, unknown>>({});
  const [schemas, setSchemas] = useState<Record<string, unknown>>({});
  const [reviewEnabled, setReviewEnabled] = useState(true);
  const [reviewDraft, setReviewDraft] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const load = useCallback(async () => {
    const [settings, progress, config, schema] = await Promise.all([
      fetchJSON<Report>("/api/luna/memory/settings"),
      fetchJSON<ServiceProgress>("/api/luna/onboarding/memory/progress"),
      api.getConfig(), api.getSchema(),
    ]);
    setReport(settings); setService(progress);
    setMemory((config.memory || {}) as Record<string, unknown>);
    setSchemas(schema.fields);
    const auxiliary = config.auxiliary as { background_review?: { enabled?: boolean } } | undefined;
    setReviewEnabled(auxiliary?.background_review?.enabled !== false);
  }, []);
  useEffect(() => { void load().catch(e => setError(errorMessage(e))); }, [load]);
  const save = async () => {
    setBusy(true); setError(""); setSaved(false);
    try {
      await api.saveConfig({ honcho: draft, memory: memoryDraft,
        ...(reviewDraft === null ? {} : { auxiliary: { background_review: { enabled: reviewDraft } } }) });
      await load(); setDraft({}); setMemoryDraft({}); setReviewDraft(null); setSaved(true); return true;
    }
    catch (e) { setError(errorMessage(e)); return false; }
    finally { setBusy(false); }
  };
  const setMemoryService = async (enabled: boolean) => {
    setBusy(true); setError(""); setSaved(false);
    try {
      const result = await fetchJSON<{ ok: boolean; detail?: string }>("/api/luna/memory/service", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, timeout: 180 }),
      });
      if (!result.ok) throw new Error(result.detail || "Honcho could not be updated.");
      await load();
    } catch (e) { setError(errorMessage(e)); await load().catch(() => undefined); }
    finally { setBusy(false); }
  };
  const dirty = Object.keys(draft).length > 0 || Object.keys(memoryDraft).length > 0 || reviewDraft !== null;
  useUnsavedChanges({ id: "honcho-tuning", label: "memory settings", dirty, onSave: save,
    onDiscard: () => { setDraft({}); setMemoryDraft({}); setReviewDraft(null); } });
  const renderField = (field: Field) => <AutoField key={field.key} schemaKey={field.label} schema={field.schema}
    value={Object.hasOwn(draft, field.key) ? draft[field.key] : field.value}
    onChange={value => { setDraft(current => ({ ...current, [field.key]: value })); setSaved(false); }} />;
  return <div className="space-y-4 p-4">
    <div className="flex items-center gap-3"><H2>Memory</H2><Link to="/onboarding#step-honcho" className="text-sm underline">Setup and repair</Link></div>
    <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm"><Link to="/groups" className="text-primary underline">Group notes and people</Link><Link to="/people" className="text-primary underline">Shared people directory</Link></div>
    <div role="tablist" aria-label="Memory views" className="flex gap-1 border-b border-border">
      {([['files', 'Files'], ['settings', 'Settings']] as const).map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} aria-controls={`memory-${id}`} id={`memory-tab-${id}`}
        className={`border-b-2 px-4 py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${tab === id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
        onClick={() => setParams(current => { const next = new URLSearchParams(current); id === 'settings' ? next.set('tab', id) : next.delete('tab'); return next; })}>{label}</button>)}
    </div>
    {tab === "files" ? <div id="memory-files" role="tabpanel" aria-labelledby="memory-tab-files"><NoteFilesEditor /></div> : <div id="memory-settings" role="tabpanel" aria-labelledby="memory-tab-settings" className="space-y-4">
    <p className="max-w-2xl text-sm text-muted-foreground">Control the companion's saved files and Honcho recall. Group notes use the same file-memory controls as private notes.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {report && <>
      <Card><CardContent className="space-y-4 py-4">
        <H2 className="text-base">Saved files and automatic maintenance</H2>
        <p className="text-xs text-muted-foreground">Each group/topic has its own MEMORY.md alongside scoped PEOPLE.md entries. The companion can update these during conversation and periodic reviews. Your owner DM can look up a group’s notes and people when needed; group contents are not loaded automatically.</p>
        <div className="grid max-w-4xl gap-4 sm:grid-cols-2">{FILE_CONTROLS.map(([key, label]) =>
          <AutoField key={key} schemaKey={`memory.${key}`} label={label} schema={(schemas[`memory.${key}`] || { type: key.endsWith("enabled") || key === "write_approval" ? "boolean" : "number" }) as Record<string, unknown>}
            value={Object.hasOwn(memoryDraft, key) ? memoryDraft[key] : memory[key]}
            onChange={value => { setMemoryDraft(current => ({ ...current, [key]: value })); setSaved(false); }} />)}
        </div>
        <div className="flex items-center justify-between gap-4"><p className="text-sm">Automatic background reviews</p>
          <Switch checked={reviewDraft ?? reviewEnabled} disabled={busy} onCheckedChange={checked => { setReviewDraft(checked === true); setSaved(false); }} aria-label="Enable automatic background memory reviews" />
        </div>
        <p className="text-xs text-muted-foreground">Reviews use the existing background-review model settings. Turning file-write approval off also permits consolidation of older entries. Basic people-entry updates do not need approval. A group request to read private USER.md or MEMORY.md always needs a separate one-read approval in your DM, showing the exact excerpt and destination group.</p>
      </CardContent></Card>
      <Card><CardContent className="space-y-3 py-4">
        <div className="flex items-center justify-between gap-4"><div><H2 className="text-base">Honcho recall</H2><p className="mt-1 max-w-xl text-xs text-muted-foreground">Conversation recall runs independently of the saved files above. Turning Honcho off keeps those files and their maintenance settings.</p>
          <p className="text-sm">{report.status.enabled ? (service?.stage === "degraded" ? "On · needs attention" : service?.stage === "disabled" ? "On · service stopped" : "On") : "Off"}
            {report.status.enabled ? ` · ${report.verification?.ok ? "Data path verified" : "Data path not verified"}` : ""}</p>
        </div><Switch checked={report.status.enabled} disabled={busy} onCheckedChange={checked => void setMemoryService(checked === true)} aria-label="Enable Honcho memory" /></div>
        {busy && <p role="status" className="text-xs text-muted-foreground">Updating Honcho…</p>}
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          {Object.entries({ Workspace: report.status.workspace, "AI peer": report.status.ai_peer,
            "Owner peer": report.status.user_peer || "Derived from transport identity", "Session strategy": report.status.session_strategy,
            "Honcho endpoint": report.status.base_url, Authentication: report.status.auth_configured ? "Configured" : "Local stack" }).map(([label, value]) =>
            <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="break-all">{value}</dd></div>)}
        </dl>
        <Button outlined size="sm" disabled={busy || !report.status.enabled} onClick={async () => {
          setBusy(true); setError("");
          try { await fetchJSON("/api/luna/data/verify-memory", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await load(); }
          catch (e) { setError(errorMessage(e)); }
          finally { setBusy(false); }
        }}>{busy ? "Working…" : "Check memory connection"}</Button>
        {report.verification && <p className="text-xs text-muted-foreground">Last check: {new Date(report.verification.at).toLocaleString()}{report.verification.stale ? " (settings have changed)" : ""}</p>}
      </CardContent></Card>
      <Card><CardContent className="space-y-3 py-4"><H2 className="text-base">Reasoning model</H2><MemoryReasoningSelector /></CardContent></Card>
      <Card><CardContent className="space-y-4 py-4">
        <H2 className="text-base">DM dialectic and recall tuning</H2>
        <p className="text-xs text-muted-foreground">Dialectic every 4 turns means one reasoning cycle after four conversation turns. It shares the selected model’s quota. These dialectic controls tune the private DM backend. Groups use indexed public conclusions and summaries; recall mode, context cadence and injection frequency also control their automatic recall. In tools-only mode, your companion can request public group recall explicitly.</p>
        <div className="grid max-w-4xl gap-4 sm:grid-cols-2">{report.fields.filter(field => PRIMARY.has(field.key)).map(renderField)}</div>
        <details className="space-y-3"><summary className="cursor-pointer text-sm">Advanced memory controls</summary>
          <div className="grid max-w-4xl gap-4 pt-3 sm:grid-cols-2">{report.fields.filter(field => !PRIMARY.has(field.key)).map(renderField)}</div>
        </details>
        <div className="flex items-center gap-3"><Button size="sm" disabled={busy || !dirty} onClick={() => void save()}>Save memory settings</Button>
          {saved && <p role="status" className="text-sm">Saved. New conversations use these settings.</p>}</div>
      </CardContent></Card>
    </>}
    {!report && !error && <p role="status">Loading memory settings…</p>}
    </div>}
  </div>;
}
