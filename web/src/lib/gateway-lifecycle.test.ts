import { afterEach, expect, it, vi } from "vitest";
import { api, type StatusResponse } from "@/lib/api";
import { gatewayActionComplete, runGatewayAction, runGatewayServiceAction } from "./gateway-lifecycle";
vi.mock("@/lib/api", () => ({ api: { getStatus: vi.fn(), restartGateway: vi.fn(), getActionStatus: vi.fn(), getGatewayService: vi.fn(), setGatewayService: vi.fn() } }));
const state = (running: boolean, pid: number) => ({ gateway_running: running, gateway_state: running ? "running" : "stopped", gateway_pid: pid }) as StatusResponse;
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });
it("requires a new live process for restart, and a stopped gateway for stop", () => {
  expect(gatewayActionComplete("restart", state(true, 1), state(true, 1), false)).toBe(false);
  expect(gatewayActionComplete("restart", state(true, 1), state(true, 2), false)).toBe(true);
  expect(gatewayActionComplete("stop", state(true, 1), state(true, 1), false)).toBe(false);
  expect(gatewayActionComplete("stop", state(true, 1), state(false, 1), false)).toBe(true);
});
it("finishes when the restart child becomes the live gateway without exiting", async () => {
  vi.useFakeTimers();
  vi.mocked(api.getStatus).mockResolvedValueOnce(state(true, 1)).mockResolvedValue(state(true, 2));
  vi.mocked(api.restartGateway).mockResolvedValue({ ok: true, name: "gateway-restart", pid: 2 });
  vi.mocked(api.getActionStatus).mockResolvedValue({ name: "gateway-restart", running: true, exit_code: null, pid: 2, lines: [] });
  const result = runGatewayAction("restart");
  await vi.advanceTimersByTimeAsync(750);
  expect((await result).gateway_pid).toBe(2);
});
it("settles even when the status request never returns", async () => {
  vi.useFakeTimers();
  vi.mocked(api.getStatus).mockReturnValue(new Promise(() => {}));
  const result = expect(runGatewayAction("restart")).rejects.toThrow("within 30 seconds");
  await vi.advanceTimersByTimeAsync(30_000);
  await result;
});

it("waits for both service registration and a live gateway after install", async () => {
  vi.useFakeTimers();
  vi.mocked(api.getStatus).mockResolvedValueOnce(state(false, 0)).mockResolvedValue(state(true, 2));
  vi.mocked(api.setGatewayService).mockResolvedValue({ ok: true, name: "gateway-service-install", pid: 3 });
  vi.mocked(api.getActionStatus).mockResolvedValue({ name: "gateway-service-install", running: false, exit_code: 0, pid: 3, lines: [] });
  vi.mocked(api.getGatewayService).mockResolvedValue({ installed: true, supported: true, kind: "systemd", scope: "user" });
  const result = runGatewayServiceAction("install");
  await vi.advanceTimersByTimeAsync(750);
  expect((await result).service.installed).toBe(true);
});
it("bounds service setup when the request hangs", async () => {
  vi.useFakeTimers();
  vi.mocked(api.getStatus).mockReturnValue(new Promise(() => {}));
  const result = expect(runGatewayServiceAction("install")).rejects.toThrow("timed out");
  await vi.advanceTimersByTimeAsync(60_000);
  await result;
});
