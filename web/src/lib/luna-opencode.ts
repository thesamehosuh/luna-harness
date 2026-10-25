import { fetchJSON } from "@/lib/api";

export interface OpenCodeStatus {
  installed: boolean;
  version: string | null;
  recommended_version: string;
  selected: string;
}

export interface FreeModel {
  id: string;
  name: string;
  free: boolean;
  context?: number;
  vision: boolean;
}

export interface OpenCodeCatalog extends OpenCodeStatus {
  models: FreeModel[];
}

export interface ModelProbe {
  ok: boolean;
  detail: string;
  model: string;
  cost?: number;
}

const modelRequest = (model: string, method: string): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ model }),
});

export const opencodeApi = {
  status: () => fetchJSON<OpenCodeStatus>("/api/luna/opencode"),
  install: () => fetchJSON<OpenCodeStatus>("/api/luna/opencode/install", { method: "POST" }),
  models: () => fetchJSON<OpenCodeCatalog>("/api/luna/opencode/models"),
  select: (model: string) => fetchJSON<{ ok: boolean; model: FreeModel }>("/api/luna/opencode/model", modelRequest(model, "PUT")),
  probe: (model: string) => fetchJSON<ModelProbe>("/api/luna/opencode/probe", modelRequest(model, "POST")),
};
