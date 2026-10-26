import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { CheckCircle2, Circle, Play, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/ui/h2";
import { Card, CardContent } from "@/components/ui/Card";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { usePageHeader } from "@/contexts/usePageHeader";
import { errorMessage } from "@/lib/api-error";
import { lunaHomePath } from "@/lib/luna-paths";
import { api } from "@/lib/api";
import OpenCodeSetup from "@/components/OpenCodeSetup";
import { LunaMark } from "@/components/LunaMark";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { MemoryReasoningSelector } from "@/components/MemoryReasoningSelector";
import {
  completionPercent,
  firstIncomplete,
  onboardingApi,
  type PersonaPreset,
  type StepReport,
  type WakeTestResult,
} from "@/lib/luna-onboarding";

const PROVIDER_PRESETS: Array<{ label: string; provider: string; baseUrl: string; keyEnv: string }> = [
  { label: "OpenCode (free models)", provider: "opencode-engine", baseUrl: "", keyEnv: "" },
  { label: "Subscription / connected account", provider: "subscription", baseUrl: "", keyEnv: "" },
  { label: "OpenCode Zen", provider: "opencode", baseUrl: "https://opencode.ai/zen/v1", keyEnv: "OPENCODE_ZEN_API_KEY" },
  { label: "OpenRouter", provider: "openrouter", baseUrl: "https://openrouter.ai/api/v1", keyEnv: "OPENROUTER_API_KEY" },
  { label: "OpenAI", provider: "openai", baseUrl: "https://api.openai.com/v1", keyEnv: "OPENAI_API_KEY" },
  { label: "Custom endpoint", provider: "", baseUrl: "", keyEnv: "" },
];

function StepIcon({ status }: { status: string }) {
  return status === "done" ? (
    <CheckCircle2 className="h-5 w-5 text-success" />
  ) : (
    <Circle className="h-5 w-5 text-muted-foreground" />
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

const inputClass = "rounded border bg-transparent px-2 py-1 text-sm";

export default function OnboardingPage() {
  const heading = useRef<HTMLHeadingElement>(null);
  const [activeStep, setActiveStep] = useState<string | null>(() => window.location.hash.replace("#step-", "") || null);
  const [modelPicker, setModelPicker] = useState(false);
  const [modelRevision, setModelRevision] = useState(0);
  const [steps, setSteps] = useState<StepReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [personas, setPersonas] = useState<PersonaPreset[]>([]);
  const [wakeReport, setWakeReport] = useState<WakeTestResult | null>(null);
  const [memoryProgress, setMemoryProgress] = useState("");
  const [provider, setProvider] = useState({ ...PROVIDER_PRESETS[0], model: "" });
  const [apiKey, setApiKey] = useState("");
  const [wakeKey, setWakeKey] = useState("");
  const [telegram, setTelegram] = useState({ token: "", chatId: "", adminId: "" });
  const [personaId, setPersonaId] = useState("generic");
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  useEffect(() => { heading.current?.focus(); }, [activeStep, loading]);

  const load = useCallback(async () => {
    try {
      const report = await onboardingApi.get();
      setSteps(report.steps);
      setActiveStep(previous => previous || firstIncomplete(report.steps) || report.steps[0]?.id || null);
      const saved = report.steps.find(step => step.id === "provider");
      if (saved?.configured === true) {
        const preset = PROVIDER_PRESETS.find(item => item.provider === saved.provider)
          || PROVIDER_PRESETS.find(item => item.provider === (saved.account_connected ? "subscription" : ""))!;
        setProvider({ ...preset, model: String(saved.model || ""), baseUrl: String(saved.base_url || preset.baseUrl), keyEnv: String(saved.key_env || preset.keyEnv) });
      }
    } catch (e) {
      showToast(`Could not load setup status: ${errorMessage(e)}`, "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (busy !== "honcho") return;
    let active = true;
    const poll = () => import("@/lib/api").then(({ fetchJSON }) => fetchJSON<{ detail: string }>("/api/luna/onboarding/memory/progress"))
      .then(value => { if (active) setMemoryProgress(value.detail); }).catch(() => undefined);
    void poll();
    const timer = window.setInterval(poll, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [busy]);

  useEffect(() => {
    onboardingApi
      .personas()
      .then((res) => setPersonas(res.personas))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setEnd(
      <Button outlined size="sm" onClick={load}>
        <RefreshCw className="mr-1 h-3.5 w-3.5" /> Re-check
      </Button>,
    );
    return () => setEnd(null);
  }, [load, setEnd]);

  const refresh = useCallback(async () => {
    const report = await onboardingApi.get();
    setSteps(report.steps);
    return report;
  }, []);

  const chooseOptional = async (step: "honcho" | "wake_test" | "telegram", choice: "enabled" | "skipped") => {
    setBusy(step);
    try { setSteps((await onboardingApi.choice(step, choice)).steps); }
    catch (e) { showToast(errorMessage(e), "error"); }
    finally { setBusy(null); }
  };

  const saveProvider = async () => {
    setBusy("provider");
    try {
      if (apiKey.trim()) {
        await api.setEnvVar(provider.keyEnv.trim() || "OPENAI_API_KEY", apiKey.trim());
      }
      await api.saveConfig({
        model: {
          provider: provider.provider || "custom",
          default: provider.model.trim(),
          base_url: provider.baseUrl,
          key_env: provider.keyEnv.trim() || "OPENAI_API_KEY",
        },
      });
      setApiKey("");
      showToast("Provider saved", "success");
      await refresh();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setBusy(null);
    }
  };

  const saveTelegram = async () => {
    setBusy("telegram");
    try {
      if (telegram.token.trim()) {
        await api.setEnvVar("TELEGRAM_BOT_TOKEN", telegram.token.trim());
      }
      const chat = telegram.chatId.trim();
      const admin = telegram.adminId.trim();
      await api.saveConfig({
        telegram: {
          ...(chat ? { group_allowed_chats: [chat] } : {}),
          ...(admin ? { allow_admin_from: [admin], group_allow_admin_from: [admin] } : {}),
        },
        ...(chat
          ? { luna: { room: { chat_id: chat } } }
          : {}),
        ...(admin
          ? { luna: { notify: { operator_chat: { telegram: admin } } } }
          : {}),
      });
      setTelegram({ ...telegram, token: "" });
      showToast("Telegram settings saved (restart the gateway to connect)", "success");
      await refresh();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setBusy(null);
    }
  };

  const startHoncho = async () => {
    setBusy("honcho");
    try {
      const res = await onboardingApi.honchoUp(180);
      showToast(res.detail, res.ok ? "success" : "error");
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setBusy(null);
      await refresh();
    }
  };

  const applyPersona = async () => {
    const preset = personas.find((p) => p.id === personaId);
    if (!preset) return;
    setBusy("character");
    try {
      await api.updateProfileSoul("default", preset.content);
      showToast("Persona applied", "success");
      await refresh();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setBusy(null);
    }
  };

  const runWakeTest = async (live: boolean) => {
    setBusy("wake_test");
    try {
      if (live && wakeKey.trim()) {
        await api.setEnvVar("OPENCODE_ZEN_API_KEY", wakeKey.trim());
        setWakeKey("");
      }
      const res = await onboardingApi.wakeTest(live);
      setWakeReport(res);
      showToast(res.detail, res.ok ? "success" : "error");
      await refresh();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-6">
        <Spinner /> Loading setup…
      </div>
    );
  }

  const next = firstIncomplete(steps);
  const percent = completionPercent(steps);
  const currentId = steps.some(step => step.id === activeStep) ? activeStep : next || steps[0]?.id;
  const currentIndex = steps.findIndex(step => step.id === currentId);
  const current = steps[currentIndex];
  const canContinue = current?.id !== "provider" || current.status === "done" || current.configured === true;
  const goTo = (id: string) => {
    setActiveStep(id);
    window.history.replaceState(null, "", `#step-${id}`);
  };

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 py-4 sm:py-10">
      <div className="flex items-center justify-between gap-3">
        <LunaMark className="h-12 w-12" />
        <div className="flex items-center gap-3">
          <Button ghost size="sm" onClick={load} disabled={busy !== null}><RefreshCw className="mr-1 h-3.5 w-3.5" />Check setup</Button>
          <Link to="/chat" className="text-sm underline">Leave setup</Link>
        </div>
      </div>
      <h1 ref={heading} tabIndex={-1} className="luna-page-title text-3xl outline-none sm:text-4xl">
        {steps.find(step => step.id === currentId)?.title || "Set up Luna"}
      </h1>
      <p className="text-sm text-muted-foreground">Make this space yours, one step at a time. Messaging, memory and self-wakes are optional. Your saved choices stay here when you return.</p>
      {steps.some(step => step.id === "provider" && (step.status === "done" || step.configured === true)) && (
        <Link to="/chat" className="inline-flex rounded border px-4 py-2 text-sm">Start chatting</Link>
      )}

      <nav aria-label="Setup steps" className="flex flex-wrap gap-2">
        {steps.map((step, index) => <Button key={step.id} outlined={step.id !== currentId} size="sm"
          aria-current={step.id === currentId ? "step" : undefined} disabled={busy !== null}
          onClick={() => goTo(step.id)}>{index + 1}. {step.title}</Button>)}
      </nav>
      <div className="space-y-2">
        <div className="h-1 overflow-hidden rounded bg-muted" role="progressbar" aria-label="Setup completion" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
        </div>
        <p className="text-xs text-muted-foreground" role="status">Step {currentIndex + 1} of {steps.length} · {percent}% saved</p>
      </div>
      {steps.filter(step => step.id === currentId).map((step) => (
        <Card key={step.id} id={`step-${step.id}`}>
          <CardContent className="p-5 sm:p-7">
            <div className="flex flex-wrap items-center gap-2">
              <StepIcon status={step.status} />
              <H2 className="text-base">{step.title}</H2>
              <Badge tone={step.status === "done" ? "default" : "secondary"}>{step.status === "done" ? "Ready" : step.status === "skipped" ? "Skipped" : "Not set up"}</Badge>
              <span className="min-w-0 basis-full break-words text-xs text-muted-foreground sm:ml-auto sm:basis-auto">{step.detail}</span>
            </div>

            {(step.id === "honcho" || step.id === "wake_test" || step.id === "telegram") && (
              <div className="pt-2">
                <Button outlined size="sm" disabled={busy !== null} onClick={() => chooseOptional(
                  step.id as "honcho" | "wake_test" | "telegram", step.status === "skipped" ? "enabled" : "skipped",
                )}>{step.status === "skipped" ? "Set up now" : "Skip for now"}</Button>
              </div>
            )}

            {step.id === "provider" && (
              <div className="grid max-w-2xl grid-cols-1 gap-3 pt-3 sm:grid-cols-2">
                <Field label="provider">
                  <select
                    className={inputClass}
                    value={provider.label}
                    onChange={(e) => {
                      const preset = PROVIDER_PRESETS.find((p) => p.label === e.target.value) ?? PROVIDER_PRESETS[0];
                      setProvider({ ...preset, model: provider.model });
                    }}
                  >
                    {PROVIDER_PRESETS.map((p) => (
                      <option key={p.label}>{p.label}</option>
                    ))}
                  </select>
                </Field>
                {provider.provider === "opencode-engine" ? (
                  <div className="min-w-0 sm:col-span-2"><OpenCodeSetup onSaved={refresh} /></div>
                ) : provider.provider === "subscription" ? (
                  <div className="space-y-3 sm:col-span-2">
                    <p className="text-sm text-muted-foreground">Sign in with your ChatGPT account using OpenAI Codex, or another supported account. Then choose a model. No separate API key is needed for subscription login.</p>
                    <OAuthProvidersCard guided onError={message => showToast(message, "error")} onSuccess={() => {
                      setModelRevision(value => value + 1);
                      void refresh();
                    }} />
                    <Button onClick={() => setModelPicker(true)}>Choose companion model</Button>
                  </div>
                ) : (<>
                <Field label="model">
                  <input
                    className={inputClass}
                    placeholder="e.g. gpt-5-mini"
                    value={provider.model}
                    onChange={(e) => setProvider({ ...provider, model: e.target.value })}
                  />
                </Field>
                <Field label="base url">
                  <input
                    className={inputClass}
                    value={provider.baseUrl}
                    onChange={(e) => setProvider({ ...provider, baseUrl: e.target.value })}
                  />
                </Field>
                <Field label={`API key env name (${provider.keyEnv || "custom"})`}>
                  <input
                    className={inputClass}
                    value={provider.keyEnv}
                    onChange={(e) => setProvider({ ...provider, keyEnv: e.target.value })}
                  />
                </Field>
                <Field label={`API key (stored in ${lunaHomePath(".env")})`}>
                  <input
                    className={inputClass}
                    type="password"
                    placeholder="sk-…"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                </Field>
                <div className="flex items-end">
                  <Button size="sm" onClick={saveProvider} disabled={busy === "provider" || !provider.model.trim() || !provider.baseUrl.trim()}>
                    Save provider
                  </Button>
                </div>
                </>)}
              </div>
            )}

            {step.id === "telegram" && step.status !== "skipped" && (
              <div className="grid max-w-2xl grid-cols-1 gap-3 pt-3 sm:grid-cols-2">
                <p className="text-xs text-muted-foreground sm:col-span-2">
                  Create a bot with @BotFather, paste the token below, then add the bot to your group
                  and send a message. Use Channels to pair, or enter the group chat id and
                  your own user id as the admin.
                </p>
                <Link to="/channels" className="text-sm underline sm:col-span-2">Open guided channel setup and pairing</Link>
                <Field label="bot token">
                  <input
                    className={inputClass}
                    type="password"
                    placeholder="123456:ABC…"
                    value={telegram.token}
                    onChange={(e) => setTelegram({ ...telegram, token: e.target.value })}
                  />
                </Field>
                <Field label="group chat id">
                  <input
                    className={inputClass}
                    placeholder="-100…"
                    value={telegram.chatId}
                    onChange={(e) => setTelegram({ ...telegram, chatId: e.target.value })}
                  />
                </Field>
                <Field label="your user id (admin)">
                  <input
                    className={inputClass}
                    placeholder="1000…"
                    value={telegram.adminId}
                    onChange={(e) => setTelegram({ ...telegram, adminId: e.target.value })}
                  />
                </Field>
                <div className="flex items-end">
                  <Button size="sm" onClick={saveTelegram} disabled={busy === "telegram"}>
                    Save Telegram
                  </Button>
                </div>
              </div>
            )}

            {step.id === "honcho" && step.status !== "skipped" && (
              <div className="max-w-2xl space-y-3 pt-3">
                <p className="text-xs text-muted-foreground">
                  Give your companion long-term memory of people and conversations. Setup prepares Docker,
                  Honcho and the bundled multilingual embedding model. No embedding API key is needed.
                </p>
                <MemoryReasoningSelector key={modelRevision} />
                <Link to="/memory" className="block text-xs underline">Dialectic turns, recall budget and full Honcho status</Link>
                <Button size="sm" onClick={startHoncho} disabled={busy === "honcho"}>
                  {busy === "honcho" ? <Spinner className="mr-1 h-3.5 w-3.5" /> : null}
                  {busy === "honcho" ? "Setting up memory…" : "Set up memory"}
                </Button>
                {busy === "honcho" && <p role="status" className="text-sm">{memoryProgress || "Preparing memory…"}</p>}
                <p className="text-xs text-muted-foreground">
                  First setup downloads the memory containers. Your operating system may ask permission to install Docker.
                  Existing memory data and unrelated containers are kept.
                </p>
              </div>
            )}

            {step.id === "character" && (
              <div className="space-y-2 pt-3">
                {personas.map((p) => (
                  <label key={p.id} className="flex items-start gap-2 text-sm">
                    <input
                      type="radio"
                      name="persona"
                      checked={personaId === p.id}
                      onChange={() => setPersonaId(p.id)}
                    />
                    <span>
                      <span className="font-medium">{p.name}</span>
                      <span className="block text-xs text-muted-foreground">{p.description}</span>
                    </span>
                  </label>
                ))}
                <Button size="sm" onClick={applyPersona} disabled={busy === "character" || !personas.length}>
                  Apply persona
                </Button>
                <p className="text-xs text-muted-foreground">
                  This writes SOUL.md. The Character page has the full editor for voice, emoji policy,
                  and wake behaviour.
                </p>
              </div>
            )}

            {step.id === "wake_test" && step.status !== "skipped" && (
              <div className="space-y-2 pt-3">
                <p className="max-w-2xl text-xs text-muted-foreground">
                  Self-wakes use Jev separately from the chat model. The default route uses OpenCode
                  Zen; add its key here if you did not use it for chat. You can choose another route in Behaviour.
                  The dry-run checks wiring; the live test verifies a real verdict before setup is complete.
                </p>
                <Field label="OpenCode Zen wake key (optional if already saved)">
                  <input className={inputClass} type="password" value={wakeKey}
                    onChange={(event) => setWakeKey(event.target.value)} />
                </Field>
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" onClick={() => runWakeTest(false)} disabled={busy === "wake_test"}>
                    <Play className="mr-1 h-3.5 w-3.5" /> Run dry-run test
                  </Button>
                  <Button outlined
                    size="sm"
                    onClick={() => runWakeTest(true)}
                    disabled={busy === "wake_test"}
                  >
                    Run live (spends one jev call)
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    A synthetic group message goes through the wake pipeline. Nothing is ever sent to
                    the room.
                  </span>
                </div>
                {wakeReport && (
                  <div className="rounded border p-2 text-xs">
                    <div>
                      <Badge tone={wakeReport.ok ? "default" : "destructive"}>
                        {wakeReport.ok ? "ok" : "failed"}
                      </Badge>{" "}
                      {wakeReport.detail}
                    </div>
                    {wakeReport.decision && (
                      <div className="mt-1 font-mono">
                        action={wakeReport.decision.action} value={wakeReport.decision.value}{" "}
                        route={wakeReport.decision.jev_route} reason={wakeReport.decision.reason}
                      </div>
                    )}
                    {!!wakeReport.route_chain?.length && (
                      <div className="mt-1 text-muted-foreground">
                        routes:{" "}
                        {wakeReport.route_chain
                          .map((r) => `${r.model || "?"}${r.key_set ? "" : " (no key)"}`)
                          .join(" → ")}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      ))}

      <div className="flex items-center justify-between gap-3">
        <Button outlined disabled={busy !== null || currentIndex <= 0} onClick={() => goTo(steps[currentIndex - 1].id)}>Back</Button>
        {currentIndex < steps.length - 1 ? <Button disabled={busy !== null || !canContinue} onClick={() => goTo(steps[currentIndex + 1].id)}>Next</Button>
          : <Link to="/chat" className="rounded border px-4 py-2 text-sm">Open Chat</Link>}
      </div>
      <details className="rounded border p-4">
        <summary className="cursor-pointer text-sm font-medium">More setup options</summary>
        <div className="grid gap-3 pt-3 text-sm sm:grid-cols-2">
          <Link to="/config" className="underline">Terminal backend, agent limits and context compression</Link>
          <Link to="/skills" className="underline">Tools, permissions and skills</Link>
          <Link to="/channels" className="underline">Messaging platforms and pairing</Link>
          <Link to="/character" className="underline">Character, voice and persona editor</Link>
          <Link to="/models" className="underline">Models and auxiliary model assignments</Link>
          <Link to="/env" className="underline">API keys and account connections</Link>
        </div>
      </details>
      {modelPicker && <ModelPickerDialog loader={api.getModelOptions} alwaysGlobal title="Choose companion model"
        onClose={() => setModelPicker(false)} onApply={async ({ provider, model, confirmExpensiveModel }) => {
          const result = await api.setModelAssignment({ scope: "main", provider, model, confirm_expensive_model: confirmExpensiveModel });
          if (result.confirm_required) return result;
          setModelRevision(value => value + 1);
          await refresh();
          setModelPicker(false);
          return result;
        }} />}
      {percent === 100 && (
        <Card>
          <CardContent className="py-3 text-sm">
            Setup choices saved. Open Chat to talk to your companion. You can change any optional
            feature here later; self-wakes stay off until you enable them in Behaviour.
          </CardContent>
        </Card>
      )}

      <Toast toast={toast} />
    </div>
  );
}
