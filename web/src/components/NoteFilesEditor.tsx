import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Check, FileText, RefreshCw, Save, Users } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { noteFilesApi, type NoteFile, type NoteFileInfo } from "@/lib/note-files-api";
import { errorMessage } from "@/lib/api-error";
import { useUnsavedChanges } from "@/hooks/useUnsavedChanges";

export function NoteFilesEditor() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("file") || "memory";
  const [files, setFiles] = useState<NoteFileInfo[]>([]);
  const [file, setFile] = useState<NoteFile | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const generation = useRef(0);
  const dirty = file !== null && draft !== file.content;
  const load = useCallback(async () => {
    const version = ++generation.current;
    setLoading(true); setFile(null); setError(""); setSaved(false);
    try {
      const [catalog, next] = await Promise.all([noteFilesApi.list(), noteFilesApi.read(selected)]);
      if (version !== generation.current) return;
      setFiles(catalog.files); setFile(next); setDraft(next.content);
    } catch (e) {
      if (version === generation.current) setError(errorMessage(e));
    } finally {
      if (version === generation.current) setLoading(false);
    }
  }, [selected]);
  useEffect(() => { void load(); return () => { generation.current++; }; }, [load]);
  const save = async () => {
    if (!file || loading) return false;
    setSaving(true); setError(""); setSaved(false);
    try {
      const next = await noteFilesApi.save(file.id, draft, file.revision);
      setFile(next); setDraft(next.content); setSaved(true); return true;
    } catch (e) { setError(errorMessage(e)); return false; }
    finally { setSaving(false); }
  };
  useUnsavedChanges({ id: "note-file", label: file?.name || "note file", dirty, onSave: save,
    onDiscard: () => { setDraft(file?.content || ""); setError(""); } });
  return <section aria-label="Note files" className="space-y-4">
    <div><h2 className="font-display text-2xl font-normal">Edit your companion’s notes</h2>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">Open a file, edit its Markdown, and save. These are the same files your companion reads and maintains.</p></div>
    <div className="grid overflow-hidden rounded-panel border border-border bg-card lg:grid-cols-[15rem_minmax(0,1fr)]">
      <nav aria-label="Choose a note file" className="border-b border-border bg-muted/20 p-3 lg:border-b-0 lg:border-r">
        {([false, true] as const).map(groups => <div key={String(groups)} className="mb-3 space-y-1">
          <p className="px-3 py-2 text-xs font-medium text-muted-foreground">{groups ? "Group notes" : "Your files"}</p>
          {files.filter(item => item.id.startsWith("group-") === groups).map(item => {
            const Icon = item.kind === "people" ? Users : item.id === "user" ? FileText : BookOpen;
            return <button key={item.id} disabled={loading || saving || dirty} aria-current={selected === item.id ? "page" : undefined}
              onClick={() => setParams(current => { const next = new URLSearchParams(current); next.set("file", item.id); next.delete("tab"); return next; })}
              className={`flex w-full items-start gap-3 rounded-control px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 ${selected === item.id ? "bg-primary/10 text-primary" : "hover:bg-muted/50"}`}>
              <Icon className="mt-0.5 h-4 w-4 shrink-0" /><span className="min-w-0"><span className="block text-sm font-medium">{item.name}</span><span className="mt-1 block truncate text-xs text-muted-foreground">{item.scope}</span></span>
            </button>;
          })}
          {groups && files.length > 0 && !files.some(item => item.id.startsWith("group-")) && <p className="px-3 text-xs text-muted-foreground">Groups appear after your companion observes them.</p>}
        </div>)}
      </nav>
      <div className="min-w-0 p-4 md:p-6" aria-busy={loading || saving}>
        {error && <div role="alert" className="mb-4 rounded-control border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}
        {loading && <p role="status" className="flex items-center gap-2 py-8 text-sm"><Spinner />Loading file…</p>}
        {!loading && file && <>
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><h3 id="note-file-title" className="text-lg font-semibold">{file.name}</h3><p className="mt-1 text-sm text-muted-foreground">{file.scope}</p></div>
            <Button outlined size="sm" disabled={saving || dirty} onClick={() => void load()}><RefreshCw className="mr-2 h-3.5 w-3.5" />Reload saved file</Button></div>
          <p className="mb-4 max-w-3xl text-sm leading-relaxed text-muted-foreground">{file.description}</p>
          {file.kind === "people" && <p className="mb-4 text-xs leading-relaxed text-muted-foreground">Keep each person under their existing heading. Fields are Name, Aliases (a JSON list), Pronouns and Role. <Link to="/people" className="text-primary underline">Use the People form</Link> to edit one person at a time.</p>}
          <textarea aria-label={`Edit ${file.name}`} aria-describedby="note-file-help" spellCheck={false} disabled={saving}
            className="min-h-[26rem] w-full resize-y rounded-control border border-input bg-background px-4 py-3 font-mono text-sm leading-relaxed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            value={draft} onChange={event => { setDraft(event.target.value); setSaved(false); }} />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-muted-foreground">{draft.length.toLocaleString()} characters{file.kind === "notes" ? ` · ${file.limit.toLocaleString()} limit` : ""}{!file.enabled ? " · Automatic use is off" : ""}</p>
            <div className="flex gap-2"><Button outlined size="sm" disabled={saving || !dirty} onClick={() => { setDraft(file.content); setError(""); setSaved(false); }}>Discard changes</Button>
              <Button size="sm" disabled={saving || !dirty} onClick={() => void save()}><Save className="mr-2 h-3.5 w-3.5" />{saving ? "Saving…" : `Save ${file.name}`}</Button></div></div>
          <p id="note-file-help" className="mt-4 text-xs leading-relaxed text-muted-foreground">{file.kind === "people" ? "Group and DM headings keep each entry in its conversation. Your next turn reads saved people changes." : file.id.startsWith("group-") ? "Saved group notes are read on the next turn in that room." : "Private file changes are loaded when you start a new conversation."}{file.kind === "notes" && " A line containing § separates notes; keep it when editing several saved entries."}</p>
          {saved && <p role="status" className="mt-3 flex items-center gap-2 text-sm text-success"><Check className="h-4 w-4" />{file.name} saved.</p>}
        </>}
        {!loading && !file && <Button outlined size="sm" onClick={() => void load()}>Retry loading files</Button>}
      </div>
    </div>
  </section>;
}
