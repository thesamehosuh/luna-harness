import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, Eye, Plus, RefreshCw, Save, Trash2, Upload } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@nous-research/ui/ui/components/confirm-dialog";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/ui/h2";
import { Card, CardContent } from "@/components/ui/Card";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { usePageHeader } from "@/contexts/usePageHeader";
import { BlossomBranch } from "@/components/BlossomBranch";
import { errorMessage } from "@/lib/api-error";
import {
  isDraftDirty,
  useUnsavedChanges,
  useUnsavedChangesGuard,
} from "@/hooks/useUnsavedChanges";
import {
  countLines,
  renderSoul,
  soulPreview,
  soulsDiffer,
} from "@/lib/soul-render";
import {
  lunaApi,
  type CharacterBundle,
  type PreviewResult,
  type SoulSection,
} from "@/lib/luna-api";

const inputClass = "rounded-xl border border-border bg-background/70 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

function outputDraftOf(output: CharacterBundle["output"]) {
  return {
    emoji_filter: output.emoji_filter !== false,
    strip_emoji: !!output.strip_emoji,
    allowed_emoji: (output.allowed_emoji ?? []).join(" "),
    max_lines: Number(output.max_lines) || 4,
    max_chars: output.max_chars ?? 1200,
    language: output.language ?? "auto",
    style_filter: output.style_filter ?? false,
    sentence_breaks: output.sentence_breaks ?? true,
  };
}

function SectionCard({
  section,
  onChange,
  onRemove,
}: {
  section: SoulSection;
  onChange: (next: SoulSection) => void;
  onRemove: () => void;
}) {
  return (
    <div className="rounded-2xl border border-border bg-background/40 p-4">
      <div className="flex items-center gap-2">
        <input
          className={`${inputClass} min-w-0 flex-1 font-medium`}
          value={section.title}
          onChange={(e) => onChange({ ...section, title: e.target.value })}
          aria-label="section title"
        />
        <Button ghost size="sm" onClick={onRemove} title="Remove section">
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      <textarea
        className={`${inputClass} mt-3 min-h-36 w-full resize-y leading-relaxed`}
        value={section.body}
        onChange={(e) => onChange({ ...section, body: e.target.value })}
        aria-label={`body of ${section.title}`}
      />
    </div>
  );
}

