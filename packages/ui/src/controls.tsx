"use client";

import * as CollapsiblePrimitive from "@radix-ui/react-collapsible";
import * as SelectPrimitive from "@radix-ui/react-select";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { Check, ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "./cn";

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("inline-flex items-center gap-1 border-b border-border", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "relative -mb-px border-b-2 border-transparent px-3 pb-2.5 pt-1 text-sm text-subtle transition-colors hover:text-text " +
          "data-[state=active]:border-accent data-[state=active]:text-text",
        className,
      )}
      {...props}
    />
  );
}

export const Collapsible = CollapsiblePrimitive.Root;
export const CollapsibleTrigger = CollapsiblePrimitive.Trigger;
export const CollapsibleContent = CollapsiblePrimitive.Content;

export function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-surface-3 transition-colors data-[state=checked]:bg-accent",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </SwitchPrimitive.Root>
  );
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder,
  className,
  ariaLabel,
}: {
  value?: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: string; hint?: string }[];
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger
        aria-label={ariaLabel}
        className={cn(
          "inline-flex h-9 items-center justify-between gap-2 rounded-[10px] border border-border bg-surface-2 px-3 text-sm text-text " +
            "focus:outline-none focus:ring-2 focus:ring-accent/40",
          className,
        )}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <ChevronDown className="size-4 text-subtle" />
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content position="popper" sideOffset={6} className="z-50 min-w-[var(--radix-select-trigger-width)] rounded-[12px] border border-border-strong bg-surface p-1 shadow-panel">
          <SelectPrimitive.Viewport>
            {options.map((o) => (
              <SelectPrimitive.Item
                key={o.value}
                value={o.value}
                className="relative flex cursor-pointer select-none flex-col rounded-[8px] py-1.5 pl-7 pr-2 text-[13px] text-muted outline-none data-[highlighted]:bg-surface-2 data-[highlighted]:text-text"
              >
                <SelectPrimitive.ItemIndicator className="absolute left-2 top-2">
                  <Check className="size-3.5 text-accent" />
                </SelectPrimitive.ItemIndicator>
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                {o.hint ? <span className="text-[11px] text-subtle">{o.hint}</span> : null}
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
