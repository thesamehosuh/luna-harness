import { fetchJSON } from "@/lib/api";

export type GroupSummary = { id: string; platform: string; chat_id: string; thread_id: string; name: string; members: number; note_chars: number };
export type PersonFacts = { display_name: string; aliases: string[]; pronouns: string; role: string; overridden: boolean; revision: string };
export type GroupPerson = PersonFacts & { platform: string; user_id: string };
export type GroupPolicy = { notes_enabled: boolean; people_enabled: boolean; write_approval: boolean; review_interval: number; reviews_enabled: boolean; note_limit: number; owner_configured: boolean };
export type GroupBundle = { groups: GroupSummary[]; policy: GroupPolicy; group?: GroupSummary & { notes: { entries: string[]; chars: number; revision: string }; people: GroupPerson[] } };
export type ScopedPerson = { platform: string; user_id: string; shared: PersonFacts; groups: Array<GroupSummary & { entry: PersonFacts }> };
export type PeopleScopes = { people: ScopedPerson[]; groups: GroupSummary[] };

const request = (body: unknown) => ({ method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const groupsApi = {
  list: () => fetchJSON<GroupBundle>("/api/luna/groups"),
  get: (id: string) => fetchJSON<GroupBundle>(`/api/luna/groups/${encodeURIComponent(id)}`),
  saveNotes: (id: string, entries: string[], revision: string) => fetchJSON<GroupBundle>(`/api/luna/groups/${encodeURIComponent(id)}/notes`, request({ entries, revision })),
  savePerson: (id: string, userId: string, values: Record<string, unknown>, revision: string, inherit = false) => fetchJSON<GroupBundle>(`/api/luna/groups/${encodeURIComponent(id)}/people/${encodeURIComponent(userId)}`, request({ values, revision, inherit })),
  people: () => fetchJSON<PeopleScopes>("/api/luna/people/scopes"),
};
