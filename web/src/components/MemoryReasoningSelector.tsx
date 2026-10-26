import { useCallback, useEffect, useState } from "react";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
import { Button } from "@/components/ui/Button";
import { api, fetchJSON } from "@/lib/api";
import { errorMessage } from "@/lib/api-error";

type Route = { configured: boolean; source: string; provider?: string; model?: string; reasoning_effort?: string; detail?: string };

export function MemoryReasoningSelector() {
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
  return <div className="space-y-2">
    <label className="flex items-center gap-2 text-sm">
      <input type="radio" name="memory-reasoning" checked={route?.source !== "custom"} disabled={busy} onChange={() => void selectCompanion()} />
      Use my companion’s model (recommended)
    </label>
    <p className="text-xs text-muted-foreground" aria-live="polite">
      {route?.configured ? `${route.provider} · ${route.model}` : route?.detail || "Checking your model…"}
      {route?.source !== "custom" && " · Follows changes to your companion’s model."}
    </p>
    <Button outlined size="sm" disabled={busy} onClick={() => setPicker(true)}>Choose another model</Button>
    <label className="flex flex-col gap-1 text-sm">
      Honcho reasoning effort
      <select className="rounded border bg-background px-2 py-1" value={route?.reasoning_effort || "default"}
        disabled={busy || !route?.configured} onChange={async event => {
          const effort = event.target.value;
          setBusy(true); setError("");
          try { await api.saveConfig({ luna: { memory_stack: { reasoning_effort: effort } } }); await load(); }
          catch (e) { setError(errorMessage(e)); }
          finally { setBusy(false); }
        }}>
        {["default", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"].map(effort =>
          <option key={effort} value={effort} disabled={route?.provider === "opencode-engine" && effort !== "default"}>
            {effort === "default" ? "Provider default" : effort}
          </option>)}
      </select>
    </label>
    <p className="text-xs text-muted-foreground">Independent of your companion’s effort. Supported levels depend on the model; subscription connections map to supported levels.</p>
    {route?.provider === "opencode-engine" && <p className="text-xs text-muted-foreground">Native OpenCode currently exposes provider default only.</p>}
    <details><summary className="cursor-pointer text-sm">Connect another account</summary>
      <OAuthProvidersCard guided onError={setError} onSuccess={() => { void load().catch(e => setError(errorMessage(e))); }} />
    </details>
    <p className="text-xs text-muted-foreground">Memory reasoning shares the selected connection’s usage limits and cost. Embeddings run locally without a model account.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {picker && <ModelPickerDialog loader={api.getModelOptions} alwaysGlobal title="Choose memory reasoning model"
      onClose={() => setPicker(false)} onApply={async ({ provider, model }) => {
        await api.saveConfig({ luna: { memory_stack: { reasoning_source: "custom", provider, model, base_url: "", api_key_env: "" } } });
        await load(); setPicker(false);
      }} />}
  </div>;
}
