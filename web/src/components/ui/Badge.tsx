import { forwardRef } from "react";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type BadgeTone = "default" | "destructive" | "outline" | "secondary" | "success" | "warning";

const tones: Record<BadgeTone, string> = {
  default: "border-primary/20 bg-primary/10 text-primary",
  destructive: "border-destructive/25 bg-destructive/10 text-destructive",
  outline: "border-border bg-transparent text-muted-foreground",
  secondary: "border-border bg-muted text-muted-foreground",
  success: "border-success/25 bg-success/10 text-success",
  warning: "border-warning/25 bg-warning/10 text-warning",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { className, tone = "default", ...props },
  ref,
) {
  return (
    <span
      ref={ref}
      className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium leading-tight", tones[tone], className)}
      {...props}
    />
  );
});
