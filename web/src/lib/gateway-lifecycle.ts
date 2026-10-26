import { api, type StatusResponse } from "@/lib/api";

export type GatewayAction = "start" | "stop" | "restart";

export function gatewayActionComplete(action: GatewayAction, before: StatusResponse, current: StatusResponse, sawStopped: boolean) {
  if (action === "stop") return !current.gateway_running;
  if (!current.gateway_running || current.gateway_state === "starting") return false;
  if (action === "start" || !before.gateway_running || sawStopped) return true;
  return current.gateway_pid != null && current.gateway_pid !== before.gateway_pid;
}

/** A foreground restart child can become the gateway and never exit. Watch the
 * actual gateway identity, with a deadline, rather than waiting for that child. */
export async function runGatewayAction(action: GatewayAction): Promise<StatusResponse> {
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = () => new Error(`Gateway ${action} was not confirmed within 30 seconds. Check System for details.`);
  const perform = async () => {
    const before = await api.getStatus();
    if (cancelled) throw timeout();
    const response = await (action === "start" ? api.startGateway() : action === "stop" ? api.stopGateway() : api.restartGateway());
    const deadline = Date.now() + 30_000;
    let sawStopped = !before.gateway_running;
    while (!cancelled && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 750));
      const [current, job] = await Promise.all([
        api.getStatus().catch(() => null),
        api.getActionStatus(response.name, 1).catch(() => null),
      ]);
      if (job && !job.running && job.exit_code != null && job.exit_code !== 0) {
        throw new Error(`Gateway ${action} failed. Open System for details.`);
      }
      if (current) {
        if (gatewayActionComplete(action, before, current, sawStopped)) return current;
        if (!current.gateway_running) sawStopped = true;
      }
    }
    throw timeout();
  };
  try {
    return await Promise.race([perform(), new Promise<never>((_, reject) => {
      timer = setTimeout(() => { cancelled = true; reject(timeout()); }, 30_000);
    })]);
  } finally { cancelled = true; clearTimeout(timer); }
}
