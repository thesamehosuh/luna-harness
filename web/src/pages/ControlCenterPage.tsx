import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router";
import { ArrowUpRight, Brain, ChevronDown, Cpu, KeyRound, Palette, Radio, Search, Settings2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
import { ReasoningPicker } from "@/components/ReasoningPicker";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import OpenCodeSetup from "@/components/OpenCodeSetup";
import { GatewayControls } from "@/components/GatewayControls";
import { useProfileScope } from "@/contexts/useProfileScope";
import { api, type ModelInfoResponse } from "@/lib/api";
import { errorMessage } from "@/lib/api-error";
import { DASHBOARD_NAV } from "@/lib/navigation";
import { cn } from "@/lib/utils";

const AppearanceSettings = lazy(() => import("@/components/AppearanceSettings"));
const EnvPage = lazy(() => import("./EnvPage"));
const sections = [
  { id: "model", label: "Model & accounts", icon: Cpu },
  { id: "keys", label: "API keys", icon: KeyRound },
  { id: "connections", label: "Connections", icon: Radio },
  { id: "preferences", label: "Preferences", icon: Palette },
] as const;

export default function ControlCenterPage() {
  const { hash, search } = useLocation();
  const { profile } = useProfileScope();
  const active = sections.some(s => s.id === hash.slice(1)) ? hash.slice(1) : "model";
  const [query, setQuery] = useState("");
  const [model, setModel] = useState<ModelInfoResponse | null>(null);
  const [picker, setPicker] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    api.getModelInfo(profile).then(value => {
      if (!cancelled) { setModel(value); setError(""); }
    }).catch(reason => { if (!cancelled) setError(errorMessage(reason)); });
    return () => { cancelled = true; };
  }, [profile, revision]);

  const matches = query.trim() ? DASHBOARD_NAV.filter(item =>
    `${item.label} ${item.keywords ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()),
  ) : [];

  return <div className="control-center space-y-7">
    <GatewayControls key={profile} />
    <div className="flex flex-wrap items-start justify-between gap-5">
      <p className="max-w-lg text-sm leading-7 text-muted-foreground">Your model, connections and everyday settings, together.</p>
      <label className="control-search flex w-full items-center gap-2 rounded-control border border-border px-3 sm:w-72">
        <Search className="size-4 shrink-0 text-muted-foreground" />
        <input aria-label="Find a setting" className="h-11 min-w-0 w-full border-0 bg-transparent text-sm outline-none" placeholder="Find a setting…" value={query} onChange={event => setQuery(event.target.value)} />
        {query && <button type="button" className="text-xs text-muted-foreground" onClick={() => setQuery("")}>Clear</button>}
      </label>
    </div>

    {query.trim() ? <section aria-label="Settings search results" className="space-y-2">
      <p className="pb-2 text-sm text-muted-foreground">{matches.length ? `${matches.length} places to look` : "No matching settings. Try model, token, Telegram or memory."}</p>
      {matches.map(item => <Link key={item.path} to={item.path} className="control-link">
        <item.icon className="size-5 text-primary" /><span className="flex-1">{item.label}</span><ArrowUpRight className="size-4 text-muted-foreground" />
      </Link>)}
    </section> : <>
      <nav aria-label="Control Center sections" className="control-tabs">
        {sections.map(section => <Link key={section.id} to={`${search}#${section.id}`} aria-current={active === section.id ? "page" : undefined} className={cn("control-tab", active === section.id && "is-active")}>
          <section.icon className="size-4" />{section.label}
        </Link>)}
      </nav>
      {notice && <p role="status" className="rounded-control border border-success/30 bg-success/5 px-4 py-3 text-sm">{notice}</p>}
      {error && <div role="alert" className="flex flex-wrap items-center gap-3 rounded-control border border-destructive/30 px-4 py-3 text-sm text-destructive">{error}<Button size="sm" outlined onClick={refresh}>Retry</Button></div>}

      {active === "model" && <div className="control-columns">
        <div className="min-w-0 space-y-6">
          <section className="control-section">
            <div className="mb-5 flex items-center gap-3"><span className="control-icon"><Sparkles className="size-5" /></span><div><h2 className="text-lg font-semibold">Your companion’s model</h2><p className="text-sm text-muted-foreground">Choose what powers the conversation.</p></div></div>
            <button type="button" onClick={() => setPicker(true)} className="model-choice" aria-label="Choose companion model">
              <div className="min-w-0 text-left"><span className="block text-xs text-muted-foreground">{model?.provider || "Model connection"}</span><span className="mt-1 block truncate text-lg font-medium">{model?.model?.split("/").at(-1) || "Choose a model"}</span></div>
              <ChevronDown className="size-5 shrink-0 text-primary" />
            </button>
            {model?.capabilities?.supports_reasoning && <div className="mt-3 rounded-control bg-background-base"><ReasoningPicker currentModel={model.model} profile={profile} refreshKey={revision} onChanged={() => setNotice("Reasoning saved. Start a new chat to use it.")} /></div>}
            <p className="mt-4 text-xs leading-6 text-muted-foreground">Changes apply to new chats. Memory has its own reasoning controls.</p>
          </section>
          <OAuthProvidersCard onError={setError} onSuccess={message => { setNotice(message); refresh(); }} />
          <details className="control-section"><summary className="cursor-pointer text-sm font-medium">Use a free model with OpenCode</summary><div className="pt-5"><OpenCodeSetup onSaved={refresh} /></div></details>
        </div>
        <aside className="space-y-5">
          <div className="control-note"><Brain className="mb-3 size-5 text-primary" /><h2 className="font-medium">Memory reasoning</h2><p className="mt-2 text-sm leading-7 text-muted-foreground">Use your companion’s model or choose a separate one, with its own reasoning effort.</p><Link to="/memory" className="mt-4 inline-flex items-center gap-2 text-sm text-primary">Manage memory <ArrowUpRight className="size-4" /></Link></div>
          <QuickLink to="#keys" title="Add an API key" detail="Connect a model provider or a tool." icon={KeyRound} />
          <QuickLink to="/models" title="Advanced models" detail="Fallbacks, specialist models and usage." icon={Settings2} />
        </aside>
      </div>}
      {active === "keys" && <Suspense fallback={<div className="route-skeleton" aria-label="Loading API keys" aria-busy="true" />}><EnvPage embedded /></Suspense>}
      {active === "connections" && <div className="grid max-w-4xl gap-4 sm:grid-cols-2">
        <QuickLink to="/channels" title="Chat apps & bot tokens" detail="Telegram, Discord and your other chat connections." icon={Radio} />
        <QuickLink to="/pairing" title="Access & pairing" detail="Choose who can talk to your companion." icon={KeyRound} />
        <QuickLink to="/system" title="Companion & system" detail="Start, stop, update and check your installation." icon={Settings2} />
        <QuickLink to="/profiles" title="Profiles & transfer" detail="Import or export a character and its settings." icon={Sparkles} />
      </div>}
      {active === "preferences" && <div className="max-w-3xl space-y-6">
        <section className="control-section"><h2 className="mb-5 text-lg font-semibold">Make yourself at home</h2><div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-5"><div><h3 className="text-sm font-medium">Appearance</h3><p className="mt-1 text-sm text-muted-foreground">Theme and typeface for every page.</p></div><ThemeSwitcher /></div><div className="flex flex-wrap items-center justify-between gap-4 pt-5"><div><h3 className="text-sm font-medium">Language</h3><p className="mt-1 text-sm text-muted-foreground">Choose the dashboard’s language.</p></div><LanguageSwitcher /></div></section>
        <Suspense fallback={<div className="route-skeleton" aria-busy="true" />}><AppearanceSettings key={profile} /></Suspense>
        <QuickLink to="/character" title="Character & reply style" detail="Personality, voice, reply length and text cleanup." icon={Sparkles} />
        <QuickLink to="/config" title="All settings" detail="Search the complete configuration when you need something specific." icon={Settings2} />
      </div>}
    </>}
    {picker && <ModelPickerDialog alwaysGlobal onFreeModelSelected={() => { refresh(); setNotice("Free model saved. Your next chat will use it."); }} loader={options => api.getModelOptions({ profile, ...options })} onClose={() => setPicker(false)} onApply={async ({ provider, model: next, confirmExpensiveModel }) => {
      const result = await api.setModelAssignment({ scope: "main", provider, model: next, confirm_expensive_model: confirmExpensiveModel }, profile);
      if (!result.confirm_required) { refresh(); setNotice("Model saved. Your next chat will use it."); }
      return result;
    }} />}
  </div>;
}

function QuickLink({ to, title, detail, icon: Icon }: { to: string; title: string; detail: string; icon: typeof Cpu }) {
  const { search } = useLocation();
  return <Link to={to.startsWith("#") ? `${search}${to}` : to} className="control-link items-start"><Icon className="mt-1 size-5 shrink-0 text-primary" /><div className="min-w-0 flex-1"><span className="text-sm font-medium">{title}</span><p className="mt-1 text-sm leading-6 text-muted-foreground">{detail}</p></div><ArrowUpRight className="mt-1 size-4 shrink-0 text-muted-foreground" /></Link>;
}
