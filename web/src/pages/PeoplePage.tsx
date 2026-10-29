import { useCallback, useEffect, useRef, useState } from "react";
import { GitMerge, RefreshCw, Save, Search } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { groupsApi, type PeopleScopes } from "@/lib/groups-api";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/ui/h2";
import { Card, CardContent } from "@/components/ui/Card";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useUnsavedChanges } from "@/hooks/useUnsavedChanges";
import { errorMessage } from "@/lib/api-error";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { BlossomBranch } from "@/components/BlossomBranch";
import {
  lunaApi,
  type AuditResponse,
  type IdentityRow,
} from "@/lib/luna-api";

interface EditState {
  platform: string;
  user_id: string;
  display_name: string;
  pronouns: string;
  role: string;
  aliases: string;
  group_id?: string;
  revision?: string;
}

function toEdit(row: IdentityRow): EditState {
  return {
    platform: row.platform,
    user_id: row.user_id,
    display_name: row.display_name ?? "",
    pronouns: row.pronouns ?? "",
    role: row.role ?? "",
    aliases: (row.aliases ?? []).join(", "),
  };
}

function emptyEdit(): EditState {
  return { platform: "telegram", user_id: "", display_name: "", pronouns: "", role: "", aliases: "" };
}

function AuditPanel({ audit }: { audit: AuditResponse }) {
  return (
    <Card className="rounded-2xl border-border shadow-sm">
      <CardContent className="p-5 md:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <H2 className="text-base">Identity check</H2>
          {audit.ok ? (
            <Badge>Attribution looks good</Badge>
          ) : (
            <Badge tone="destructive">
              {audit.unmapped.length} members need mapping · {audit.colliding.length} ID conflicts
            </Badge>
          )}
        </div>
        {!!audit.unmapped.length && (
          <div className="mt-2">
            <div className="text-sm font-medium">Room members without a saved profile</div>
            <ul className="text-sm">
              {audit.unmapped.map((row, i) => (
                <li key={i} className="text-muted-foreground">
                  <code>{String(row.user_id)}</code>
                  {row.user_name ? ` (${String(row.user_name)})` : ""},{" "}
                  {String(row.n)} messages in {String(row.chat_id)}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!!audit.colliding.length && (
          <div className="mt-2">
            <div className="text-sm font-medium">IDs currently sharing a profile</div>
            <ul className="text-sm">
              {audit.colliding.map((row, i) => (
                <li key={i} className="text-muted-foreground">
                  <code>{String(row.peer_id)}</code> ← {String(row.user_ids)}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!!audit.orphans.length && (
          <div className="mt-2 text-xs text-muted-foreground">
            {audit.orphans.length} registered member(s) have no message history yet (usually fine).
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function PeoplePage() {
  const [params, setParams] = useSearchParams();
  const selectedGroup = params.get("group") || "";
  const [scopes, setScopes] = useState<PeopleScopes | null>(null);
  const [query, setQuery] = useState("");
  const [identities, setIdentities] = useState<IdentityRow[]>([]);
  const [audit, setAudit] = useState<AuditResponse | null>(null);
  const [directory, setDirectory] = useState<{ text: string; count: number } | null>(null);
  const [directoryError, setDirectoryError] = useState("");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<EditState | null>(null);
  const editHeading = useRef<HTMLDivElement>(null);
  const editingOpen = editing !== null;
  useEffect(() => {
    if (editingOpen) editHeading.current?.querySelector<HTMLInputElement>('input:not(:disabled)')?.focus();
  }, [editingOpen]);
  const [merge, setMerge] = useState({ primary: "", alt: "" });
  // B3: merging rewrites the identity registry — the alt row is absorbed and deleted. The UI said
  // "Fold a second runtime id into the primary", which reads like bookkeeping and does not say that.
  const [confirmMerge, setConfirmMerge] = useState<{ primary: string; alt: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  const load = useCallback(async () => {
    try {
      setDirectoryError("");
      const [list, report, local, scoped] = await Promise.all([lunaApi.getIdentity(), lunaApi.getAudit(), lunaApi.getPeopleDirectory().catch(e => { setDirectoryError(errorMessage(e)); return null; }), groupsApi.people()]);
      setIdentities(list.identities);
      setAudit(report);
      setDirectory(local);
      setScopes(scoped);
    } catch (e) {
      showToast(`Could not load people: ${errorMessage(e)}`, "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setEnd(
      <Button outlined size="sm" onClick={load} disabled={!!editing || busy !== null}>
        <RefreshCw className="mr-1 h-3.5 w-3.5" /> Refresh
      </Button>,
    );
    return () => setEnd(null);
  }, [load, setEnd, editing, busy]);

  const saveIdentity = async () => {
    if (!editing) return false;
    if (!editing.user_id.trim()) {
      showToast("A runtime user id is required", "error");
      return false;
    }
    setBusy(`save:${editing.platform}:${editing.user_id}`);
    try {
      const values = {
        display_name: editing.display_name.trim(), pronouns: editing.pronouns.trim(), role: editing.role.trim(),
        aliases: editing.aliases.split(",").map(alias => alias.trim()).filter(Boolean),
      };
      if (editing.group_id) {
        await groupsApi.savePerson(editing.group_id, editing.user_id, values, editing.revision || "");
      } else await lunaApi.upsertIdentity({
        platform: editing.platform,
        user_id: editing.user_id.trim(),
        display_name: editing.display_name.trim() || null,
        pronouns: editing.pronouns.trim() || null,
        role: editing.role.trim() || null,
        aliases: editing.aliases
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
      });
      showToast(editing.group_id ? "Group entry saved" : "Shared basic details saved", "success");
      setEditing(null);
      await load();
      return true;
    } catch (e) {
      showToast(errorMessage(e), "error");
      return false;
    } finally {
      setBusy(null);
    }
  };
  useUnsavedChanges({ id: "person-entry", label: "person details", dirty: !!editing,
    onSave: saveIdentity, onDiscard: () => setEditing(null) });

  const runMerge = async () => {
    if (!merge.primary.trim() || !merge.alt.trim()) {
      showToast("Both runtime user ids are required", "error");
      return;
    }
    setBusy("merge");
    try {
      await lunaApi.mergeIdentity(confirmMerge!.primary, confirmMerge!.alt);
      showToast("Identities merged", "success");
      setMerge({ primary: "", alt: "" });
      await load();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setBusy(null);
      setConfirmMerge(null);
    }
  };

  const runSync = async () => {
    setBusy("sync");
    try {
      const res = await lunaApi.syncPeers();
      const roomError = res.room && typeof res.room.error === "string" ? res.room.error : null;
      showToast(
        roomError
          ? `Aliases written: ${res.aliases_written}; Honcho: ${roomError}`
          : `Aliases written: ${res.aliases_written}; room peers synced`,
        roomError ? "error" : "success",
      );
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setBusy(null);
    }
  };

  const group = scopes?.groups.find(item => item.id === selectedGroup);
  const personScope = (row: IdentityRow) => scopes?.people.find(person => person.platform === row.platform && person.user_id === row.user_id);
  const facts = (row: IdentityRow) => {
    const person = personScope(row);
    return selectedGroup ? person?.groups.find(item => item.id === selectedGroup)?.entry : person?.shared;
  };
  const visible = identities.filter(row => (!selectedGroup || !!facts(row)) &&
    `${(facts(row)?.display_name ?? row.display_name ?? "")} ${(facts(row)?.aliases || row.aliases || []).join(" ")} ${(facts(row)?.role ?? row.role ?? "")} ${row.user_id}`.toLowerCase().includes(query.toLowerCase()));
  const editPerson = (row: IdentityRow) => {
    const entry = facts(row);
    setEditing({ ...toEdit(row), ...(entry ? { display_name: entry.display_name, pronouns: entry.pronouns, role: entry.role, aliases: entry.aliases.join(", ") } : {}),
      group_id: selectedGroup || undefined, revision: entry?.revision });
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-6">
        <Spinner /> Loading people…
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <header className="relative overflow-hidden rounded-3xl border border-border/70 bg-card px-6 py-8 md:px-8 md:py-10">
        <BlossomBranch className="pointer-events-none absolute right-0 top-0 hidden w-80 opacity-40 lg:block" />
        <div className="relative max-w-3xl">
          <H2 className="max-w-xl text-3xl font-normal lg:text-4xl">One person. A place in every room.</H2>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">Keep shared basic details in one directory. Choose a group to see the names, aliases and roles your companion uses there.</p>
        </div>
      </header>

      <Card className="rounded-2xl border-border shadow-sm">
        <CardContent className="p-5 md:p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1"><H2 className="text-lg">{group ? `People in ${group.name}` : "Shared basic details"}</H2><p className="mt-1 text-sm text-muted-foreground">{group ? "Group entries apply in this room. Shared basics remain available elsewhere." : "Names, pronouns and aliases stay tied to verified platform IDs across rooms."}</p></div>
            <div className="flex flex-wrap gap-2 sm:shrink-0">
              <Link to="/memory?file=people" className="inline-flex items-center rounded-control border border-border px-3 py-2 text-sm font-medium hover:bg-muted/50">Edit PEOPLE.md</Link>
              {group && <Link to={`/groups?group=${group.id}`} className="self-center text-sm text-primary underline">Open group memory</Link>}
              {!selectedGroup && <Button size="sm" onClick={() => setEditing(emptyEdit())} disabled={!!editing || busy !== null}>
                Add person
              </Button>}
            </div>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,auto)]">
            <label className="relative"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input className="w-full rounded-control border border-input bg-background py-2 pl-9 pr-3 text-sm" placeholder="Find a name, alias or role" aria-label="Find a person" value={query} onChange={event => setQuery(event.target.value)} /></label>
            <select className="rounded-control border border-input bg-background px-3 py-2 text-sm" aria-label="People directory scope" value={selectedGroup} disabled={!!editing} onChange={event => setParams(event.target.value ? { group: event.target.value } : {})}>
              <option value="">Shared basics · all people</option>{scopes?.groups.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </div>
          {!visible.length ? (
            <p className="mt-5 rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
              {identities.length ? "No people match this group or search." : "Members appear here as your companion observes their messages."}
            </p>
          ) : (
            <div className="mt-5 overflow-x-auto rounded-xl border border-border"><table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="bg-muted/50 text-left text-xs font-medium text-muted-foreground">
                  <th className="px-3 py-3">Person</th>
                  <th className="pr-3">Pronouns and role</th>
                  <th className="pr-3">Groups</th>
                  <th className="pr-3">Saved as</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={`${row.platform}:${row.user_id}`} className="border-t border-border/70 hover:bg-muted/30">
                    <td className="px-3 py-3"><p className="font-medium">{(facts(row)?.display_name ?? row.display_name) || "Unnamed person"}</p><p className="mt-1 text-xs text-muted-foreground">{(facts(row)?.aliases || row.aliases || []).join(", ") || `${row.platform} / ${row.user_id}`}</p></td>
                    <td className="pr-3"><p>{(facts(row)?.pronouns ?? row.pronouns) || "—"}</p><p className="mt-1 text-xs text-muted-foreground">{(facts(row)?.role ?? row.role ?? "")}</p></td>
                    <td className="max-w-56 pr-3"><div className="flex flex-wrap gap-x-3 gap-y-1">{personScope(row)?.groups.map(room => <Link key={room.id} to={`/groups?group=${room.id}`} className="text-xs text-primary underline">{room.name}</Link>)}{!personScope(row)?.groups.length && <span className="text-xs text-muted-foreground">No observed group yet</span>}</div></td>
                    <td className="pr-3"><Badge tone={facts(row)?.overridden ? "default" : "outline"}>{facts(row)?.overridden ? "Group entry" : "Shared basics"}</Badge></td>
                    <td>
                      <Button ghost size="sm" onClick={() => editPerson(row)} disabled={!!editing || busy !== null}>
                        Edit
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </CardContent>
      </Card>

      {directoryError && <p role="alert" className="text-sm text-destructive">Could not read PEOPLE.md: {directoryError}. Saved identities are still available.</p>}
      {directory && <details className="rounded-panel border border-border bg-card p-5"><summary className="cursor-pointer text-sm font-medium">Local directory and identity tools</summary><div className="mt-4 space-y-4">
        {audit && <AuditPanel audit={audit} />}
        <Button outlined size="sm" onClick={runSync} disabled={busy === "sync"}>Sync basic identity cards to Honcho</Button>
        <CardContent className="space-y-3 p-5">
          <H2 className="text-base">PEOPLE.md</H2>
          <p className="text-sm text-muted-foreground">{directory.count} people saved locally. Your companion can add or update basic entries with the people tool, even when Honcho is unavailable. This stores names, aliases, pronouns and short roles, with no detailed memories. One transport ID follows a person across groups; model updates stay in the group or DM where they were learned.</p>
          <Link to="/memory?file=people" className="inline-block text-sm text-primary underline">Open PEOPLE.md editor</Link>
          <details className="text-sm"><summary>View local directory</summary><pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-background/70 p-3 font-mono text-xs">{directory.text}</pre></details>
          <p className="text-xs text-muted-foreground">Edit person above updates shared basic details. Model updates remain local to their group or DM. PEOPLE.md stays out of shareable profile exports; private data backups include it.</p>
        </CardContent>
      </div></details>}

      {editing && (<div ref={editHeading}>
        <Card className="rounded-2xl border-border shadow-sm">
          <CardContent className="p-5 md:p-6">
            <H2 className="text-base">
              {editing.group_id ? "Edit this group's entry" : identities.some((i) => i.user_id === editing.user_id) ? "Edit shared basic details" : "Add person"}
            </H2>
            <div className="grid max-w-2xl grid-cols-1 gap-4 pt-4 text-sm sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Platform</span>
                <input
                  className="rounded-xl border border-border bg-background/70 px-3 py-2"
                  value={editing.platform}
                  disabled={identities.some(row => row.platform === editing.platform && row.user_id === editing.user_id)}
                  onChange={(e) => setEditing({ ...editing, platform: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Runtime user ID</span>
                <input
                  className="rounded-xl border border-border bg-background/70 px-3 py-2 font-mono"
                  value={editing.user_id}
                  disabled={identities.some(row => row.platform === editing.platform && row.user_id === editing.user_id)}
                  onChange={(e) => setEditing({ ...editing, user_id: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Display name</span>
                <input
                  className="rounded-xl border border-border bg-background/70 px-3 py-2"
                  value={editing.display_name}
                  onChange={(e) => setEditing({ ...editing, display_name: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Pronouns</span>
                <input
                  className="rounded-xl border border-border bg-background/70 px-3 py-2"
                  value={editing.pronouns}
                  onChange={(e) => setEditing({ ...editing, pronouns: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Role</span>
                <input
                  className="rounded-xl border border-border bg-background/70 px-3 py-2"
                  value={editing.role}
                  onChange={(e) => setEditing({ ...editing, role: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Aliases (comma separated)</span>
                <input
                  className="rounded-xl border border-border bg-background/70 px-3 py-2"
                  value={editing.aliases}
                  onChange={(e) => setEditing({ ...editing, aliases: e.target.value })}
                />
              </label>
            </div>
            <div className="flex gap-2 pt-3">
              <Button size="sm" onClick={saveIdentity} disabled={busy !== null}>
                <Save className="mr-1 h-3.5 w-3.5" /> {editing.group_id ? "Save group entry" : "Save shared basics"}
              </Button>
              <Button outlined size="sm" onClick={() => setEditing(null)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>)}

      <details className="rounded-panel border border-border bg-card"><summary className="cursor-pointer px-5 py-4 text-sm font-medium">Link two accounts belonging to one person</summary>
        <CardContent className="p-5 md:p-6">
          <H2 className="text-lg">Merge accounts</H2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Combine two platform IDs that belong to the same person. The second ID will share the primary profile and history.
          </p>
          <div className="flex max-w-2xl flex-col gap-3 pt-4 sm:flex-row">
            <input
              className="min-w-0 flex-1 rounded-xl border border-border bg-background/70 px-3 py-2 font-mono text-sm"
              aria-label="Primary runtime user ID"
              placeholder="Primary runtime ID"
              value={merge.primary}
              onChange={(e) => setMerge({ ...merge, primary: e.target.value })}
            />
            <input
              className="min-w-0 flex-1 rounded-xl border border-border bg-background/70 px-3 py-2 font-mono text-sm"
              aria-label="Second runtime user ID"
              placeholder="Second runtime ID"
              value={merge.alt}
              onChange={(e) => setMerge({ ...merge, alt: e.target.value })}
            />
            <Button
              size="sm"
              onClick={() =>
                setConfirmMerge({
                  primary: merge.primary.trim(),
                  alt: merge.alt.trim(),
                })
              }
              disabled={busy === "merge"}
            >
              <GitMerge className="mr-1 h-3.5 w-3.5" /> Merge
            </Button>
          </div>
        </CardContent>
      </details>

      {/* The consequences are the point of this dialog. "Merge" reads like it adds a link; it
          actually rewrites `luna_identity` — the alt row is absorbed into the primary and DELETED,
          so your companion can no longer tell the two ids apart and the peer inherits the primary's history
          under one identity. There is no un-merge in the UI. */}
      <DeleteConfirmDialog
        open={confirmMerge !== null}
        onCancel={() => setConfirmMerge(null)}
        onConfirm={() => void runMerge()}
        title={`Merge ${confirmMerge?.primary ?? ""} and ${confirmMerge?.alt ?? ""}?`}
        description={`These two platform IDs become one identity. Messages from ${confirmMerge?.alt ?? "the second account"} will be attributed to ${confirmMerge?.primary ?? "the primary account"}, and their history follows that identity. Check both IDs carefully; undoing a merge requires restoring a private data backup.`}
        confirmLabel="Merge identities"
        loading={busy === "merge"}
      />

      <Toast toast={toast} />
    </div>
  );
}
