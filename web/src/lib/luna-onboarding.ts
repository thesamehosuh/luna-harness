/**
 * Client + pure helpers for the onboarding wizard (PRODUCT_PLAN P3).
 */
import { fetchJSON } from "@/lib/api";

export type StepStatus = "done" | "todo" | "skipped";

export interface StepReport {
  id: string;
  title: string;
  status: StepStatus;
  detail: string;
  [extra: string]: unknown;
}

export interface OnboardingReport {
  steps: StepReport[];
  complete: boolean;
}

export interface PersonaPreset {
  is_current?: boolean;
  id: string;
  name: string;
  description: string;
  sample?: string;
  content: string;
}

export interface HonchoUpResult {
  ok: boolean;
  detail: string;
  env_keys_written?: string[];
  output?: string;
  errors?: string;
}

export interface WakeTestResult {
  ok: boolean;
  live: boolean;
  detail: string;
  stage0?: { allowed: boolean; reason: string };
  questions?: string[];
  route_chain?: Array<{ model: string; base_url: string; key_set: boolean }>;
  decision?: {
    action: string;
    value?: number;
    reason?: string;
    scores?: Record<string, number>;
    jev_route?: string;
  };
  state_preview?: Record<string, unknown>;
}

export const onboardingApi = {
  get: () => fetchJSON<OnboardingReport>("/api/luna/onboarding"),
  choice: (step: "honcho" | "wake_test" | "telegram", choice: "enabled" | "skipped") =>
    fetchJSON<OnboardingReport>("/api/luna/onboarding/choice", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ step, choice }) }),
  personas: () => fetchJSON<{ personas: PersonaPreset[] }>("/api/luna/onboarding/personas"),
  honchoUp: (timeout = 180) =>
    fetchJSON<HonchoUpResult>("/api/luna/onboarding/honcho/up", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ timeout }),
    }),
  wakeTest: (live = false) =>
    fetchJSON<WakeTestResult>("/api/luna/onboarding/wake-test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ live }),
    }),
};

/** Steps still to do, in wizard order. */
export function pendingSteps(steps: StepReport[]): string[] {
  return steps.filter((s) => s.status !== "done" && s.status !== "skipped").map((s) => s.id);
}

/** First incomplete step id (where the wizard should land), or null when done. */
export function firstIncomplete(steps: StepReport[]): string | null {
  const pending = pendingSteps(steps);
  return pending.length ? pending[0] : null;
}

/**
 * Chat requires a model connection. Telegram and memory are optional and cannot
 * bypass or prolong first-run setup.
 */
export function needsFirstRun(steps: StepReport[]): boolean {
  const provider = steps.find((s) => s.id === "provider");
  return !!provider && provider.status !== "done" && provider.configured !== true;
}

/** Progress as a percentage for the wizard header. */
export function completionPercent(steps: StepReport[]): number {
  if (!steps.length) return 0;
  const done = steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  return Math.round((done / steps.length) * 100);
}
