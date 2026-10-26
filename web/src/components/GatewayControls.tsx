import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Play, RotateCw, Server, Square } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { api, type StatusResponse, type GatewayServiceStatus } from "@/lib/api";
import { errorMessage } from "@/lib/api-error";
import { runGatewayAction, runGatewayServiceAction, type GatewayAction } from "@/lib/gateway-lifecycle";
import { sharedGatewayProfiles } from "@/lib/shared-gateway";

export function GatewayControls() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [busy, setBusy] = useState<GatewayAction | "install" | "uninstall" | null>(null);
  const [service, setService] = useState<GatewayServiceStatus | null>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    let active = true;
    const load = () => Promise.all([api.getStatus(), api.getGatewayService()]).then(([value, info]) => { if (active) { setStatus(value); setService(info); setLoadError(""); } }).catch(reason => { if (active) setLoadError(errorMessage(reason)); });
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
  const changeService = async (action: "install" | "uninstall") => {
    setBusy(action); setError("");
    try { const result = await runGatewayServiceAction(action); setService(result.service); setStatus(result.status); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(null); }
  };
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
    {service?.supported && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
      <div><p className="flex items-center gap-2 text-xs font-medium"><Server className="size-3.5" />Background service <span className="font-normal text-muted-foreground">{service.installed ? "Enabled" : "Off"}</span></p><p className="mt-1 text-xs text-muted-foreground">Keeps running after Luna closes. Starts at sign-in.</p></div>
      <Button outlined size="sm" disabled={busy !== null || !!shared || service.scope === "system"} onClick={() => void changeService(service.installed ? "uninstall" : "install")}>
        {busy === "install" ? "Enabling…" : busy === "uninstall" ? "Removing…" : service.installed ? "Remove service & stop" : "Enable service"}
      </Button>
    </div>}
    {(error || loadError) && <p role="alert" className="mt-3 text-sm text-destructive">{error || loadError}</p>}
    <ConfirmDialog open={confirm} title="Restart shared gateway?" description={`This reconnects ${shared?.length || 0} bots on this device.`} confirmLabel="Restart" onCancel={() => setConfirm(false)} onConfirm={() => { setConfirm(false); void run("restart"); }} />
  </section>;
}
