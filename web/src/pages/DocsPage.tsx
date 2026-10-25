import { useLayoutEffect } from "react";
import { Link } from "react-router";
import { ExternalLink } from "lucide-react";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";
import { lunaDocsUrl } from "@/lib/luna-paths";

const DS_BUTTON_OUTLINED_LINK_CN = cn(
  "group relative inline-flex items-center justify-center gap-2",
  "min-h-10 rounded-control border border-border px-4 py-2",
  "text-sm font-medium text-foreground hover:bg-accent",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
);

export default function DocsPage() {
  const { t } = useI18n();
  const { setEnd } = usePageHeader();

  // Operator-configured (`luna.docs.url`), empty by default. This page used to hardcode a
  // third-party documentation site and iframe the whole surface from it, so Luna's dashboard
  // rendered someone else's docs as though they documented Luna -- and a stale hardcode cannot be
  // corrected without a rebuild. The backend only forwards http(s) values, so a `javascript:` URL
  // cannot reach an iframe src from the config.
  const docsUrl = lunaDocsUrl();

  useLayoutEffect(() => {
    // With no docs site configured there is nothing to open in a new tab, so the button is omitted
    // rather than rendered pointing at a page that would 404.
    if (!docsUrl) {
      setEnd(null);
      return;
    }
    setEnd(
      <a
        href={docsUrl}
        target="_blank"
        rel="noopener noreferrer"
        className={DS_BUTTON_OUTLINED_LINK_CN}
      >
        <ExternalLink className="size-3.5" />
        {t.app.openDocumentation}
      </a>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, t, docsUrl]);

  return (
    <div
      className={cn(
        "flex min-h-0 w-full min-w-0 flex-1 flex-col",
        "pt-1 sm:pt-2",
      )}
    >
      <PluginSlot name="docs:top" />
      {docsUrl ? (
        <iframe
          title={t.app.nav.documentation}
          src={docsUrl}
          className={cn(
            "min-h-0 w-full min-w-0 flex-1",
            "rounded-sm border border-current/20",
            // Docusaurus paints over a transparent <html> / <body> and
            // relies on the browser's canvas color (light by default) to
            // fill the viewport. Inheriting the dashboard's dark color
            // scheme makes that canvas dark, so the docs body text — which
            // is tuned for a light canvas — becomes near-invisible. Force a
            // light color scheme + white background on the iframe element so
            // the docs render cleanly regardless of the active dashboard
            // theme or the user's prefers-color-scheme.
            "[color-scheme:light] bg-white",
          )}
          sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
          referrerPolicy="no-referrer-when-downgrade"
        />
      ) : (
        // No docs site configured (the default). Send the user to the help page that ships in the
        // dashboard, rather than rendering an empty frame that looks broken.
        <div className="flex min-h-0 w-full flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
          <p className="max-w-prose text-sm text-muted-foreground">
            No documentation site is configured for this install.
          </p>
          <Link
            to="/help"
            className="text-sm text-midground underline underline-offset-4 hover:opacity-80"
          >
            Open the in-dashboard help
          </Link>
        </div>
      )}
      <PluginSlot name="docs:bottom" />
    </div>
  );
}
