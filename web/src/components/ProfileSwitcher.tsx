import { useMemo } from "react";
import { Users } from "lucide-react";
import {
  Select,
  SelectOption,
} from "@nous-research/ui/ui/components/select";
import { useProfileScope } from "@/contexts/useProfileScope";
import { useUnsavedChangesGuard } from "@/hooks/useUnsavedChanges";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * The machine dashboard's single write-target selector.
 *
 * Rendered in the sidebar above the nav. Every management page (Config,
 * Keys, Skills, MCP, Models) reads/writes the selected profile via the
 * fetchJSON ?profile= injection. Hidden when only one profile exists.
 */
export function ProfileSwitcher({ collapsed }: ProfileSwitcherProps) {
  const { profile, currentProfile, profiles, setProfile } = useProfileScope();
  const { t } = useI18n();
  const { requestLeave } = useUnsavedChangesGuard();

  // Switching profile remounts the entire routed tree (`ProfileKeyedRoutes` in App.tsx keys the
  // routes on the profile), so it is a navigation in every way that matters — it just never reaches
  // `history.push`, which is why the guarded history cannot catch it. Without this, a dirty form
  // died silently on a profile switch.
  const selectProfile = (next: string) => requestLeave(() => setProfile(next));

  const currentDashboardLabel = useMemo(
    () =>
      (t.app.currentProfileOption ?? "this dashboard ({name})").replace(
        "{name}",
        currentProfile || "default",
      ),
    [currentProfile, t.app.currentProfileOption],
  );

  if (profiles.length < 2) return null;

  const managed = profile || currentProfile || "default";
  const isOther = !!profile && profile !== currentProfile;
  const managingLabel = t.app.managingProfile ?? "Managing profile";

  return (
    <div
      className={cn(
        "flex items-center gap-2 border-b border-current/10 px-3 py-2",
        collapsed && "lg:justify-center lg:px-0",
      )}
      title={managingLabel}
    >
      <Users
        className={cn(
          "h-3.5 w-3.5 shrink-0",
          isOther ? "text-warning" : "text-text-tertiary",
        )}
      />

      <Select
        className={cn(
          "min-w-0 flex-1",
          collapsed && "lg:hidden",
          "[&_button]:h-7 [&_button]:border-border [&_button]:bg-background [&_button]:px-2 [&_button]:text-xs",
          "[&_button]:font-sans [&_button]:normal-case [&_button]:tracking-normal",
          "[&_[role=listbox]>div]:font-sans [&_[role=listbox]>div]:text-xs",
          "[&_[role=listbox]>div]:normal-case [&_[role=listbox]>div]:tracking-normal",
          isOther &&
            "[&_button]:border-warning/50 [&_button]:text-warning",
        )}
        id="hermes-profile-switcher"
        onValueChange={selectProfile}
        value={profile}
      >
        <SelectOption value="">{currentDashboardLabel}</SelectOption>

        {profiles
          .filter((name) => name !== currentProfile)
          .map((name) => (
            <SelectOption key={name} value={name}>
              {name}
            </SelectOption>
          ))}
      </Select>

      {collapsed && <span className="sr-only">{managed}</span>}
    </div>
  );
}

interface ProfileSwitcherProps {
  collapsed?: boolean;
}
