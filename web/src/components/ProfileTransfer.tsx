import { useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { lunaApi, type ProfileTransferPreview } from "@/lib/luna-api";
import { errorMessage } from "@/lib/api-error";

/** A new destination is mandatory: portability never overwrites a working character. */
export function ProfileTransfer({ profiles, onImported }: {
  profiles: { name: string }[];
  onImported: () => void;
}) {
  const [source, setSource] = useState("default");
  const [file, setFile] = useState<{ name: string; bundle: unknown; preview: ProfileTransferPreview } | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const download = async () => {
    setBusy(true); setError(""); setMessage("");
    try {
      const bundle = await lunaApi.exportProfile(source);
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2) + "\n"], { type: "application/json" }));
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `${source}.luna-profile.json`;
      anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage("Profile downloaded. Review persona text before sharing it.");
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };

  const readFile = async (incoming: File) => {
    setBusy(true); setError(""); setMessage(""); setFile(null);
    try {
      if (incoming.size > 2 * 1024 * 1024) throw new Error("Profile file exceeds the 2 MiB limit");
      const bundle: unknown = JSON.parse(await incoming.text());
      const preview = await lunaApi.previewProfile(bundle);
      setFile({ name: incoming.name, bundle, preview });
      setName("");
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };

  const importFile = async () => {
    if (!file) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await lunaApi.importProfile(name.trim(), file.bundle);
      setFile(null); setName("");
      setMessage(`Imported ${result.name}. Select it in the profile picker, then open Setup to connect your model, chats and optional memory.`);
      onImported();
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };

  return <Card>
    <CardContent className="space-y-4 p-5">
      <div>
        <h2 className="text-lg">Import and export a profile</h2>
        <p className="mt-1 text-sm text-muted-foreground">Move the saved persona, model choices, behaviour, appearance and memory tuning in one file. Credentials, chat connections, history and local services stay on this device.</p>
      </div>
      <fieldset disabled={busy} className="flex min-w-0 flex-wrap items-end gap-3">
        <div className="grid min-w-0 gap-1">
          <Label htmlFor="export-profile">Profile to export</Label>
          <select id="export-profile" value={source} onChange={e => setSource(e.target.value)} className="max-w-full rounded-lg border border-input bg-background px-3 py-2 text-sm">
            {profiles.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </div>
        <Button outlined onClick={() => void download()}><Download className="mr-2 h-4 w-4" /> Export profile</Button>
        <Button outlined onClick={() => fileRef.current?.click()}><Upload className="mr-2 h-4 w-4" /> Import profile file</Button>
        <input ref={fileRef} type="file" accept=".json,application/json" className="sr-only" aria-label="Profile JSON file" onChange={e => {
          const incoming = e.target.files?.[0]; e.target.value = "";
          if (incoming) void readFile(incoming);
        }} />
      </fieldset>
      {file && <fieldset disabled={busy} className="space-y-3 rounded-xl border border-border bg-background/50 p-4" aria-label="Import preview">
        <p className="break-words font-medium">{file.preview.title || "Companion"} · {file.name}</p>
        {file.preview.description && <p className="text-sm">{file.preview.description}</p>}
        <p className="break-words text-sm text-muted-foreground">Settings: {file.preview.sections.join(", ") || "new-user defaults"}.</p>
        <p className="text-sm text-muted-foreground">Creates a new profile. Set up connections again; memory and proactive wakes stay off until you enable them. Skills and extensions are not installed from profile files.</p>
        {file.preview.missing_skills.length > 0 && <p className="break-words text-sm text-warning">Additional skills needed: {file.preview.missing_skills.join(", ")}</p>}
        {file.preview.omitted.length > 0 && <details className="text-sm"><summary>Settings left out ({file.preview.omitted.length})</summary><p className="mt-2 break-words text-muted-foreground">{file.preview.omitted.join(", ")}</p></details>}
        <div className="grid max-w-sm gap-1">
          <Label htmlFor="import-profile-name">New profile name</Label>
          <Input id="import-profile-name" value={name} onChange={e => setName(e.target.value)} placeholder="my-companion" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void importFile()} disabled={!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(name.trim()) || name.trim() === "default"}>Create imported profile</Button>
          <Button ghost onClick={() => setFile(null)}>Cancel</Button>
        </div>
      </fieldset>}
      {busy && <p role="status" className="text-sm text-muted-foreground">Preparing profile…</p>}
      {message && <p role="status" className="text-sm">{message}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </CardContent>
  </Card>;
}
