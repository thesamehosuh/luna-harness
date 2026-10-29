import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { BookOpen, Check, ChevronRight, LockKeyhole, MessagesSquare, Pencil, RefreshCw, Search, Users } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { H2 } from "@/components/ui/h2";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { groupsApi, type GroupBundle, type GroupPerson } from "@/lib/groups-api";
import { errorMessage } from "@/lib/api-error";
import { useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import { usePageHeader } from "@/contexts/usePageHeader";

const inputClass = "w-full rounded-control border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export default function GroupsPage() {
  const [params, setParams] = useSearchParams();
  const [bundle, setBundle] = useState<GroupBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [notes, setNotes] = useState("");
  const [noteBaseline, setNoteBaseline] = useState("");
  const [noteRevision, setNoteRevision] = useState("");
  const [editing, setEditing] = useState<GroupPerson | null>(null);
  const editForm = useRef<HTMLDivElement>(null);
  const editingOpen = editing !== null;
  useEffect(() => { if (editingOpen) editForm.current?.querySelector<HTMLInputElement>('input')?.focus(); }, [editingOpen]);
  const [aliases, setAliases] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");
  const active = params.get("group") || "";
  const generation = useRef(0);
  const { setEnd } = usePageHeader();
  const group = bundle?.group;
  const noteEntries = useMemo(() => notes.split(/\n\s*\n/).map(note => note.trim()).filter(Boolean), [notes]);
  const dirty = !!group && notes !== noteBaseline;
  const load = useCallback(async () => {
    const version = ++generation.current;
    setLoading(true); setError("");
    try {
      const data = active ? await groupsApi.get(active) : await groupsApi.list();
      if (version !== generation.current) return;
      if (!active && data.groups.length) { setParams({ group: data.groups[0].id }, { replace: true }); return; }
      const text = data.group?.notes.entries.join("\n\n") || "";
      setBundle(data); setNotes(text); setNoteBaseline(text); setNoteRevision(data.group?.notes.revision || ""); setEditing(null);
    } catch (e) { if (version === generation.current) setError(errorMessage(e)); }
    finally { if (version === generation.current) setLoading(false); }
  }, [active, setParams]);
  useEffect(() => { void load(); return () => { generation.current++; }; }, [load]);
  const saveNotes = async () => {
    if (!group) return false;
    setBusy(true); setError(""); setSaved("");
    try {
      const data = await groupsApi.saveNotes(group.id, noteEntries, noteRevision);
      const text = data.group?.notes.entries.join("\n\n") || "";
      setBundle(data); setNotes(text); setNoteBaseline(text); setNoteRevision(data.group?.notes.revision || ""); setSaved("Group notes saved. The next group turn reads the updated notes."); return true;
    } catch (e) { setError(errorMessage(e)); return false; }
    finally { setBusy(false); }
  };
  useUnsavedChanges({ id: "group-memory", label: "group notes", dirty, onSave: saveNotes,
    onDiscard: () => setNotes(noteBaseline) });
  useEffect(() => {
    setEnd(<Button outlined size="sm" onClick={() => void load()} disabled={busy || loading || dirty || !!editing}><RefreshCw className="mr-2 h-3.5 w-3.5" />Refresh</Button>);
    return () => setEnd(null);
  }, [load, setEnd, busy, loading, dirty, editing]);
  const savePerson = async (inherit = false) => {
    if (!group || !editing) return false;
    setBusy(true); setError(""); setSaved("");
    try {
      const data = await groupsApi.savePerson(group.id, editing.user_id,
        { display_name: editing.display_name, pronouns: editing.pronouns, role: editing.role,
          aliases: aliases.split(",").map(alias => alias.trim()).filter(Boolean) }, editing.revision, inherit);
      // A person update must never erase an unsaved note draft.
      setBundle(data); setEditing(null); setSaved(inherit ? "This member now uses shared basic details." : "Group entry saved.");
      if (!dirty) {
        const text = data.group?.notes.entries.join("\n\n") || "";
        setNotes(text); setNoteBaseline(text); setNoteRevision(data.group?.notes.revision || "");
      }
      return true;
    } catch (e) { setError(errorMessage(e)); return false; }
    finally { setBusy(false); }
  };
  useUnsavedChanges({ id: "group-person", label: "group person entry", dirty: !!editing,
    onSave: () => savePerson(), onDiscard: () => setEditing(null) });
  const groups = (bundle?.groups || []).filter(item => `${item.name} ${item.chat_id}`.toLowerCase().includes(query.toLowerCase()));
  const policy = bundle?.policy;
  return <div className="space-y-6 p-4 md:p-6">
    <header className="flex max-w-3xl items-start gap-4 py-2">
      <MessagesSquare className="mt-2 hidden h-7 w-7 shrink-0 text-primary sm:block" />
      <div><H2 className="font-display text-3xl font-normal md:text-4xl">Every room has its own story.</H2>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">Keep the people and knowledge of each group together. Your owner DM can look them up when needed.</p></div>
    </header>
    {error && <p role="alert" className="rounded-control border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {saved && <p role="status" className="flex items-center gap-2 text-sm text-success"><Check className="h-4 w-4" />{saved}</p>}
    {!bundle && loading ? <div className="flex gap-2 py-8 text-sm"><Spinner />Loading groups…</div> : null}
    {bundle && !bundle.groups.length && <div className="rounded-panel border border-dashed border-border p-8">
      <H2 className="text-lg">Bring your companion into a group.</H2><p className="mt-2 max-w-xl text-sm text-muted-foreground">Connected and observed groups appear here. Set up Telegram in Channels, then mention your companion in the room.</p>
      <Link to="/channels" className="mt-4 inline-block text-sm text-primary underline">Open Channels</Link>
    </div>}
    {!!bundle?.groups.length && <div className="grid overflow-hidden rounded-panel border border-border bg-card lg:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="border-b border-border bg-muted/20 p-4 lg:border-b-0 lg:border-r" aria-label="Your groups">
        <label className="relative block"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input className={inputClass + " pl-9"} placeholder="Find a group" aria-label="Find a group" value={query} onChange={event => setQuery(event.target.value)} /></label>
        <div className="mt-3 flex gap-2 overflow-x-auto lg:block lg:space-y-1">{groups.map(item => <button key={item.id} disabled={busy || loading || dirty || !!editing}
          onClick={() => { setSaved(""); setParams({ group: item.id }); }} aria-current={active === item.id ? "page" : undefined}
          className={`flex min-w-44 items-center justify-between gap-3 rounded-control px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 lg:w-full ${active === item.id ? "bg-primary/10 text-primary" : "hover:bg-muted/50"}`}>
          <span className="min-w-0"><span className="block truncate text-sm font-medium">{item.name}</span><span className="mt-1 block text-xs text-muted-foreground">{item.members ?? 0} people{item.thread_id ? " · Topic" : ""}</span></span>
          {active === item.id && <ChevronRight className="h-4 w-4 shrink-0" />}
        </button>)}</div>
        {!groups.length && <p className="mt-4 text-sm text-muted-foreground">No matching groups.</p>}
      </aside>
      <main className="min-w-0" aria-busy={loading}>
        {group && <>
          <div className="border-b border-border px-5 py-5 md:px-7"><div className="flex flex-wrap items-center justify-between gap-3"><div><H2 className="text-xl">{group.name}</H2><p className="mt-1 text-xs text-muted-foreground">{group.platform} · {group.chat_id}{group.thread_id ? ` · Topic ${group.thread_id}` : ""}</p></div>
            <Link to={`/people?group=${group.id}`} className="text-sm text-primary underline">View this group in People</Link></div>
            <div className="mt-4 flex flex-wrap gap-2"><Badge>{policy?.notes_enabled ? "Group notes on" : "Group notes off"}</Badge><Badge tone="outline">{policy?.people_enabled ? "People maintenance on" : "People maintenance off"}</Badge><Badge tone={policy?.owner_configured ? "success" : "warning"}>{policy?.owner_configured ? "Private reads need owner-DM approval" : "Set up an owner for private-read approvals"}</Badge></div>
          </div>
          <div className="grid xl:grid-cols-[minmax(0,1.2fr)_minmax(18rem,1fr)]">
            <section className="space-y-4 p-5 md:p-7 xl:border-r xl:border-border" aria-labelledby="group-notes-title">
              <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-primary" /><h3 id="group-notes-title" className="text-base font-semibold">Group memory</h3></div><Link to={`/memory?file=group-${group.id}`} className="text-xs text-primary underline">Edit MEMORY.md</Link></div>
              <p className="text-sm leading-relaxed text-muted-foreground">Shared interests, plans and room conventions. Keep one durable note per paragraph. Names and aliases belong in People.</p>
              <textarea className={inputClass + " min-h-72 resize-y leading-relaxed"} aria-label="Group memory notes" value={notes} disabled={busy || loading} onChange={event => { setNotes(event.target.value); setSaved(""); }} placeholder="What should your companion remember about this room?" />
              <div className="flex flex-wrap items-center justify-between gap-3"><span className={`text-xs ${noteEntries.join("\n§\n").length > (policy?.note_limit || 2200) ? "text-destructive" : "text-muted-foreground"}`}>{noteEntries.join("\n§\n").length.toLocaleString()} / {(policy?.note_limit || 2200).toLocaleString()} characters</span>
                <Button size="sm" onClick={() => void saveNotes()} disabled={busy || loading || !dirty || noteEntries.join("\n§\n").length > (policy?.note_limit || 2200)}>Save group notes</Button></div>
              <p className="text-xs leading-relaxed text-muted-foreground">{policy?.reviews_enabled && policy.notes_enabled && policy.review_interval > 0 ? `The companion reviews these files every ${policy.review_interval} conversation turns.` : "Automatic note reviews are off."} {policy?.write_approval ? "Agent updates require approval." : "The companion can update and consolidate these files without approval."} <Link to="/memory?tab=settings" className="text-primary underline">Change shared memory controls</Link></p>
              <div className="flex gap-3 border-t border-border pt-4 text-xs leading-relaxed text-muted-foreground"><LockKeyhole className="mt-0.5 h-4 w-4 shrink-0" /><p>Your private USER.md and MEMORY.md are available through owner-approved reads. A request from this group sends the exact excerpt to your DM for one-read approval. Reads in your owner DM are approval-free.</p></div>
            </section>
            <section className="border-t border-border p-5 md:p-7 xl:border-t-0" aria-labelledby="group-people-title">
              <div className="mb-4 flex items-center gap-2"><Users className="h-4 w-4 text-primary" /><h3 id="group-people-title" className="text-base font-semibold">People in this room</h3></div>
              <p className="mb-4 text-xs leading-relaxed text-muted-foreground">One person keeps the same identity across groups. The name and role saved here apply in this room.</p>
              <div className="divide-y divide-border">{group.people.map(person => <div key={person.user_id} className="flex items-start justify-between gap-2 py-3">
                <div className="min-w-0"><p className="truncate text-sm font-medium">{person.display_name || "Unnamed person"}{person.pronouns && <span className="ml-2 font-normal text-muted-foreground">{person.pronouns}</span>}</p><p className="mt-1 text-xs text-muted-foreground">{person.role || (person.overridden ? "Group entry" : "Shared basic details")}</p></div>
                <Button ghost size="sm" aria-label={`Edit ${person.display_name || person.user_id} in this group`} disabled={busy || loading || !!editing} onClick={() => { setEditing({ ...person }); setAliases(person.aliases.join(", ")); }}><Pencil className="mr-1 h-3.5 w-3.5" />Edit</Button>
              </div>)}</div>
              {!group.people.length && <p className="rounded-control border border-dashed border-border p-4 text-sm text-muted-foreground">Members appear after your companion observes their group messages.</p>}
              {editing && <div ref={editForm} className="mt-4 space-y-3 rounded-control border border-primary/30 bg-primary/5 p-4">
                <p className="text-sm font-medium">Edit this group's entry</p>
                {([['display_name', 'Name', 80], ['pronouns', 'Pronouns', 40], ['role', 'Short role in this group', 120]] as const).map(([key, label, limit]) => <label key={key} className="block space-y-1 text-xs"><span>{label}</span><input className={inputClass} maxLength={limit} value={editing[key]} onChange={event => setEditing({ ...editing, [key]: event.target.value })} /></label>)}
                <label className="block space-y-1 text-xs"><span>Aliases, separated by commas</span><input className={inputClass} value={aliases} onChange={event => setAliases(event.target.value)} /></label>
                <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy || loading} onClick={() => void savePerson()}>Save group entry</Button><Button outlined size="sm" disabled={busy || loading} onClick={() => setEditing(null)}>Cancel</Button></div>
                {editing.overridden && <button className="text-xs text-primary underline" disabled={busy || loading} onClick={() => void savePerson(true)}>Use shared basic details</button>}
              </div>}
            </section>
          </div>
        </>}
      </main>
    </div>}
  </div>;
}
