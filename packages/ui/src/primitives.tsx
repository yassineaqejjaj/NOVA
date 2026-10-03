import * as React from "react";

import { cn } from "./cn";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-[14px] border border-border bg-surface shadow-panel", className)} {...props} />;
}

export function Badge({
  className,
  tone = "neutral",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "accent" | "success" | "warning" | "danger" }) {
  const tones = {
    neutral: "bg-surface-3 text-muted",
    accent: "bg-accent-soft text-accent",
    success: "bg-success/12 text-success",
    warning: "bg-warning/12 text-warning",
    danger: "bg-danger/12 text-danger",
  } as const;
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium leading-none", tones[tone], className)}
      {...props}
    />
  );
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-9 w-full rounded-[10px] border border-border bg-surface-2 px-3 text-sm text-text placeholder:text-subtle " +
        "focus:outline-none focus:ring-2 focus:ring-accent/40",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full rounded-[10px] border border-border bg-surface-2 px-3 py-2 text-sm text-text placeholder:text-subtle " +
          "focus:outline-none focus:ring-2 focus:ring-accent/40",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export function Kbd({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn("rounded-md border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-subtle", className)}
      {...props}
    />
  );
}

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-surface-3", className)} {...props} />;
}

export function Separator({ className }: { className?: string }) {
  return <div role="separator" className={cn("h-px w-full bg-border", className)} />;
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-[13px] font-medium text-muted", className)} {...props} />;
}
