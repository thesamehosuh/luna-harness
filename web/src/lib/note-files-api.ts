import { fetchJSON } from "@/lib/api";

export type NoteFileInfo = {
  id: string;
  name: string;
  scope: string;
  kind: "notes" | "people";
  description: string;
  limit: number;
  enabled: boolean;
};
export type NoteFile = NoteFileInfo & { content: string; revision: string };

export const noteFilesApi = {
  list: () => fetchJSON<{ files: NoteFileInfo[] }>("/api/luna/note-files"),
  read: (id: string) => fetchJSON<NoteFile>(`/api/luna/note-files/${encodeURIComponent(id)}`),
  save: (id: string, content: string, revision: string) => fetchJSON<NoteFile>(
    `/api/luna/note-files/${encodeURIComponent(id)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, revision }),
    }),
};
