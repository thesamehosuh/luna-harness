import { useCallback, useEffect, useState } from "react";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { api, fetchJSON } from "@/lib/api";
import { errorMessage } from "@/lib/api-error";

type Route = { configured: boolean; source: string; provider?: string; model?: string; reasoning_effort?: string; detail?: string };

export function MemoryReasoningSelector({ compact = false }: { compact?: boolean }) {
  const [route, setRoute] = useState<Route | null>(null);
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => setRoute(await fetchJSON<Route>("/api/luna/onboarding/memory/reasoning")), []);
  useEffect(() => { void load().catch(e => setError(errorMessage(e))); }, [load]);
  const selectCompanion = async () => {
    setBusy(true); setError("");
    try { await api.saveConfig({ luna: { memory_stack: { reasoning_source: "companion" } } }); await load(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  return <div className="space-y-5">
    <div className="onboarding-setting-row">
      <div className="min-w-0">
        <span className="text-sm font-medium">Memory model</span>
        <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Memory model source">
          <Button outlined={route?.source === "custom"} size="sm" aria-pressed={route?.source !== "custom"} disabled={busy || !route} onClick={() => void selectCompanion()}>Companion’s model</Button>
          <Button outlined size="sm" aria-pressed={route?.source === "custom"} disabled={busy} onClick={() => setPicker(true)}>Choose another</Button>
        </div>
        {route?.configured && <p className="mt-2 truncate text-xs text-muted-foreground" aria-live="polite">{route.model?.split("/").at(-1)}</p>}
      </div>
    </div>
    <div className="onboarding-setting-row">
      <label htmlFor="memory-reasoning-effort" className="text-sm font-medium">Reasoning effort</label>
      <Select id="memory-reasoning-effort" label="Memory reasoning effort" className="sm:max-w-56" value={route?.reasoning_effort || "default"}
        disabled={busy || !route?.configured} onValueChange={async effort => {
          setBusy(true); setError("");
          try { await api.saveConfig({ luna: { memory_stack: { reasoning_effort: effort } } }); await load(); }
          catch (e) { setError(errorMessage(e)); }
          finally { setBusy(false); }
        }} options={["default", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"].map(effort => ({
          value: effort, label: effort === "default" ? "Provider default" : effort[0].toUpperCase() + effort.slice(1),
          disabled: route?.provider === "opencode-engine" && effort !== "default",
        }))} />
    </div>
    <details><summary className="onboarding-disclosure">Connection options</summary><div className="space-y-3 pt-4">
      <p className="text-xs text-muted-foreground">Memory effort is independent of chat. {route?.provider === "opencode-engine" ? "OpenCode supports provider default only." : "Available levels depend on your model."}</p>
      {route && !route.configured && <p className="text-xs text-muted-foreground">{route.detail}</p>}
      <OAuthProvidersCard guided compact={compact} onError={setError} onSuccess={() => { void load().catch(e => setError(errorMessage(e))); }} />
      {!compact && <p className="text-xs text-muted-foreground">Uses the selected account’s limits and pricing. Embeddings run locally.</p>}
    </div></details>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {picker && <ModelPickerDialog loader={api.getModelOptions} alwaysGlobal title="Choose memory reasoning model"
      onClose={() => setPicker(false)} onApply={async ({ provider, model }) => {
        await api.saveConfig({ luna: { memory_stack: { reasoning_source: "custom", provider, model, base_url: "", api_key_env: "" } } });
        await load(); setPicker(false);
      }} />}
  </div>;
}
