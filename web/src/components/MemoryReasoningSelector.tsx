import { useCallback, useEffect, useState } from "react";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { Button } from "@/components/ui/Button";
import { api, fetchJSON } from "@/lib/api";
import { errorMessage } from "@/lib/api-error";

type Route = { configured: boolean; source: string; provider?: string; model?: string; detail?: string };

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
    <p className="text-xs text-muted-foreground">Memory reasoning shares the selected connection’s usage limits and cost. Embeddings run locally without a model account.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {picker && <ModelPickerDialog loader={api.getModelOptions} alwaysGlobal title="Choose memory reasoning model"
      onClose={() => setPicker(false)} onApply={async ({ provider, model }) => {
        await api.saveConfig({ luna: { memory_stack: { reasoning_source: "custom", provider, model, base_url: "", api_key_env: "" } } });
        await load(); setPicker(false);
      }} />}
  </div>;
}
