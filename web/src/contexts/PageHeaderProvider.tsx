import { useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { PageHeaderContext } from "./page-header-context";
import { resolvePageTitle } from "@/lib/resolve-page-title";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { DASHBOARD_NAV, CHAT_NAV_ITEM, navGroupLabel } from "@/lib/navigation";

export function PageHeaderProvider({
  children,
  pluginTabs,
}: {
  children: ReactNode;
  pluginTabs: { path: string; label: string }[];
}) {
  const { pathname } = useLocation();
  const { t } = useI18n();
  const [titleOverride, setTitleOverride] = useState<string | null>(null);
  const [afterTitle, setAfterTitle] = useState<ReactNode>(null);
  const [end, setEnd] = useState<ReactNode>(null);

  // Clear any per-page title / toolbar slots when the path changes. Child routes
  // re-fill these on mount via usePageHeader.
  /* eslint-disable react-hooks/set-state-in-effect */
  useLayoutEffect(() => {
    setTitleOverride(null);
    setAfterTitle(null);
    setEnd(null);
  }, [pathname]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const defaultTitle = useMemo(
    () => resolvePageTitle(pathname, t, pluginTabs),
    [pathname, t, pluginTabs],
  );
  const displayTitle = titleOverride ?? defaultTitle;
  const routeGroup = [...DASHBOARD_NAV, CHAT_NAV_ITEM].find((item) => item.path === pathname.replace(/\/$/, ""))?.group;

  const isChatRoute = pathname === "/chat" || pathname === "/chat/";
  const value = useMemo(
    () => ({
      setAfterTitle,
      setEnd,
      setTitle: setTitleOverride,
    }),
    [],
  );

  return (
    <PageHeaderContext.Provider value={value}>
      <div className="flex min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden">
        <header className="z-1 w-full shrink-0 border-b border-border/60 bg-background-base px-4 py-4 sm:px-6 lg:px-8 lg:py-5">
          <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              {routeGroup && !isChatRoute && (
                <p className="mb-2 text-xs text-muted-foreground">{navGroupLabel(routeGroup, t)} <span aria-hidden className="mx-1 text-primary">/</span> {displayTitle}</p>
              )}
              <div className="flex min-w-0 flex-wrap items-center gap-3">
                <h1 className={cn("luna-page-title min-w-0 break-words text-foreground", isChatRoute && "text-2xl")}>{displayTitle}</h1>
                {afterTitle && <div className="min-w-0 max-w-full overflow-x-auto scrollbar-none">{afterTitle}</div>}
              </div>
            </div>
            {end && (
              <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2 lg:justify-end [&>*]:max-w-full [&>div]:flex-wrap">
                {end}
              </div>
            )}
          </div>
        </header>

        <main
          id="main-content"
          tabIndex={-1}
          className={cn(
            "min-h-0 w-full min-w-0 flex-1 flex flex-col",
            // Bottom inset for scrolled pages lives on the route outlet wrapper in
            // `App.tsx` (`w-full min-w-0`) so it pads scrollable content, not flex chrome.
            isChatRoute
              ? "overflow-hidden"
              : "overflow-auto [scrollbar-gutter:stable]",
          )}
        >
          {children}
        </main>
      </div>
    </PageHeaderContext.Provider>
  );
}
