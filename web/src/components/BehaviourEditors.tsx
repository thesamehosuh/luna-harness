import { useState } from "react";
import { Plus, RotateCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { thresholdLabel, type BehaviourBundle, type DecisionPolicy, type WakeCondition } from "@/lib/luna-api";

const input = "w-full rounded-xl border border-border bg-background/70 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";
const tabs = ["Reactions", "Wake prompts", "Jev judgments", "Custom conditions"] as const;

export function BehaviourEditors({ behaviour, decision, onDecision, reactions, onReactions, prompts, onPrompts }: {
  behaviour: BehaviourBundle;
  decision: DecisionPolicy;
  onDecision: (value: DecisionPolicy) => void;
  reactions: BehaviourBundle["reactions"];
  onReactions: (value: BehaviourBundle["reactions"]) => void;
  prompts: NonNullable<BehaviourBundle["wake_prompts"]>;
  onPrompts: (value: NonNullable<BehaviourBundle["wake_prompts"]>) => void;
}) {
  const [tab, setTab] = useState<typeof tabs[number]>("Reactions");
  const [emoji, setEmoji] = useState("");
  const [emojiError, setEmojiError] = useState("");
  const [search, setSearch] = useState("");
  const updateRule = (id: string, patch: Partial<WakeCondition>) => onDecision({
    ...decision, rules: decision.rules.map(rule => rule.id === id ? { ...rule, ...patch } : rule),
  });
  const updateQuestion = (id: string, patch: DecisionPolicy["questions"][string]) => onDecision({
    ...decision, questions: { ...decision.questions, [id]: { ...decision.questions[id], ...patch } },
  });

  return <section className="my-6 min-w-0" aria-label="Behaviour customization">
    <div className="flex flex-wrap gap-1 border-b border-border pb-2" role="group" aria-label="Behaviour editors">
      {tabs.map(name => <Button key={name} size="sm" ghost={tab !== name} aria-pressed={tab === name} onClick={() => setTab(name)}>{name}</Button>)}
    </div>
    <div className="pt-5">
      {tab === "Reactions" && <div className="space-y-4">
        <div><h3 className="text-lg font-medium">A reaction for every kind of moment</h3>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Choose your own emoji and tell Jev what each one means. Removing every reaction turns reactions off.</p></div>
        {reactions.allowed.length === 0 && <p className="rounded-xl bg-muted/40 p-4 text-sm">Reactions are off. Add an emoji to build your companion’s palette.</p>}
        <div className="space-y-3">
          {reactions.allowed.map((value, index) => <div key={value} className="flex items-start gap-3 border-b border-border/60 pb-3">
            <span className="flex h-11 w-12 shrink-0 items-center justify-center rounded-xl bg-muted/60 text-2xl" aria-hidden="true">{value}</span>
            <label className="min-w-0 flex-1 text-xs text-muted-foreground">When to use {value}
              <textarea className={`${input} mt-1 min-h-20 resize-y`} maxLength={12000}
                value={reactions.criteria?.[value] ?? behaviour.reaction_defaults?.[value] ?? ""}
                placeholder="Describe the feeling or situations this reaction fits."
                onChange={e => onReactions({ ...reactions, criteria: { ...reactions.criteria, [value]: e.target.value } })} /></label>
            <Button ghost size="sm" className="mt-5" aria-label={`Remove reaction ${value}`} onClick={() => {
              const criteria = { ...reactions.criteria };
              delete criteria[value];
              onReactions({ allowed: reactions.allowed.filter((_, i) => i !== index), criteria });
            }}><Trash2 className="h-4 w-4" /></Button>
          </div>)}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-muted-foreground">New reaction
            <input className={`${input} mt-1 max-w-44`} placeholder="Paste an emoji" value={emoji} maxLength={32} onChange={e => { setEmoji(e.target.value); setEmojiError(""); }} /></label>
          <Button outlined size="sm" disabled={!emoji.trim()} onClick={() => {
            const value = emoji.trim();
            if (/\s/.test(value) || reactions.allowed.includes(value)) { setEmojiError("Choose one emoji that is not already in the palette."); return; }
            onReactions({ ...reactions, allowed: [...reactions.allowed, value] }); setEmoji("");
          }}><Plus className="mr-1 h-4 w-4" />Add reaction</Button>
        </div>
        {emojiError && <p role="alert" className="text-sm text-destructive">{emojiError}</p>}
        <p className="text-xs text-muted-foreground">Telegram must support the chosen emoji and allow this bot to react. Edit reaction fit, freshness, and selection prompts in Jev judgments.</p>
      </div>}

      {tab === "Wake prompts" && <div className="space-y-5">
        <div><h3 className="text-lg font-medium">What starts a reply</h3><p className="mt-1 text-sm text-muted-foreground">Edit the instructions your companion receives after Jev selects a text wake. The selected message and room context are attached automatically.</p></div>
        {(["directed", "message"] as const).map(kind => <div key={kind} className="space-y-2">
          <div className="flex items-center justify-between gap-3"><label htmlFor={`wake-${kind}`} className="text-sm font-medium">{kind === "directed" ? "When someone addresses your companion" : "When your companion joins in"}</label>
            <Button ghost size="sm" disabled={prompts[kind] === undefined} aria-label={`Reset ${kind} wake prompt`} onClick={() => { const next = { ...prompts }; delete next[kind]; onPrompts(next); }}><RotateCcw className="mr-1 h-3.5 w-3.5" />Use default</Button></div>
          <textarea id={`wake-${kind}`} className={`${input} min-h-36 resize-y leading-relaxed`} maxLength={12000} value={prompts[kind] ?? behaviour.wake_prompt_defaults?.[kind] ?? ""} onChange={e => onPrompts({ ...prompts, [kind]: e.target.value })} />
        </div>)}
        <p className="text-xs text-muted-foreground">Use <code>{"{contribution_type}"}</code> for the selected kind of contribution. Character voice comes from Character; group output limits still apply.</p>
      </div>}

      {tab === "Jev judgments" && <div className="space-y-4">
        <div><h3 className="text-lg font-medium">Teach Jev how to judge a moment</h3><p className="mt-1 text-sm text-muted-foreground">Every question and answer rubric is editable. Question types and answer positions connect these judgments to the wake thresholds below.</p></div>
        <label className="block text-xs text-muted-foreground">Find a judgment<input className={`${input} mt-1`} placeholder="Search reaction, privacy, timing…" value={search} onChange={e => setSearch(e.target.value)} /></label>
        {!behaviour.question_defaults?.length && <p className="text-sm text-muted-foreground">Judgment defaults are unavailable. Refresh after updating the dashboard backend.</p>}
        {behaviour.question_defaults?.filter(q => `${q.id} ${q.instructions}`.toLowerCase().includes(search.toLowerCase())).map(q => {
          const patch = decision.questions[q.id];
          const criteria = patch?.criteria ?? q.criteria;
          return <details key={q.id} className="rounded-xl border border-border p-4">
            <summary className="cursor-pointer text-sm font-medium">{thresholdLabel(q.id)} <span className="ml-2 text-xs font-normal text-muted-foreground">{patch ? "Customized" : "Default"}</span></summary>
            <div className="mt-4 space-y-3">
              <label className="block text-xs text-muted-foreground">Question prompt<textarea className={`${input} mt-1 min-h-32 resize-y leading-relaxed`} maxLength={12000} value={patch?.instructions ?? q.instructions} onChange={e => updateQuestion(q.id, { instructions: e.target.value })} /></label>
              {q.id === "reaction_emoji" ? <p className="text-xs text-muted-foreground">Edit emoji choices and their meanings in Reactions.</p> : <div className="grid gap-3 sm:grid-cols-2">
                {Object.entries(criteria).map(([key, value]) => <label key={key} className="text-xs text-muted-foreground">{q.type === "score" ? `Score ${key}` : key}
                  <textarea className={`${input} mt-1 min-h-20 resize-y`} maxLength={12000} value={value} onChange={e => updateQuestion(q.id, { criteria: Array.isArray(criteria) ? criteria.map((v, i) => i === Number(key) ? e.target.value : v) : { ...criteria, [key]: e.target.value } })} /></label>)}
              </div>}
              <Button ghost size="sm" disabled={!patch} onClick={() => { const next = { ...decision.questions }; delete next[q.id]; onDecision({ ...decision, questions: next }); }}><RotateCcw className="mr-1 h-3.5 w-3.5" />Reset judgment</Button>
            </div>
          </details>;
        })}
      </div>}

      {tab === "Custom conditions" && <div className="space-y-4">
        <div><h3 className="text-lg font-medium">Your own reasons to speak or stay quiet</h3><p className="mt-1 max-w-2xl text-sm text-muted-foreground">Add a yes/no question Jev must answer yes to before a wake can proceed. Every enabled condition for that action must pass, alongside the usual wake checks.</p></div>
        {!decision.rules.length && <p className="rounded-xl bg-muted/40 p-4 text-sm">No custom conditions yet. Try “Is this a conversation about one of my companion’s interests?”</p>}
        {decision.rules.map(rule => <fieldset key={rule.id} className="space-y-3 rounded-xl border border-border p-4">
          <legend className="px-1 text-sm">{rule.name || "New condition"}</legend>
          <div className="flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rule.enabled} onChange={e => updateRule(rule.id, { enabled: e.target.checked })} />Enabled</label>
            <Button ghost size="sm" className="ml-auto" aria-label={`Remove condition ${rule.name}`} onClick={() => onDecision({ ...decision, rules: decision.rules.filter(r => r.id !== rule.id) })}><Trash2 className="mr-1 h-4 w-4" />Remove condition</Button></div>
          <label className="block text-xs text-muted-foreground">Condition name<input className={`${input} mt-1`} value={rule.name} onChange={e => updateRule(rule.id, { name: e.target.value })} /></label>
          <label className="block text-xs text-muted-foreground">Question Jev must answer yes to<textarea className={`${input} mt-1 min-h-24 resize-y`} value={rule.instructions} maxLength={12000} placeholder="Refer to candidate.text, recent_messages, or luna_recent_activity." onChange={e => updateRule(rule.id, { instructions: e.target.value })} /></label>
          <div className="grid gap-3 sm:grid-cols-2"><label className="text-xs text-muted-foreground">Apply to<select className={`${input} mt-1`} value={rule.action} onChange={e => updateRule(rule.id, { action: e.target.value as WakeCondition["action"] })}><option value="both">Text wakes and reactions</option><option value="message">Text wakes</option><option value="reaction">Reactions</option></select></label>
            <label className="text-xs text-muted-foreground">Minimum yes probability (0–1)<input className={`${input} mt-1`} type="number" min={0} max={1} step={0.05} value={rule.threshold} onChange={e => updateRule(rule.id, { threshold: e.target.valueAsNumber })} /></label></div>
        </fieldset>)}
        <Button outlined size="sm" disabled={decision.rules.length >= 30} onClick={() => onDecision({ ...decision, rules: [...decision.rules, { id: crypto.randomUUID(), name: "New condition", instructions: "", action: "both", threshold: 0.8, enabled: true }] })}><Plus className="mr-1 h-4 w-4" />Add condition</Button>
      </div>}
    </div>
  </section>;
}
