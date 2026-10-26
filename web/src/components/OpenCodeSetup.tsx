import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { errorMessage } from "@/lib/api-error";
import { opencodeApi, type OpenCodeStatus, type FreeModel, type ModelProbe } from "@/lib/luna-opencode";

export default function OpenCodeSetup({ onSaved, compact = false }: { onSaved?: () => void | Promise<unknown>; compact?: boolean }) {
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

  const saveSelected = () => act("save", async () => {
    await opencodeApi.select(model);
    setStatus(current => current ? { ...current, selected: model } : current);
    setSaved(true);
    // Bind verification to the saved connection, not a previous selection.
    setProbe(await opencodeApi.probe(model));
    await onSaved?.();
  });

  return (
    <div className="space-y-3">
      {!compact && <p className="text-sm text-muted-foreground">Free models through OpenCode. No API key needed.</p>}
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
          <div className="flex flex-wrap items-end gap-3">
          <div className="flex min-w-0 flex-1 basis-52 flex-col gap-1 text-sm">
            <label htmlFor="opencode-free-model">Free model</label>
            <Select id="opencode-free-model" label="Free model" value={model}
              disabled={busy !== null || models.length === 0}
              placeholder={busy ? "Loading models…" : "No free models available"}
              options={models.map(entry => ({ value: entry.id, label: entry.name }))}
              onValueChange={value => { setModel(value); setProbe(null); setSaved(false); }} />
          </div>
          <Button disabled={busy !== null || !model} onClick={saveSelected}>{busy === "save" ? "Testing…" : "Use this model"}</Button>
          </div>
          {!compact && <div className="flex flex-wrap gap-2">
            {!compact && <Button outlined size="sm" disabled={busy !== null} onClick={() => act("refresh", loadModels)}>Refresh models</Button>}
            {!compact && <Button outlined size="sm" disabled={busy !== null || !model} onClick={() => act("probe", async () => {
              setProbe(await opencodeApi.probe(model));
            })}>{busy === "probe" ? "Testing model…" : "Test model"}</Button>}
          </div>}
          {saved && <p role="status" className="text-sm">Model saved. New conversations use {models.find((entry) => entry.id === model)?.name || model}.</p>}
          {probe && <p role="status" className={`text-sm ${probe.ok ? "text-success" : "text-muted-foreground"}`}>
            {probe.ok ? `Model replied: ${probe.detail}` : probe.detail}
          </p>}
        </>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <p className="text-xs text-muted-foreground">Availability and usage limits are set by OpenCode.</p>
    </div>
  );
}
