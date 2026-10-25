/**
 * `<DirtyBar>` — the one place the dashboard says "you have unsaved changes".
 *
 * Rendered once by `UnsavedChangesProvider`, so a single instance covers every guarded surface and
 * the three states are distinguished by what the user is being asked rather than by which page they
 * are on:
 *
 * - **dirty, nothing pending** — a quiet `role="status"` bar with Save / Discard, so the state is
 *   visible *before* the user tries to navigate away rather than only at the moment of loss.
 * - **dirty, navigation pending** — the same bar promoted to `role="alertdialog"` with Save /
 *   Discard / Stay, because a navigation is now genuinely at stake.
 * - **clean** — renders nothing.
 *
 * react-router's own docs call block-then-confirm "rough edges ... behaves very differently across
 * browsers if you click back/forward while the confirmation is open". Keeping the UI in one
 * component instead of five per-page dialogs is what keeps those edges in one file.
 */

import { Button } from "@/components/ui/Button";
import { AlertTriangle, Save, Trash2, X } from "lucide-react";

import { useI18n } from "@/i18n";
import { dirtyBarLabels } from "@/lib/dirty-bar-copy";
import { cn } from "@/lib/utils";

export interface DirtyBarProps {
  /** Labels of every surface with unsaved edits, in registration order. */
  labels: string[];
  /** True when a navigation is being held back waiting on this decision. */
  pending: boolean;
  /**
   * False when any dirty surface cannot be saved — e.g. the profile wizard, whose steps are only
   * persisted by Create.
   *
   * The Save button is then omitted entirely. It used to render unconditionally while `saveAll`
   * silently skipped such an entry and returned success, so on the wizard "Save and leave" discarded
   * five steps of work under a label that promised the opposite — and the non-pending Save was a dead
   * button. A guard must not offer an action it cannot honour.
   */
  canSave?: boolean;
  saving?: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onStay: () => void;
}

export function DirtyBar({
  labels,
  pending,
  canSave = true,
  saving = false,
  onSave,
  onDiscard,
  onStay,
}: DirtyBarProps) {
  const { t } = useI18n();
  const copy = dirtyBarLabels(t.common, labels);

  if (labels.length === 0) return null;

  return (
    <div
      // `alertdialog` while a navigation is blocked so a screen reader announces the interruption;
      // `status` otherwise, because it is informational and must not steal focus.
      role={pending ? "alertdialog" : "status"}
      aria-label={pending ? copy.blocked : copy.title}
      aria-live={pending ? "assertive" : "polite"}
      data-pending={pending ? "true" : "false"}
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border bg-card px-4 py-3 text-sm shadow-xl",
        pending
          ? "border-destructive/40"
          : "border-warning/40",
      )}
    >
      <AlertTriangle
        aria-hidden
        className={cn("h-4 w-4 shrink-0", pending ? "text-destructive" : "text-warning")}
      />

      <div className="min-w-0 flex-1">
        <div className="font-medium">{pending ? copy.blocked : copy.title}</div>
        <div className="truncate text-xs text-muted-foreground">
          {copy.what} {labels.join(", ")}
        </div>
      </div>

      <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
        {canSave && (
          <Button
            size="sm"
            onClick={onSave}
            disabled={saving}
            prefix={<Save className="h-3.5 w-3.5" />}
          >
            {saving ? t.common.saving : pending ? copy.saveAndLeave : t.common.save}
          </Button>
        )}
        <Button
          size="sm"
          outlined
          onClick={onDiscard}
          disabled={saving}
          prefix={<Trash2 className="h-3.5 w-3.5" />}
        >
          {pending ? copy.discardAndLeave : copy.discard}
        </Button>
        {pending && (
          // Never disabled by `saving`: a PUT with no timeout can hang indefinitely, and Stay is the
          // only escape from a bar whose Save and Discard are both blocked on it.
          <Button size="sm" ghost onClick={onStay} prefix={<X className="h-3.5 w-3.5" />} aria-label={copy.stay}>
            {copy.stay}
          </Button>
        )}
      </div>
    </div>
  );
}