export default function CharacterPage() {
  const [bundle, setBundle] = useState<CharacterBundle | null>(null);
  const [title, setTitle] = useState("");
  const [intro, setIntro] = useState("");
  const [sections, setSections] = useState<SoulSection[]>([]);
  const [footer, setFooter] = useState("");
  const [output, setOutput] = useState({ emoji_filter: true, strip_emoji: false, allowed_emoji: "", max_lines: 4, max_chars: 1200, language: "auto", style_filter: false, sentence_breaks: true });
  const [skin, setSkin] = useState("default");
  const [skinColors, setSkinColors] = useState<Record<string, string>>({});
  const [autoLoad, setAutoLoad] = useState<string[]>([]);
  const [presetId, setPresetId] = useState("generic");
  const [sample, setSample] = useState("I am SO happy about this 😭 and 😡!!!\nthis should wrap a bit.");
  const [surface, setSurface] = useState("group");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  // B3: the two destructive persona actions. Applying a preset or importing a SOUL.md replaces the
  // whole file server-side, so no client-side guard can stop it — it needs its own confirmation.
  const [pendingPreset, setPendingPreset] = useState<{ id: string; name: string } | null>(null);
  const [pendingImport, setPendingImport] = useState<{ name: string; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const writing = useRef(false);
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();
  const { requestLeave } = useUnsavedChangesGuard();

  const applyBundle = useCallback((b: CharacterBundle) => {
    setBundle(b);
    setTitle(b.soul.title);
    setIntro(b.soul.intro);
    setSections(b.soul.sections.map((s) => ({ ...s })));
    setFooter(b.soul.footer);
    setOutput(outputDraftOf(b.output));
    setSkin(b.current_skin);
    setSkinColors({ ...b.skins.find((s) => s.name === b.current_skin)?.colors });
    setAutoLoad([...b.auto_load]);
  }, []);

  const load = useCallback(async () => {
    try {
      applyBundle(await lunaApi.getCharacter());
    } catch (e) {
      showToast(`Could not load character: ${errorMessage(e)}`, "error");
    } finally {
      setLoading(false);
    }
  }, [applyBundle, showToast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setEnd(
      <Button
        outlined
        size="sm"
        disabled={busy !== null}
        onClick={() => requestLeave(() => void load())}
        // Reload refetches the bundle and `applyBundle` replaces the persona draft outright, so with
        // unsaved edits it is a silent destroy. Routed through the guard for the same reason as a
        // navigation: no history entry moves, so the guarded history cannot see it.
        title="Refetch from disk"
      >
        <RefreshCw className="mr-1 h-3.5 w-3.5" /> Reload
      </Button>,
    );
    return () => setEnd(null);
  }, [load, setEnd, requestLeave, busy]);

  const runPreview = useCallback(async () => {
    try {
      setPreview(await lunaApi.previewShaping(sample, surface));
    } catch (e) {
      showToast(errorMessage(e), "error");
    }
  }, [sample, surface, showToast]);

  useEffect(() => {
    const timer = window.setTimeout(runPreview, 400);
    return () => window.clearTimeout(timer);
  }, [runPreview]);

  /**
   * Returns whether the persona was written. See `handleYamlSave` — the DirtyBar reads `false` as
   * "did not save" and holds the navigation, so a failed PUT cannot take the draft with it.
   */
  const saveSoul = async (): Promise<boolean> => {
    if (writing.current) return false;
    writing.current = true;
    setBusy("soul");
    try {
      const res = await lunaApi.saveCharacter({
        title,
        intro,
        sections,
        footer,
      }, bundle?.revision);
      setBundle(res.bundle);
      applyBundleToDraft(res.bundle.soul);
      showToast("Persona saved", "success");
      return true;
    } catch (e) {
      showToast(errorMessage(e), "error");
      return false;
    } finally {
      writing.current = false;
      setBusy(null);
    }
  };

  /** Replace SOUL.md with the selected preset. Only reached after the confirmation. */
  const applyPreset = async (id: string) => {
    if (writing.current) return;
    writing.current = true;
    setBusy("preset");
    try {
      const res = await lunaApi.saveCharacter({ preset_id: id }, bundle?.revision);
      setBundle(res.bundle);
      applyBundleToDraft(res.bundle.soul);
      showToast("Preset applied", "success");
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      writing.current = false;
      setBusy(null);
      setPendingPreset(null);
    }
  };

  const saveOutput = async (): Promise<boolean> => {
    if (writing.current) return false;
    writing.current = true;
    setBusy("output");
    try {
      const res = await lunaApi.saveCharacter({
        output: {
          emoji_filter: output.emoji_filter,
          strip_emoji: output.strip_emoji,
          allowed_emoji: output.allowed_emoji.split(/\s+/).filter(Boolean),
          max_lines: Number(output.max_lines),
          max_chars: output.max_chars, language: output.language, style_filter: output.style_filter,
          sentence_breaks: output.sentence_breaks,
        },
      }, bundle?.revision);
      setBundle(res.bundle);
      setOutput(outputDraftOf(res.bundle.output));
      showToast("Hard limits saved", "success");
      return true;
    } catch (e) {
      showToast(errorMessage(e), "error");
      return false;
    } finally {
      writing.current = false;
      setBusy(null);
    }
  };

  const saveSkin = async (name: string) => {
    if (writing.current) return;
    writing.current = true;
    setBusy("skin");
    try {
      const res = await lunaApi.saveCharacter({ skin: name }, bundle?.revision);
      setBundle(res.bundle);
      setSkin(res.bundle.current_skin);
      setSkinColors({ ...res.bundle.skins.find((s) => s.name === res.bundle.current_skin)?.colors });
      showToast(`Skin set: ${name}`, "success");
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      writing.current = false;
      setBusy(null);
    }
  };

  const saveColors = async (): Promise<boolean> => {
    if (!activeSkin || writing.current) return false;
    writing.current = true;
    setBusy("colors");
    try {
      const res = await lunaApi.saveSkinColors(activeSkin.name, skinColors, activeSkin.description);
      setBundle(res.bundle);
      setSkinColors({ ...res.bundle.skins.find((s) => s.name === activeSkin.name)?.colors });
      showToast(`Skin ${activeSkin.name} saved`, "success");
      return true;
    } catch (e) {
      showToast(errorMessage(e), "error");
      return false;
    } finally {
      writing.current = false;
      setBusy(null);
    }
  };

  const toggleSkill = async (name: string, on: boolean) => {
    if (writing.current) return;
    writing.current = true;
    const next = on ? [...autoLoad, name] : autoLoad.filter((n) => n !== name);
    setBusy("skills");
    try {
      const res = await lunaApi.saveCharacter({ auto_load: next }, bundle?.revision);
      setBundle(res.bundle);
      setAutoLoad([...res.bundle.auto_load]);
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      writing.current = false;
      setBusy(null);
    }
  };

  // The persona draft, and the version last loaded from the server. `bundle.soul` is the baseline:
  // `applyBundle` refreshes it on every successful write, so a save (or a preset/import) is what
  // clears the dirty state, not a separate flag that could drift from what is actually on disk.
  const soulDraft = useMemo(
    () => ({ title, intro, sections, footer }),
    [title, intro, sections, footer],
  );
  const soulBaseline = useMemo(
    () =>
      bundle
        ? {
            title: bundle.soul.title,
            intro: bundle.soul.intro,
            sections: bundle.soul.sections.map((s) => ({ ...s })),
            footer: bundle.soul.footer,
          }
        : null,
    [bundle],
  );
  const soulDirty = soulBaseline !== null && isDraftDirty(soulDraft, soulBaseline);

  /** Name of the selected preset, for the confirmation's title. */
  const presetNameOf = (id: string) =>
    bundle?.presets.find((p) => p.id === id)?.name ?? id;

  /** "3 lines" / "1 line", so the confirmation does not read "1 lines". */
  const lineCount = (text: string) => `${countLines(text)} line${countLines(text) === 1 ? "" : "s"}`;

  /** What the persona would be written as right now — the export, and what a preset would replace. */
  const currentSoulText = useMemo(
    () => renderSoul({ title, intro, sections, footer }),
    [title, intro, sections, footer],
  );

  useUnsavedChanges({
    id: "character-soul",
    label: "the persona",
    dirty: soulDirty,
    onSave: saveSoul,
    // Discard = throw the edits away and reload what is on disk. Building the draft from the
    // baseline directly (rather than refetching) keeps Discard synchronous, so the DirtyBar's
    // pending navigation resumes without waiting on the network.
    onDiscard: () => {
      if (soulBaseline) applyBundleToDraft(soulBaseline);
    },
  });

  function applyBundleToDraft(next: {
    title: string;
    intro: string;
    sections: SoulSection[];
    footer: string;
  }) {
    setTitle(next.title);
    setIntro(next.intro);
    setSections(next.sections.map((s) => ({ ...s })));
    setFooter(next.footer);
  }

  const swatches = useMemo(() => {
    const colors = bundle?.skins.find((s) => s.name === skin)?.colors ?? {};
    return Object.entries(colors).slice(0, 12);
  }, [bundle, skin]);

  const activeSkin = useMemo(
    () => bundle?.skins.find((s) => s.name === skin) ?? null,
    [bundle, skin],
  );

  const outputBaseline = bundle ? outputDraftOf(bundle.output) : null;
  const colorsDirty = !!activeSkin && !activeSkin.builtin && isDraftDirty(skinColors, activeSkin.colors);

  useUnsavedChanges({
    id: "character-output",
    label: "hard limits",
    dirty: outputBaseline !== null && isDraftDirty(output, outputBaseline),
    onSave: saveOutput,
    onDiscard: () => { if (outputBaseline) setOutput(outputBaseline); },
  });
  useUnsavedChanges({
    id: "character-colors",
    label: "skin colors",
    dirty: colorsDirty,
    onSave: saveColors,
    onDiscard: () => { if (activeSkin) setSkinColors({ ...activeSkin.colors }); },
  });

  const fileRef = useRef<HTMLInputElement | null>(null);

  /**
   * Download SOUL.md as it currently reads on screen.
   *
   * This used to export `bundle.soul.raw` — the last *saved* text — from a page whose textareas hold
   * the user's unsaved edits. So exporting mid-edit silently discarded that work and handed back the
   * previous file, which is the worst possible outcome for the one action meant to be a backup.
   * Rendering the draft also makes the export round-trip: importing it reproduces what you see.
   */
  const exportSoul = () => {
    const raw = renderSoul({ title, intro, sections, footer });
    const blob = new Blob([raw], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "SOUL.md";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  /**
   * Replace SOUL.md with a file's contents, after confirming.
   *
   * The file is read on click rather than on confirm so the dialog can state what is about to
   * replace what — a line count alone does not tell a user whether they picked the right file.
   */
  const confirmImport = async () => {
    if (!pendingImport || writing.current) return;
    writing.current = true;
    const text = pendingImport.text;
    setBusy("import");
    try {
      const res = await lunaApi.saveCharacter({ soul_text: text }, bundle?.revision);
      setBundle(res.bundle);
      applyBundleToDraft(res.bundle.soul);
      showToast("Persona imported", "success");
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      writing.current = false;
      setBusy(null);
      setPendingImport(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-6">
        <Spinner /> Loading character…
      </div>
    );
  }

  return (
    <fieldset disabled={busy !== null} className="min-w-0 space-y-6 p-4 md:p-6">
      <header className="relative overflow-hidden rounded-3xl border border-border/70 bg-card px-6 py-8 md:px-8 md:py-10">
        <BlossomBranch className="pointer-events-none absolute right-0 top-0 hidden w-80 opacity-40 lg:block" />
        <div className="relative flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl">
            <H2 className="max-w-md text-3xl font-normal lg:text-4xl">Give your companion a voice.</H2>
            <p className="mt-3 max-w-lg text-sm leading-relaxed text-muted-foreground">Shape their personality, set their boundaries, and make a little space in your chats feel like home.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button outlined size="sm" onClick={exportSoul} title="Download persona text as SOUL.md; export settings from Profiles"><Download className="mr-1 h-3.5 w-3.5" /> Export persona</Button>
            <Button outlined size="sm" onClick={() => fileRef.current?.click()} disabled={busy === "import"} title="Replace the persona from a SOUL.md file"><Upload className="mr-1 h-3.5 w-3.5" /> Import persona</Button>
          </div>
        </div>
      </header>

      <nav aria-label="Character settings sections" className="sticky top-0 z-10 -mx-4 flex gap-1 overflow-x-auto border-y border-border bg-background/90 px-4 py-2 backdrop-blur sm:gap-2 md:-mx-6 md:px-6">
        {[["persona", "Persona"], ["boundaries", "Boundaries"], ["appearance", "Appearance"], ["skills", "Skills"]].map(([id, label]) => <a key={id} href={`#character-${id}`} className="shrink-0 rounded-full px-2 py-2 text-sm text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 sm:px-4">{label}</a>)}
      </nav>

      <section id="character-persona" className="scroll-mt-20 space-y-4">
      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="py-3">
          <div className="flex flex-col gap-3 md:flex-row md:items-center">
            <div className="min-w-48"><H2 className="text-base">Start with a voice</H2><p className="mt-1 text-xs text-muted-foreground">Choose a starting point, then make it yours.</p></div>
            <select className={`${inputClass} min-w-48`} value={presetId} onChange={(e) => setPresetId(e.target.value)} aria-label="Persona preset">
              {(bundle?.presets ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              onClick={() => {
                // Applying the persona you already have is not destructive, so it does not earn a
                // confirm — a dialog that fires on a no-op is one people learn to dismiss blindly.
                const incoming = bundle?.presets.find((p) => p.id === presetId)?.content ?? "";
                if (!soulsDiffer(currentSoulText, incoming)) {
                  showToast("That preset is already the active persona", "success");
                  return;
                }
                setPendingPreset({ id: presetId, name: presetNameOf(presetId) });
              }}
              disabled={busy === "preset"}
            >
              Apply preset
            </Button>
            <span className="flex-1 text-sm text-muted-foreground">
              {(bundle?.presets ?? []).find((p) => p.id === presetId)?.description}
            </span>
          </div>
        </CardContent>
      </Card>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(300px,0.85fr)]">
      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <div className="flex flex-wrap items-center gap-2">
            <div className="mr-auto"><H2 className="text-xl">Write their story</H2><p className="mt-1 text-sm text-muted-foreground">The personality and voice they carry into every conversation.</p></div>
            <input
              ref={fileRef}
              type="file"
              accept=".md,text/markdown"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                // Read now so the dialog can name the file and say how much it will replace.
                void file.text().then((text) => setPendingImport({ name: file.name, text }));
              }}
            />
            <Button size="sm" onClick={saveSoul} disabled={busy === "soul"}>
              <Save className="mr-1 h-3.5 w-3.5" /> Save persona
            </Button>
          </div>
          <div className="grid gap-4 pt-5">
            <label className="block text-sm font-medium text-foreground">
              Character name
              <input className={`${inputClass} mt-2 block w-full max-w-sm`} value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label className="block text-sm font-medium text-foreground">
              Who they are (intro)
              <textarea
                className={`${inputClass} mt-2 min-h-32 w-full resize-y leading-relaxed`}
                value={intro}
                onChange={(e) => setIntro(e.target.value)}
              />
            </label>
            {sections.map((section, index) => (
              <SectionCard
                key={`${section.title}-${index}`}
                section={section}
                onChange={(next) => setSections(sections.map((s, i) => (i === index ? next : s)))}
                onRemove={() => setSections(sections.filter((_, i) => i !== index))}
              />
            ))}
            <div>
              <Button outlined
                size="sm"
                onClick={() => setSections([...sections, { title: "New section", body: "" }])}
              >
                <Plus className="mr-1 h-3.5 w-3.5" /> Add section
              </Button>
            </div>
            <label className="block text-sm font-medium text-foreground">
              Closing note
              <input className={`${inputClass} mt-2 block w-full max-w-xl`} value={footer} onChange={(e) => setFooter(e.target.value)} />
            </label>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-2xl border-border shadow-sm xl:sticky xl:top-16">
        <CardContent className="p-5">
          <div className="flex items-start justify-between gap-2">
            <div><H2 className="text-lg">A message, in context</H2><p className="mt-1 text-sm text-muted-foreground">Preview how output rules shape a sample.</p></div>
            <select className={`${inputClass} w-auto`} value={surface} onChange={(e) => setSurface(e.target.value)} aria-label="Preview surface">
              <option value="group">group</option>
              <option value="dm">dm</option>
            </select>
          </div>
          <textarea
            className={`${inputClass} mt-4 min-h-28 w-full resize-y`}
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            aria-label="preview sample"
          />
          <div className="mt-3 rounded-2xl border border-border bg-background/60 p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <Eye className="h-3.5 w-3.5" /> Shaped reply
            </div>
            <div className="mt-2 min-h-16 whitespace-pre-wrap text-sm leading-relaxed">{preview?.output ?? "…"}</div>
            {preview && (
              <div className="pt-1 text-xs text-muted-foreground">{preview.notes.join(" · ")}</div>
            )}
          </div>
        </CardContent>
      </Card>
      </div>
      </section>

      <section id="character-boundaries" className="scroll-mt-20">
      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <H2 className="text-lg">Boundaries in group chats</H2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            These limits are applied to every group reply, alongside the voice you wrote above.
          </p>
          <div className="grid max-w-3xl grid-cols-1 gap-4 pt-5 text-sm sm:grid-cols-2">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={output.emoji_filter}
                onChange={(e) => setOutput({ ...output, emoji_filter: e.target.checked })}
              />
              Keep emoji within the allowed list
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={output.strip_emoji}
                onChange={(e) => setOutput({ ...output, strip_emoji: e.target.checked })}
              />
              Remove all emoji
            </label>
            <label className="block text-sm text-muted-foreground">
              Allowed emoji (space separated)
              <input
                className={`${inputClass} mt-2 w-full`}
                value={output.allowed_emoji}
                onChange={(e) => setOutput({ ...output, allowed_emoji: e.target.value })}
              />
            </label>
            <label className="block text-sm text-muted-foreground">
              Maximum lines per reply
              <input
                className={`${inputClass} mt-2 block w-24`}
                type="number"
                min={1}
                max={50}
                value={output.max_lines}
                onChange={(e) => setOutput({ ...output, max_lines: Number(e.target.value) })}
              />
            </label>
            <label className="block text-sm text-muted-foreground">Group reply size (one message)
              <input className={`${inputClass} mt-2 block w-28`} type="number" min={80} max={3500} value={output.max_chars} onChange={e => setOutput({ ...output, max_chars: Number(e.target.value) })} />
            </label>
            <label className="block text-sm text-muted-foreground">Language
              <select className={`${inputClass} mt-2 block`} value={output.language} onChange={e => setOutput({ ...output, language: e.target.value })}><option value="auto">Any language</option><option value="english">English only</option></select>
            </label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={output.style_filter} onChange={e => setOutput({ ...output, style_filter: e.target.checked })} />Rewrite into casual chat style</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={output.sentence_breaks} onChange={e => setOutput({ ...output, sentence_breaks: e.target.checked })} />Sentence line breaks (with casual chat style)</label>
            <p className="text-xs text-muted-foreground">Turn off to keep periods, semicolons and the model’s line layout. Emoticons, quotes, code and links stay intact when line breaks are on.</p>
          </div>
          <Button size="sm" className="mt-5" onClick={saveOutput} disabled={busy === "output"}>
            Save hard limits
          </Button>
        </CardContent>
      </Card>
      </section>

      <section id="character-appearance" className="scroll-mt-20">
      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <H2 className="text-lg">Appearance</H2>
          <p className="mt-1 text-sm text-muted-foreground">Choose your companion’s chat colors. Use the theme picker in the sidebar to change the dashboard’s appearance.</p>
          <div className="flex flex-wrap gap-2 pt-2">
            {(bundle?.skins ?? []).map((s) => (
              <button
                key={s.name}
                className={`rounded-xl border px-4 py-2.5 text-sm transition-colors ${skin === s.name ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted/60"}`}
                onClick={() => {
                  if (s.name === skin) return;
                  if (colorsDirty) requestLeave(() => void saveSkin(s.name));
                  else void saveSkin(s.name);
                }}
                disabled={busy === "skin"}
              >
                {s.name}
                {skin === s.name && <Badge className="ml-2">active</Badge>}
              </button>
            ))}
          </div>
          {!!swatches.length && (
            <div className="flex gap-1 pt-3" aria-label="Selected palette colors">
              {swatches.map(([key, value]) => (
                <span key={key} className="h-5 w-5 rounded" style={{ background: value }} title={`${key}: ${value}`} />
              ))}
            </div>
          )}
          {activeSkin && !activeSkin.builtin && (
            <div className="pt-4">
              <H2 className="text-base">Edit {activeSkin.name}</H2>
              <p className="text-xs text-muted-foreground">
                Colors you leave out are inherited from the built-in default skin.
              </p>
              <div className="grid max-w-2xl grid-cols-1 gap-2 pt-2">
                {Object.entries(skinColors).map(([key, value]) => (
                  <div key={key} className="flex flex-wrap items-center gap-2 text-sm sm:flex-nowrap">
                    <span className="w-full shrink-0 font-mono text-xs sm:w-48">{key}</span>
                    <input
                      type="color"
                      className="h-8 w-10 cursor-pointer rounded border bg-transparent"
                      value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : "#000000"}
                      onChange={(e) => setSkinColors({ ...skinColors, [key]: e.target.value })}
                      aria-label={`${key} color`}
                    />
                    <input
                className={`${inputClass} w-40 font-mono`}
                      value={value}
                      onChange={(e) => setSkinColors({ ...skinColors, [key]: e.target.value })}
                    />
                  </div>
                ))}
              </div>
              <Button size="sm" className="mt-3" onClick={saveColors} disabled={busy === "colors"}>
                Save skin
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      </section>

      <section id="character-skills" className="scroll-mt-20">
      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <H2 className="text-lg">Skills</H2>
          <p className="mt-1 text-sm text-muted-foreground">
            Turn on the skills your character should have ready in each conversation.
          </p>
          <div className="grid grid-cols-1 gap-2 pt-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
            {(bundle?.skills ?? []).map((s) => (
              <label key={s.name} className="flex min-w-0 items-center gap-3 rounded-xl border border-border p-3">
                <input
                  type="checkbox"
                  checked={autoLoad.includes(s.name)}
                  onChange={(e) => toggleSkill(s.name, e.target.checked)}
                  disabled={busy === "skills"}
                />
                <span className="font-mono text-xs">{s.name}</span>
                <span className="text-xs text-muted-foreground">{s.category}</span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>
      </section>

      {/* B3: both actions replace SOUL.md wholesale, server-side. The description states what is
          about to be replaced rather than just asking "are you sure", because the question the user
          actually has is "with what, and over what" — a bare confirm on a persona file is a coin
          flip. Import names the file and both line counts; the preview shows the two openings, which
          is where a wrong-file pick is visible. */}
      <ConfirmDialog
        open={pendingPreset !== null}
        onCancel={() => setPendingPreset(null)}
        onConfirm={() => pendingPreset && void applyPreset(pendingPreset.id)}
        loading={busy === "preset"}
        destructive
        title={`Replace the persona with "${pendingPreset?.name ?? ""}"?`}
        confirmLabel="Replace persona"
        description={[
          `${lineCount(currentSoulText)} of your current SOUL.md will be overwritten. This cannot be undone.`,
          soulDirty
            ? "You have unsaved persona edits. Export first if you want to keep them."
            : null,
        ]
          .filter(Boolean)
          .join(" ")}
      />

      <ConfirmDialog
        open={pendingImport !== null}
        onCancel={() => setPendingImport(null)}
        onConfirm={() => void confirmImport()}
        loading={busy === "import"}
        destructive
        title="Replace the persona from this file?"
        confirmLabel="Replace persona"
        description={[
          `${pendingImport?.name ?? ""} — ${lineCount(pendingImport?.text ?? "")} will overwrite your current SOUL.md (${lineCount(currentSoulText)}). This cannot be undone.`,
          soulDirty ? "You have unsaved persona edits. Export first if you want to keep them." : null,
        ]
          .filter(Boolean)
          .join(" ")}
      />

      {(pendingPreset || pendingImport) && (
        <div
          className="rounded border bg-muted/40 p-3 font-mono text-xs"
          data-soul-preview
          aria-label="persona preview"
        >
          <div className="mb-1 font-sans font-semibold">incoming</div>
          {soulPreview(
            pendingImport?.text ?? bundle?.presets.find((p) => p.id === pendingPreset?.id)?.content ?? "",
          ).map((line, i) => (
            <div key={i} className="truncate">
              {line || "\u00a0"}
            </div>
          ))}
          <div className="mb-1 mt-3 font-sans font-semibold">current</div>
          {soulPreview(currentSoulText).map((line, i) => (
            <div key={i} className="truncate text-muted-foreground">
              {line || "\u00a0"}
            </div>
          ))}
        </div>
      )}

      <Toast toast={toast} />
    </fieldset>
  );
}
