import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
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

export default function MemoryPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [service, setService] = useState<ServiceProgress | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const load = useCallback(async () => {
    const [settings, progress] = await Promise.all([
      fetchJSON<Report>("/api/luna/memory/settings"),
      fetchJSON<ServiceProgress>("/api/luna/onboarding/memory/progress"),
    ]);
    setReport(settings); setService(progress);
  }, []);
  useEffect(() => { void load().catch(e => setError(errorMessage(e))); }, [load]);
  const save = async () => {
    setBusy(true); setError(""); setSaved(false);
    try { await api.saveConfig({ honcho: draft }); await load(); setDraft({}); setSaved(true); return true; }
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
  useUnsavedChanges({ id: "honcho-tuning", label: "memory settings", dirty: Object.keys(draft).length > 0, onSave: save, onDiscard: () => setDraft({}) });
  const renderField = (field: Field) => <AutoField key={field.key} schemaKey={field.label} schema={field.schema}
    value={Object.hasOwn(draft, field.key) ? draft[field.key] : field.value}
    onChange={value => { setDraft(current => ({ ...current, [field.key]: value })); setSaved(false); }} />;
  return <div className="space-y-4 p-4">
    <div className="flex items-center gap-3"><H2>Memory</H2><Link to="/onboarding#step-honcho" className="text-sm underline">Setup and repair</Link></div>
    <p className="max-w-2xl text-sm text-muted-foreground">Choose how often Honcho reasons about conversations and how much context your companion recalls. These are the effective settings used by the memory client.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {report && <>
      <Card><CardContent className="space-y-3 py-4">
        <div className="flex items-center justify-between gap-4"><div><H2 className="text-base">Honcho</H2>
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
        <H2 className="text-base">Dialectic and recall</H2>
        <p className="text-xs text-muted-foreground">Dialectic every 4 turns means one reasoning cycle after four conversation turns. It shares the selected model’s quota. Group recall remains restricted to facts from that room.</p>
        <div className="grid max-w-4xl gap-4 sm:grid-cols-2">{report.fields.filter(field => PRIMARY.has(field.key)).map(renderField)}</div>
        <details className="space-y-3"><summary className="cursor-pointer text-sm">Advanced memory controls</summary>
          <div className="grid max-w-4xl gap-4 pt-3 sm:grid-cols-2">{report.fields.filter(field => !PRIMARY.has(field.key)).map(renderField)}</div>
        </details>
        <div className="flex items-center gap-3"><Button size="sm" disabled={busy || Object.keys(draft).length === 0} onClick={() => void save()}>Save memory settings</Button>
          {saved && <p role="status" className="text-sm">Saved. New conversations use these settings.</p>}</div>
      </CardContent></Card>
    </>}
    {!report && !error && <p role="status">Loading memory settings…</p>}
  </div>;
}
