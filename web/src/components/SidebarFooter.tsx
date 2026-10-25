import { Typography } from "@/components/ui/Typography";
import type { StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { Link } from "react-router";

export function SidebarFooter({ status }: SidebarFooterProps) {
  const { t } = useI18n();

  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-between gap-2",
        "px-5 py-2.5",
        "border-t border-current/10",
      )}
    >
      <Typography
        className="font-mono-ui text-xs tabular-nums text-text-tertiary"
      >
        {status?.version != null ? `v${status.version}` : "—"}
      </Typography>

      <Link
        to="/help#credits"
        className={cn(
          "font-sans text-xs text-muted-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/40",
        )}
      >
        {t.app.footer.org}
      </Link>
    </div>
  );
}

interface SidebarFooterProps {
  status: StatusResponse | null;
}
