import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Play, RotateCw, Square } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { api, type StatusResponse } from "@/lib/api";
import { errorMessage } from "@/lib/api-error";
import { runGatewayAction, type GatewayAction } from "@/lib/gateway-lifecycle";
import { sharedGatewayProfiles } from "@/lib/shared-gateway";

export function GatewayControls() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [busy, setBusy] = useState<GatewayAction | null>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    let active = true;
    const load = () => api.getStatus().then(value => { if (active) { setStatus(value); setLoadError(""); } }).catch(reason => { if (active) setLoadError(errorMessage(reason)); });
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  const run = async (action: GatewayAction) => {
    setBusy(action); setError("");
    try { setStatus(await runGatewayAction(action)); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(null); }
  };
  const shared = sharedGatewayProfiles(status);
  const running = status?.gateway_running === true;
  const connected = Object.values(status?.gateway_platforms || {}).filter(platform => platform.state === "connected").length;
  return <section aria-label="Gateway controls" className="rounded-panel border border-border bg-card px-5 py-4">
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div><h2 className="flex items-center gap-2 text-sm font-medium"><span className={`size-2 rounded-full ${running ? "bg-success" : "bg-muted-foreground"}`} />Gateway <span className="font-normal text-muted-foreground">{status ? running ? "Running" : "Stopped" : "Checking…"}</span></h2>
        <p className="mt-1 text-xs text-muted-foreground">{running ? status?.gateway_platforms?.telegram?.state === "connected" ? "Telegram connected" : connected ? `${connected} chat connections active` : "No chat apps connected yet" : "Start to receive messages from your chat apps"}</p>
      </div>
      <div className="flex items-center gap-2">
        <Link to="/system" className="mr-2 text-xs text-muted-foreground hover:text-foreground">Details</Link>
        {running ? <><Button outlined size="sm" disabled={busy !== null} prefix={<Square />} onClick={() => void run("stop")}>{busy === "stop" ? "Stopping…" : "Stop"}</Button><Button size="sm" disabled={busy !== null} prefix={<RotateCw className={busy === "restart" ? "animate-spin" : ""} />} onClick={() => shared ? setConfirm(true) : void run("restart")}>{busy === "restart" ? "Restarting…" : "Restart"}</Button></>
          : <Button size="sm" disabled={busy !== null || !status} prefix={<Play />} onClick={() => void run("start")}>{busy === "start" ? "Starting…" : "Start gateway"}</Button>}
      </div>
    </div>
    {(error || loadError) && <p role="alert" className="mt-3 text-sm text-destructive">{error || loadError}</p>}
    <ConfirmDialog open={confirm} title="Restart shared gateway?" description={`This reconnects ${shared?.length || 0} bots on this device.`} confirmLabel="Restart" onCancel={() => setConfirm(false)} onConfirm={() => { setConfirm(false); void run("restart"); }} />
  </section>;
}
