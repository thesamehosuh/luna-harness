import { createContext } from "react";

/**
 * The context value, kept separate from the provider so the hook can live in a `.ts` file — the same
 * split `profile-context.ts` / `ProfileProvider.tsx` / `useProfileScope.ts` uses, and the reason
 * `react-refresh` does not complain about a component file that also exports a hook.
 */
export interface UnsavedChangesApi {
  /**
   * Run a navigation, or hold it back until the user resolves the bar.
   *
   * Needed for navigation the guarded history cannot see, because it never reaches `history.push`:
   * remounting the routed tree on a profile switch (`ProfileKeyedRoutes` in `App.tsx`), a modal that
   * discards its draft when it closes on Escape, and a wizard's own Cancel button.
   */
  requestLeave: (resume: () => void) => void;
}

export const UnsavedChangesContext = createContext<UnsavedChangesApi | null>(null);
