import { createElement, forwardRef } from "react";
import type { ComponentPropsWithRef, ElementType, ReactElement } from "react";

import { cn } from "@/lib/utils";

type FontFlags = {
  compressed?: boolean;
  courier?: boolean;
  expanded?: boolean;
  mondwest?: boolean;
  mono?: boolean;
  variant?: "lg" | "md" | "sm" | "xl";
};

export type TypographyProps<T extends ElementType = "span"> = {
  as?: T;
} & FontFlags & Omit<ComponentPropsWithRef<T>, keyof FontFlags | "as">;

const variants: Record<NonNullable<FontFlags["variant"]>, string> = {
  lg: "text-2xl leading-tight tracking-normal",
  md: "text-2xl leading-tight tracking-normal",
  sm: "text-sm leading-relaxed tracking-normal",
  xl: "text-4xl leading-tight tracking-normal",
};

export function Typography<T extends ElementType = "span">({
  as = "span" as T,
  className,
  compressed = false,
  courier = false,
  expanded = false,
  mondwest = false,
  mono = false,
  variant,
  ...props
}: TypographyProps<T>) {
  // Legacy font switches remain accepted for source compatibility. The
  // vintage display faces now resolve to Luna's modern display/sans tokens.
  const fontClass = courier || mono ? "font-mono" : mondwest ? "font-display" : "font-sans";
  const legacyWeight = expanded || compressed ? "font-medium" : undefined;

  return createElement(as, {
    ...props,
    className: cn(fontClass, legacyWeight, variant && variants[variant as NonNullable<FontFlags["variant"]>], className),
  }) as ReactElement;
}

export const H2 = forwardRef<HTMLHeadingElement, TypographyProps<"h2">>(function H2(
  {
    className,
    compressed = false,
    courier = false,
    expanded = false,
    mondwest = false,
    mono = false,
    variant = "lg",
    ...props
  },
  ref,
) {
  const fontClass = courier || mono
    ? "font-mono"
    : mondwest || (!compressed && !expanded)
      ? "font-display"
      : "font-sans";
  const legacyWeight = expanded || compressed ? "font-medium" : undefined;
  return createElement("h2", {
    ...props,
    ref,
    className: cn(fontClass, legacyWeight, variants[variant], "font-semibold", className),
  });
});

