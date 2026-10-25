import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api-error";
import { opencodeApi, type OpenCodeStatus, type FreeModel, type ModelProbe } from "@/lib/luna-opencode";

export default function OpenCodeSetup({ onSaved }: { onSaved?: () => void | Promise<unknown> }) {
  const [status, setStatus] = useState<OpenCodeStatus | null>(null);
  const [models, setModels] = useState<FreeModel[]>([]);
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState<string | null>("loading");
  const [error, setError] = useState("");
  const [probe, setProbe] = useState<ModelProbe | null>(null);
  const [saved, setSaved] = useState(false);

  const loadModels = async () => {
    const catalog = await opencodeApi.models();
    setStatus(catalog);
    setModels(catalog.models);
    setModel((current) => catalog.models.some((entry) => entry.id === current) ? current :
      catalog.models.some((entry) => entry.id === catalog.selected) ? catalog.selected : catalog.models[0]?.id || "");
  };

  useEffect(() => {
    let cancelled = false;
    opencodeApi.status().then(async (result) => {
      if (cancelled) return;
      setStatus(result);
      if (result.installed) {
        const catalog = await opencodeApi.models();
        if (cancelled) return;
        setModels(catalog.models);
        setModel(catalog.models.some((entry) => entry.id === result.selected) ? result.selected : catalog.models[0]?.id || "");
      }
    }).catch((reason) => { if (!cancelled) setError(errorMessage(reason)); })
      .finally(() => { if (!cancelled) setBusy(null); });
    return () => { cancelled = true; };
  }, []);

  const act = async (action: string, callback: () => Promise<void>) => {
    setBusy(action);
    setError("");
    setSaved(false);
    try { await callback(); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(null); }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Use OpenCode’s free models for your companion’s replies. No API key is needed. OpenCode sets availability and usage limits.
      </p>
      {!status?.installed && (
        <Button size="sm" disabled={busy !== null} onClick={() => act("install", async () => {
          setStatus(await opencodeApi.install());
          await loadModels();
        })}>
          {busy === "install" ? "Installing OpenCode…" : busy === "loading" ? "Checking OpenCode…" : "Install OpenCode"}
        </Button>
      )}
      {status?.installed && (
        <>
          <label className="flex max-w-xl flex-col gap-1 text-sm">
            <span>Free model</span>
            <select aria-label="Free model" className="rounded border bg-transparent px-2 py-1" value={model}
              disabled={busy !== null || models.length === 0}
              onChange={(event) => { setModel(event.target.value); setProbe(null); setSaved(false); }}>
              {models.length === 0 && <option value="">{busy ? "Loading models…" : "No free models available"}</option>}
              {models.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
            </select>
          </label>
          <div className="flex flex-wrap gap-2">
            <Button outlined size="sm" disabled={busy !== null} onClick={() => act("refresh", loadModels)}>Refresh models</Button>
            <Button outlined size="sm" disabled={busy !== null || !model} onClick={() => act("probe", async () => {
              setProbe(await opencodeApi.probe(model));
            })}>{busy === "probe" ? "Testing model…" : "Test model"}</Button>
            <Button size="sm" disabled={busy !== null || !model} onClick={() => act("save", async () => {
              await opencodeApi.select(model);
              setStatus({ ...status, selected: model });
              setSaved(true);
              // Verify the saved connection, so a pre-selection probe cannot leave
              // setup with a proof bound to the previous configuration.
              setProbe(await opencodeApi.probe(model));
              await onSaved?.();
            })}>Use this model</Button>
          </div>
          {saved && <p role="status" className="text-sm">Model saved. New conversations use {models.find((entry) => entry.id === model)?.name || model}.</p>}
          {probe && <p role="status" className={`text-sm ${probe.ok ? "text-success" : "text-muted-foreground"}`}>
            {probe.ok ? `Model replied: ${probe.detail}` : probe.detail}
          </p>}
        </>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <p className="text-xs text-muted-foreground">Memory can share this model. Its embeddings run locally; wake checks are optional.</p>
    </div>
  );
}
