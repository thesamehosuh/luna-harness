import type { UpdateCheckResponse } from "./api";

export function lunaReleaseUpdateDescription(info: UpdateCheckResponse | null): string | null {
  if (info?.install_method !== "luna-release") return null;
  if (!info.update_available || !info.can_apply) return info.message ?? "You're on the latest published Luna version.";
  return `Install ${info.latest_version ? `Luna ${info.latest_version}` : "the latest Luna release"} after verifying its download. Stop your companion in Control Center and wait for active chats to finish first. Your character, settings, and memories stay here. Quit and reopen Luna when installation finishes, then start your companion when ready.`;
}
