import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ArrowRight, Brain, Check, KeyRound, LogIn, MessageCircle, Moon, RefreshCw, UserRound, Zap } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Card, CardContent } from "@/components/ui/Card";
import { Select } from "@/components/ui/Select";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { usePageHeader } from "@/contexts/usePageHeader";
import { errorMessage } from "@/lib/api-error";
import { runGatewayAction } from "@/lib/gateway-lifecycle";
import { api, getManagementProfile } from "@/lib/api";
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

const STEP_UI: Record<string, { label: string; title: string; icon: typeof Brain }> = {
  provider: { label: "Model", title: "Choose a model", icon: Zap },
  telegram: { label: "Telegram", title: "Connect Telegram", icon: MessageCircle },
  honcho: { label: "Memory", title: "Add memory", icon: Brain },
  character: { label: "Character", title: "Choose a character", icon: UserRound },
  wake_test: { label: "Wakes", title: "Try self-wakes", icon: Moon },
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

const inputClass = "rounded-control border border-input bg-transparent px-3 py-2 text-sm transition-colors hover:border-primary/50 focus-visible:outline-2 focus-visible:outline-primary";

export default function OnboardingPage() {
  const heading = useRef<HTMLHeadingElement>(null);
  const [activeStep, setActiveStep] = useState<string | null>(() => window.location.hash.replace("#step-", "") || null);
  const [modelPicker, setModelPicker] = useState(false);
  const [modelRevision, setModelRevision] = useState(0);
  const [steps, setSteps] = useState<StepReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [personas, setPersonas] = useState<PersonaPreset[]>([]);
  const [wakeReport, setWakeReport] = useState<WakeTestResult | null>(null);
  const [memoryProgress, setMemoryProgress] = useState("");
  const [provider, setProvider] = useState({ ...PROVIDER_PRESETS[0], model: "" });
  const [apiKey, setApiKey] = useState("");
  const [wakeKey, setWakeKey] = useState("");
  const [telegram, setTelegram] = useState({ token: "", chatId: "", adminId: "" });
  const [telegramResult, setTelegramResult] = useState("");
  const [personaId, setPersonaId] = useState("generic");
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  useEffect(() => { heading.current?.focus(); }, [activeStep, loading]);

  const load = useCallback(async () => {
    try {
      const report = await onboardingApi.get();
      setLoadError("");
      setSteps(report.steps);
      setActiveStep(previous => previous || firstIncomplete(report.steps) || report.steps[0]?.id || null);
      const messaging = report.steps.find(step => step.id === "telegram");
      if (messaging) setTelegram(previous => ({ ...previous,
        chatId: previous.chatId || String((messaging.groups as string[] | undefined)?.[0] || ""),
        adminId: previous.adminId || String((messaging.admin_ids as string[] | undefined)?.[0] || ""),
      }));
      const saved = report.steps.find(step => step.id === "provider");
      if (saved?.configured === true) {
        const preset = PROVIDER_PRESETS.find(item => item.provider === saved.provider)
          || PROVIDER_PRESETS.find(item => item.provider === (saved.account_connected ? "subscription" : ""))!;
        setProvider({ ...preset, model: String(saved.model || ""), baseUrl: String(saved.base_url || preset.baseUrl), keyEnv: String(saved.key_env || preset.keyEnv) });
      }
    } catch (e) {
      setLoadError(errorMessage(e));
      showToast(`Could not load setup status: ${errorMessage(e)}`, "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const followHash = () => setActiveStep(window.location.hash.replace("#step-", "") || null);
    window.addEventListener("hashchange", followHash);
    return () => window.removeEventListener("hashchange", followHash);
  }, []);

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
      .then((res) => {
        setPersonas(res.personas);
        setPersonaId(res.personas.find(persona => persona.is_current)?.id || "generic");
      })
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
    setTelegramResult("Saving Telegram…");
    try {
      if (telegram.token.trim()) {
        await api.setEnvVar("TELEGRAM_BOT_TOKEN", telegram.token.trim());
      }
      const chat = telegram.chatId.trim();
      const admin = telegram.adminId.trim();
      const existing = steps.find(step => step.id === "telegram");
      const ids = (key: string) => Array.isArray(existing?.[key]) ? (existing[key] as unknown[]).map(String) : [];
      const union = (...values: string[]) => [...new Set(values.filter(value => value && value !== "0"))];
      // Default admin must also pass the transport's DM allowlist.
      await api.setEnvVar("TELEGRAM_ALLOWED_USERS", union(...ids("allowed_user_ids"), admin).join(","));
      await api.saveConfig({
        telegram: {
          ...(chat ? { group_allowed_chats: union(...ids("groups"), chat) } : {}),
          ...(admin ? { allow_admin_from: union(...ids("admin_ids"), admin), group_allow_admin_from: union(...ids("group_admin_ids"), admin) } : {}),
        },
        ...(chat
          ? { luna: { room: { chat_id: chat } } }
          : {}),
        ...(admin
          ? { luna: { notify: { operator_chat: { telegram: admin } } } }
          : {}),
      });
      await api.updateMessagingPlatform("telegram", { enabled: true });
      setTelegram(previous => ({ ...previous, token: "" }));
      setTelegramResult("Connecting Telegram…");
      const status = await api.getStatus();
      await runGatewayAction(status.gateway_running ? "restart" : "start");
      let connected = false;
      for (let attempt = 0; attempt < 20; attempt++) {
        await new Promise(resolve => window.setTimeout(resolve, 1000));
        const result = await api.testMessagingPlatform("telegram");
        if (result.ok) { connected = true; break; }
        if (["fatal", "startup_failed"].includes(result.state)) throw new Error(result.message);
      }
      setTelegramResult(connected ? "Telegram connected. Send your bot a message." : "Settings saved. Telegram is still connecting — check its status in Connections.");
      showToast(connected ? "Telegram connected" : "Telegram settings saved; connection not confirmed yet", connected ? "success" : "error");
      await refresh();
    } catch (e) {
      setTelegramResult(errorMessage(e));
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
      await api.updateProfileSoul(getManagementProfile() || "default", preset.content);
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

  if (loadError && steps.length === 0) return <div className="mx-auto max-w-3xl space-y-4 py-10">
    <LunaMark className="h-10 w-10" />
    <h1 className="luna-page-title text-3xl">Setup couldn’t load</h1>
    <p role="alert" className="text-sm text-destructive">{loadError}</p>
    <Button onClick={load}>Try again</Button>
  </div>;

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

  const optional = currentId === "honcho" || currentId === "wake_test" || currentId === "telegram";
  const connection = provider.provider === "opencode-engine" ? "free" : provider.provider === "subscription" ? "account" : "key";
  const skipped = current?.status === "skipped";

  return (
    <div className="onboarding mx-auto w-full max-w-3xl py-4 sm:py-8">
      <div className="mb-8 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5"><LunaMark className="h-9 w-9" /><span className="text-sm text-muted-foreground">Luna · Setup</span></div>
        <div className="flex items-center gap-2">
          <Button ghost size="icon" onClick={load} disabled={busy !== null} aria-label="Check setup"><RefreshCw className="h-4 w-4" /></Button>
          <Link to="/chat" className="onboarding-quiet-link">Leave setup</Link>
        </div>
      </div>
      <nav aria-label="Setup steps" className="onboarding-steps">
        {steps.map((step, index) => <button key={step.id} type="button"
          aria-label={`${index + 1}. ${STEP_UI[step.id]?.label || step.title}`}
          aria-current={step.id === currentId ? "step" : undefined} disabled={busy !== null}
          onClick={() => goTo(step.id)}>
          <span className="onboarding-step-number" data-complete={step.status === "done"}>{index + 1}</span>
          <span>{STEP_UI[step.id]?.label || step.title}</span>
        </button>)}
      </nav>
      <div className="sr-only" role="progressbar" aria-label="Setup completion" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} />
      <div className="mb-5 mt-9 flex items-center justify-between gap-3">
        <h1 ref={heading} tabIndex={-1} className="luna-page-title text-3xl outline-none sm:text-4xl">{STEP_UI[currentId || ""]?.title || current?.title || "Set up Luna"}</h1>
        {optional && <span className="text-xs text-muted-foreground">Optional</span>}
        {current?.status === "done" && <span className="text-xs text-success">{current.id === "telegram" ? "Saved" : "Ready"}</span>}
      </div>
      {current && <Card key={current.id} id={`step-${current.id}`}>
        <CardContent className="p-5 sm:p-7">
          {skipped ? <div className="flex items-center justify-between gap-3 py-5">
            <span className="text-sm text-muted-foreground">Skipped for now</span>
            <Button outlined size="sm" disabled={busy !== null} onClick={() => chooseOptional(current.id as "honcho" | "wake_test" | "telegram", "enabled")}>Set up now</Button>
          </div> : <>
          {current.id === "provider" && <div className="space-y-6">
            <div className="onboarding-connections" role="group" aria-label="Model connection">
              {([
                ["free", "Free models", Zap],
                ["account", "Sign in", LogIn],
                ["key", "API key", KeyRound],
              ] as const).map(([id, label, Icon]) => <button key={id} type="button" aria-label={label} aria-pressed={connection === id}
                onClick={() => setProvider({ ...PROVIDER_PRESETS[id === "free" ? 0 : id === "account" ? 1 : 3], model: provider.model })}>
                <Icon className="h-5 w-5" /><span className="font-medium">{label}</span>
              </button>)}
            </div>
            {connection === "free" ? <OpenCodeSetup onSaved={refresh} compact />
              : connection === "account" ? <div className="space-y-5">
                <OAuthProvidersCard guided compact onError={message => showToast(message, "error")} onSuccess={() => {
                  setModelRevision(value => value + 1); void refresh();
                }} />
                <Button onClick={() => setModelPicker(true)}>Choose companion model<ArrowRight className="ml-2 h-4 w-4" /></Button>
              </div> : <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1 sm:col-span-2"><span className="text-xs text-muted-foreground">Provider</span>
                  <Select label="Provider" value={provider.label} options={PROVIDER_PRESETS.slice(2).map(preset => ({ value: preset.label, label: preset.label }))}
                    onValueChange={value => { const preset = PROVIDER_PRESETS.find(item => item.label === value)!; setProvider({ ...preset, model: provider.model }); }} />
                </div>
                <Field label="Model"><input className={inputClass} placeholder="Model ID" value={provider.model} onChange={event => setProvider({ ...provider, model: event.target.value })} /></Field>
                <Field label="API key"><input className={inputClass} type="password" autoComplete="off" value={apiKey} onChange={event => setApiKey(event.target.value)} /></Field>
                {!provider.provider && <Field label="Endpoint URL"><input className={inputClass} placeholder="https://…/v1" value={provider.baseUrl} onChange={event => setProvider({ ...provider, baseUrl: event.target.value })} /></Field>}
                <details className="sm:col-span-2">
                  <summary className="onboarding-disclosure">Connection options</summary>
                  <div className="grid gap-3 pt-3 sm:grid-cols-2">
                    {provider.provider && <Field label="Endpoint URL"><input className={inputClass} value={provider.baseUrl} onChange={event => setProvider({ ...provider, baseUrl: event.target.value })} /></Field>}
                    <Field label="Key variable"><input className={inputClass} value={provider.keyEnv} onChange={event => setProvider({ ...provider, keyEnv: event.target.value })} /></Field>
                  </div>
                </details>
                <div className="sm:col-span-2"><Button onClick={saveProvider} disabled={busy !== null || !provider.model.trim() || !provider.baseUrl.trim()}>Save connection</Button></div>
              </div>}
          </div>}
          {current.id === "telegram" && <div className="space-y-5">
            <div className="flex items-center justify-between gap-3"><label htmlFor="telegram-setup-token" className="text-sm font-medium">Bot token</label><a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="onboarding-quiet-link">Create a bot ↗</a></div>
            <div className="onboarding-token-row"><MessageCircle className="h-5 w-5 text-primary" aria-hidden="true" /><input id="telegram-setup-token" aria-label="Bot token" className={inputClass} type="password" autoComplete="off" placeholder={current.token_present ? "Bot token saved securely" : "123456:ABC…"} value={telegram.token} onChange={event => setTelegram({ ...telegram, token: event.target.value })} /></div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Your Telegram user ID · default admin"><input className={inputClass} inputMode="numeric" placeholder="123456789" value={telegram.adminId} onChange={event => setTelegram({ ...telegram, adminId: event.target.value })} /></Field>
              <Field label="Group chat ID"><input className={inputClass} inputMode="text" placeholder="-100…" value={telegram.chatId} onChange={event => setTelegram({ ...telegram, chatId: event.target.value })} /></Field>
            </div>
            <div className="onboarding-card-actions"><Link to="/channels" className="onboarding-quiet-link">Connections<ArrowRight className="h-3.5 w-3.5" /></Link><Button onClick={saveTelegram} disabled={busy !== null || !/^[1-9]\d*$/.test(telegram.adminId.trim()) || !/^-[1-9]\d*$/.test(telegram.chatId.trim()) || (!telegram.token.trim() && current.token_present !== true)}>{busy === "telegram" ? "Connecting…" : "Save & connect"}</Button></div>
            {telegramResult && <p role="status" className="text-sm text-muted-foreground">{telegramResult}</p>}
          </div>}
          {current.id === "honcho" && <div className="space-y-5">
            <MemoryReasoningSelector key={modelRevision} compact />
            <div className="onboarding-card-actions">
              <Link to="/memory" className="onboarding-quiet-link">Memory settings</Link>
              <Button onClick={startHoncho} disabled={busy !== null}>{busy === "honcho" && <Spinner className="mr-2 h-4 w-4" />}{busy === "honcho" ? "Setting up memory…" : "Set up memory"}</Button>
            </div>
            {busy === "honcho" ? <p role="status" className="text-sm">{memoryProgress || "Preparing memory…"}</p> : null}
          </div>}
          {current.id === "character" && <div className="space-y-5">
            <div className="onboarding-personas" role="radiogroup" aria-label="Character preset">
              {personas.map(persona => <label key={persona.id} data-selected={personaId === persona.id}>
                <input className="sr-only" type="radio" name="persona" checked={personaId === persona.id} onChange={() => setPersonaId(persona.id)} />
                <span className="font-medium">{persona.name}</span>
                {persona.sample && <span className="onboarding-persona-sample">“{persona.sample}”</span>}
                {personaId === persona.id && <Check className="onboarding-persona-check h-4 w-4" />}
              </label>)}
            </div>
            {personas.find(persona => persona.id === personaId) && <details><summary className="onboarding-disclosure">View persona</summary><pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap text-sm text-muted-foreground">{personas.find(persona => persona.id === personaId)?.content}</pre></details>}
            <div className="onboarding-card-actions"><Link to="/character" className="onboarding-quiet-link">Write your own<ArrowRight className="h-3.5 w-3.5" /></Link><Button onClick={applyPersona} disabled={busy !== null || !personas.length}>Apply persona</Button></div>
          </div>}
          {current.id === "wake_test" && <div className="space-y-5">
            <Field label="OpenCode Zen key"><input className={inputClass} type="password" autoComplete="off" placeholder="Optional if already connected" value={wakeKey} onChange={event => setWakeKey(event.target.value)} /></Field>
            <div className="onboarding-card-actions">
              <span className="text-xs text-muted-foreground">One model call · Nothing sent to your chats</span>
              <Button onClick={() => runWakeTest(true)} disabled={busy !== null}>{busy === "wake_test" ? "Testing…" : "Test connection"}</Button>
            </div>
            {wakeReport && <p role="status" className={`text-sm ${wakeReport.ok ? "text-success" : "text-destructive"}`}>{wakeReport.detail}</p>}
            <details><summary className="onboarding-disclosure">Test options</summary><div className="space-y-3 pt-3">
              <Button outlined size="sm" onClick={() => runWakeTest(false)} disabled={busy !== null}>Run dry-run test</Button>
              {wakeReport?.decision && <p className="font-mono text-xs">{wakeReport.decision.action} · {wakeReport.decision.reason}</p>}
              <p className="text-xs text-muted-foreground">Self-wakes remain off until you enable them.</p>
              <Link to="/behaviour" className="onboarding-quiet-link">Wake settings<ArrowRight className="h-3.5 w-3.5" /></Link>
            </div></details>
          </div>}
          </>}
        </CardContent>
      </Card>}
      <div className="mt-5 flex items-center justify-between gap-3">
        <Button ghost disabled={busy !== null || currentIndex <= 0} onClick={() => goTo(steps[currentIndex - 1].id)}>Back</Button>
        <div className="flex items-center gap-3">
          {optional && !skipped && <Button ghost disabled={busy !== null} onClick={() => chooseOptional(currentId as "honcho" | "wake_test" | "telegram", "skipped")}>Skip for now</Button>}
          {currentIndex < steps.length - 1 ? <Button disabled={busy !== null || !canContinue} onClick={() => goTo(steps[currentIndex + 1].id)}>Next<ArrowRight className="ml-2 h-4 w-4" /></Button>
            : <Link to="/chat" className="onboarding-finish">Open Chat<ArrowRight className="h-4 w-4" /></Link>}
        </div>
      </div>
      <details className="mt-5 px-1 py-3">
        <summary className="onboarding-disclosure">More setup options</summary>
        <div className="grid gap-3 pt-4 text-sm sm:grid-cols-2">
          <Link to="/controls" className="onboarding-quiet-link">Models & accounts</Link>
          <Link to="/controls#keys" className="onboarding-quiet-link">API keys</Link>
          <Link to="/channels" className="onboarding-quiet-link">Messaging</Link>
          <Link to="/character" className="onboarding-quiet-link">Character editor</Link>
          <Link to="/skills" className="onboarding-quiet-link">Tools & permissions</Link>
          <Link to="/config" className="onboarding-quiet-link">Advanced settings</Link>
          {current?.detail && <p className="text-xs text-muted-foreground sm:col-span-2" role="status">{current.detail}</p>}
        </div>
      </details>
      {modelPicker && <ModelPickerDialog loader={api.getModelOptions} alwaysGlobal title="Choose companion model"
        onClose={() => setModelPicker(false)} onApply={async ({ provider, model, confirmExpensiveModel }) => {
          const result = await api.setModelAssignment({ scope: "main", provider, model, confirm_expensive_model: confirmExpensiveModel });
          if (result.confirm_required) return result;
          setModelRevision(value => value + 1); await refresh(); setModelPicker(false); return result;
        }} />}
      <Toast toast={toast} />
    </div>
  );
}
