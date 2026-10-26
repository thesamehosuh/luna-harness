import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

export type ButtonSize = "default" | "sm" | "xs" | "icon";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "prefix"> {
  destructive?: boolean;
  ghost?: boolean;
  invert?: boolean;
  outlined?: boolean;
  prefix?: ReactNode;
  size?: ButtonSize;
  suffix?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    children,
    className,
    destructive = false,
    ghost = false,
    invert = false,
    outlined = false,
    prefix,
    size = "default",
    suffix,
    type = "button",
    ...props
  },
  ref,
) {
  const visualVariant = destructive
    ? ghost
      ? "text-destructive hover:bg-destructive/10"
      : outlined
        ? "border border-destructive/40 bg-transparent text-destructive hover:bg-destructive/10"
        : "bg-destructive text-destructive-foreground hover:bg-destructive/90"
    : ghost
      ? "bg-transparent text-foreground hover:bg-accent"
      : outlined
        ? invert
          ? "border border-primary-foreground/25 bg-transparent text-primary-foreground hover:bg-primary-foreground/10"
          : "border border-border bg-transparent text-foreground hover:bg-accent"
        : invert
          ? "bg-primary-foreground text-primary hover:bg-primary-foreground/90"
          : "bg-primary text-primary-foreground hover:bg-primary/90";

  const sizeStyles: Record<ButtonSize, string> = {
    default: "min-h-10 px-4 py-2 text-sm",
    sm: "min-h-9 px-3 py-1.5 text-sm",
    xs: "min-h-8 px-2.5 py-1 text-xs",
    icon: "size-10 p-0 [&_svg]:size-4",
  };

  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-2 rounded-control font-medium leading-5 transition-colors duration-150 enabled:cursor-pointer enabled:active:brightness-95",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:pointer-events-none disabled:opacity-50",
        "[&_svg]:shrink-0",
        visualVariant,
        sizeStyles[size],
        className,
      )}
      {...props}
    >
      {prefix != null && <span className="inline-flex shrink-0 items-center [&_svg]:size-4">{prefix}</span>}
      {children}
      {suffix != null && <span className="inline-flex shrink-0 items-center [&_svg]:size-4">{suffix}</span>}
    </button>
  );
});

