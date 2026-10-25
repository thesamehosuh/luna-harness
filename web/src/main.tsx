/**
 * The dashboard shell's providers: router, i18n, theme, system actions, unsaved-changes guard.
 *
 * `BrowserRouter` becomes `HistoryRouter` over a guarded history. That swap is the whole mechanism:
 * react-router's `useBlocker` needs a data router (`createBrowserRouter` + `RouterProvider`) and this
 * shell is declarative, so the guard is installed at the history object every in-app navigation
 * already flows through.
 *
 * Both imports below are `unstable_` / `UNSAFE_` prefixed upstream. That is the honest cost of not
 * migrating the whole shell to a data router, and it is a trade worth making: the alternative is no
 * unsaved-changes protection at all. Both are thin wrappers over the public `Router`, so an upstream
 * rename is a two-line change here rather than a redesign. Read through the namespace object so
 * TypeScript sees the real prefixed names instead of pretending they are unprefixed.
 */

import { createRoot } from "react-dom/client";
import * as ReactRouter from "react-router";
import "./index.css";
import App from "./App";
import { SystemActionsProvider } from "./contexts/SystemActions";
import { I18nProvider } from "./i18n";
import { UnsavedChangesProvider } from "./contexts/UnsavedChanges";
import { exposePluginSDK } from "./plugins";
import { ThemeProvider } from "./themes";
import { HERMES_BASE_PATH } from "./lib/api";
import {
  createGuardedHistory,
  type RoutableHistory,
} from "./lib/guarded-history";

const { unstable_HistoryRouter: HistoryRouter, UNSAFE_createBrowserHistory: createBrowserHistory } =
  ReactRouter;

// Expose the plugin SDK before rendering so plugins loaded via <script>
// can access React, components, etc. immediately.
exposePluginSDK();

// `v5Compat` matches what <BrowserRouter> passes internally, so the router still sees push/replace
// notifications synchronously. The casts are one-way on purpose: react-router does not export its
// `History` type, so the guard's structural interface is checked against it here rather than leaking
// into the guard's own signature.
const history = createGuardedHistory(
  createBrowserHistory({ v5Compat: true }) as unknown as RoutableHistory,
);

createRoot(document.getElementById("root")!).render(
  <HistoryRouter
    history={history as unknown as React.ComponentProps<typeof HistoryRouter>["history"]}
    basename={HERMES_BASE_PATH || undefined}
  >
    <I18nProvider>
      <ThemeProvider>
        <SystemActionsProvider>
          <UnsavedChangesProvider>
            <App />
          </UnsavedChangesProvider>
        </SystemActionsProvider>
      </ThemeProvider>
    </I18nProvider>
  </HistoryRouter>,
);
