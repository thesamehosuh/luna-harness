import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { lunaApi, type CharacterBundle } from "@/lib/luna-api";
import { errorMessage } from "@/lib/api-error";
import { isDraftDirty, useUnsavedChanges, useUnsavedChangesGuard } from "@/hooks/useUnsavedChanges";

/** Chat styling is a preference, independent of the character/persona draft. */
export default function AppearanceSettings() {
  const [bundle, setBundle] = useState<CharacterBundle | null>(null);
  const [colors, setColors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const writing = useRef(false);
  const { requestLeave } = useUnsavedChangesGuard();
  const adopt = useCallback((next: CharacterBundle) => {
    setBundle(next);
    setColors({ ...next.skins.find(skin => skin.name === next.current_skin)?.colors });
  }, []);
  useEffect(() => {
    let disposed = false;
    lunaApi.getCharacter().then(next => { if (!disposed) adopt(next); }).catch(reason => { if (!disposed) setError(errorMessage(reason)); });
    return () => { disposed = true; };
  }, [adopt]);
  const active = bundle?.skins.find(skin => skin.name === bundle.current_skin);
  const dirty = !!active && !active.builtin && isDraftDirty(colors, active.colors);
  const save = async () => {
    if (!active || writing.current) return false;
    writing.current = true; setBusy(true); setError("");
    try { adopt((await lunaApi.saveSkinColors(active.name, colors, active.description)).bundle); setSaved(true); return true; }
    catch (reason) { setError(errorMessage(reason)); return false; }
    finally { writing.current = false; setBusy(false); }
  };
  useUnsavedChanges({ id: "chat-colors", label: "chat colors", dirty, onSave: save, onDiscard: () => setColors({ ...active?.colors }) });
  const select = async (name: string) => {
    if (writing.current) return;
    writing.current = true; setBusy(true); setError(""); setSaved(false);
    try { adopt((await lunaApi.saveCharacter({ skin: name }, bundle?.revision)).bundle); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { writing.current = false; setBusy(false); }
  };
  return <section className="control-section">
    <h2 className="text-lg font-semibold">Chat appearance</h2>
    <p className="mt-2 text-sm leading-7 text-muted-foreground">Choose a palette for the conversation. New chats use the selected palette.</p>
    {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
    {!bundle && !error && <p role="status" className="mt-3 text-sm text-muted-foreground">Loading palettes…</p>}
    <fieldset disabled={busy} className="mt-4 space-y-5">
      <div className="flex flex-wrap gap-2">{bundle?.skins.map(skin => <Button key={skin.name} outlined aria-pressed={active?.name === skin.name} className={active?.name === skin.name ? "border-primary bg-primary/10 text-primary" : ""} onClick={() => {
        if (skin.name === active?.name) return;
        if (dirty) requestLeave(() => void select(skin.name)); else void select(skin.name);
      }}>{skin.name}</Button>)}</div>
      <div className="flex flex-wrap gap-1.5" aria-label="Selected palette colors">{Object.entries(colors).slice(0, 12).map(([key, value]) => <span key={key} className="size-5 rounded" style={{ background: value }} title={key.replaceAll("_", " ")} />)}</div>
      {active && !active.builtin && <details>
        <summary className="cursor-pointer rounded-control py-2 text-sm text-muted-foreground hover:text-foreground">Advanced color editor</summary>
        <p className="my-3 text-xs text-muted-foreground">Adjust individual chat colors. Omitted colors inherit from the default palette.</p>
        <div className="grid gap-3 sm:grid-cols-2">{Object.entries(colors).map(([key, value]) => <label key={key} className="flex min-w-0 items-center gap-3 rounded-control border border-border px-3 py-2">
          <input type="color" aria-label={`${key} color`} className="size-8 shrink-0 cursor-pointer rounded border-0 bg-transparent" value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : "#000000"} onChange={event => { setColors(previous => ({ ...previous, [key]: event.target.value })); setSaved(false); }} />
          <span className="min-w-0 flex-1 text-xs capitalize">{key.replaceAll("_", " ")}</span>
          <Input aria-label={`${key} value`} className="h-8 w-24 px-2 font-mono text-xs" value={value} onChange={event => { setColors(previous => ({ ...previous, [key]: event.target.value })); setSaved(false); }} />
        </label>)}</div>
        <Button className="mt-4" disabled={!dirty || busy} onClick={() => void save()}>Save chat colors</Button>
      </details>}
    </fieldset>
    {saved && <p role="status" className="mt-4 text-sm text-success">Chat colors saved.</p>}
  </section>;
}
