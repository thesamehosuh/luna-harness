import { useCallback, useEffect, useState } from "react";
import { authedFetch, fetchJSON } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { errorMessage } from "@/lib/api-error";

type Check = { ok: boolean; at: string; detail: string; checks?: Record<string, unknown> } | null;
type DataStatus = {
  product?: { version: string; engine?: { version: string } };
  inventory: { store: string; path: string; retention: string; backup: string }[];
  retention: { checked_at?: string; last_success_at?: string };
  delivery: { pending: number; uncertain: number; failed: number; oldest_pending_at: string | null };
  memory_check: Check; chat_check: Check;
  native: { at: string; compacted: boolean; input_tokens: number } | null;
  backups: string[]; release: string | null; rollback_available: boolean;
};

export function LunaDataPanel() {
  const [data, setData] = useState<DataStatus | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try { setData(await fetchJSON<DataStatus>("/api/luna/data")); }
    catch (e) { setError(errorMessage(e)); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const action = async (path: string, body: object = {}) => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await fetchJSON<{ ok?: boolean; detail?: string; restart_required?: boolean }>(`/api/luna/data/${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      setNotice(result.detail ?? (result.restart_required ? "Completed. Restart the dashboard and gateway when ready." : "Completed"));
      await refresh();
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const download = async (name: string) => {
    try {
      const response = await authedFetch(`/api/luna/data/backups/${encodeURIComponent(name)}`);
      if (!response.ok) throw new Error("Backup download failed");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = name; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(errorMessage(e)); }
  };
  if (!data) return <p role={error ? "alert" : "status"}>{error || "Checking companion data…"}</p>;
  return <Card><CardContent className="space-y-4 py-5">
    <h2 className="text-lg font-semibold">Companion data & recovery</h2>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <p className="text-sm">Memory delivery: {data.delivery.pending} pending, {data.delivery.uncertain} awaiting reconciliation, {data.delivery.failed} retried or failed.
      {data.delivery.oldest_pending_at && ` Oldest: ${data.delivery.oldest_pending_at}`}</p>
    <p className="text-sm">Retention last succeeded: {data.retention.last_success_at ?? "Not verified"}.</p>
    <p className="text-sm">Memory pipeline: {data.memory_check?.ok ? "Verified" : "Not verified or degraded"}{data.memory_check && ` · ${data.memory_check.at} · ${data.memory_check.detail}`}.</p>
    {data.memory_check?.checks && <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Memory verification checks">
      {Object.entries(data.memory_check.checks).filter(([, value]) => typeof value === "boolean").map(([name, ok]) => <li key={name}>{name.replaceAll("_", " ")}: {ok ? "Passed" : "Failed"}</li>)}
    </ul>}
    {data.native && <p className="text-sm">Native context: {data.native.input_tokens} input tokens; compaction {data.native.compacted ? "occurred" : "not reported"} · {data.native.at}.</p>}
    <p className="text-sm">Chat model: {data.chat_check?.ok ? "Verified" : "Not verified or degraded"}{data.chat_check && ` · ${data.chat_check.at}`}.</p>
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={busy} onClick={() => void action("verify-chat")}>Verify chat model</Button>
      <Button size="sm" disabled={busy} onClick={() => void action("verify-memory")}>Verify memory pipeline</Button>
      {data.delivery.uncertain > 0 && <Button size="sm" disabled={busy} onClick={() => { if (window.confirm("Retry held deliveries after reconciling the remote store? A provider that accepted a write but cannot yet list it can still produce a duplicate.")) void action("retry-delivery"); }}>Retry held deliveries</Button>}
      <Button size="sm" disabled={busy} onClick={() => void action("retention")}>Run retention</Button>
      <Button size="sm" disabled={busy} onClick={() => void action("backup")}>Create companion backup</Button>
      <Button size="sm" disabled={busy} onClick={() => void refresh()}>Refresh</Button>
    </div>
    <p className="text-xs text-muted-foreground">Backups contain private history and credentials. Managed memory must be available for a complete backup. Restore requires this profile’s gateway to be stopped and creates a safety backup first.</p>
    {data.backups.map(name => <div key={name} className="flex flex-wrap items-center gap-3 text-sm"><span>{name}</span>
      <Button size="sm" ghost disabled={busy} onClick={() => void download(name)}>Download</Button>
      <Button size="sm" ghost disabled={busy} onClick={() => { if (window.confirm("Restore this backup? Current state will be replaced after creating a safety backup.")) void action("restore", { name }); }}>Restore</Button>
    </div>)}
    <p className="text-sm">Luna {data.product?.version ?? "development"} · Engine {data.product?.engine?.version ?? "unknown"}. Release: {data.release ?? "Development checkout"}.</p>
    {data.rollback_available && <Button size="sm" disabled={busy} onClick={() => { if (window.confirm("Restore the previous installed code and environment? Stop the gateway first.")) void action("rollback"); }}>Restore previous release</Button>}
    <details><summary className="cursor-pointer text-sm">Data inventory and retention coverage</summary>
      <div className="overflow-x-auto"><table className="mt-3 w-full text-left text-xs"><thead><tr><th>Store</th><th>Retention</th><th>Backup</th></tr></thead>
      <tbody>{data.inventory.map(item => <tr key={item.store}><td className="p-2">{item.store}</td><td className="p-2">{item.retention}</td><td className="p-2">{item.backup}</td></tr>)}</tbody></table></div>
      <p className="mt-2 text-xs">Derived memory and identities persist separately from raw sources. Use People and Memory to inspect and edit them.</p>
    </details>
  </CardContent></Card>;
}
