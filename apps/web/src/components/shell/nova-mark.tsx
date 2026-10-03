"use client";

import { cn } from "@nova/ui";

import type { NovaPhase } from "@/lib/api/types";

import { NovaOrb, orbStateFromPhase } from "./nova-orb";

/** NOVA's presence: the glass orb, animated according to the current phase. */
export function NovaMark({ phase = "idle", size = 22, className }: { phase?: NovaPhase; size?: number; className?: string }) {
  return <NovaOrb state={orbStateFromPhase(phase)} size={size} className={className} />;
}

export const PHASE_LABEL: Record<NovaPhase, string> = {
  idle: "Idle",
  retrieving_context: "Retrieving context",
  planning: "Planning",
  executing: "Executing",
  waiting_user: "Waiting for you",
  completed: "Completed",
  failed: "Failed",
};

/** Organization mark + wordmark. */
/** The NOVA wordmark (official artwork, transparent PNG). */
export function NovaLogo({ className, height = 24 }: { className?: string; height?: number }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static brand asset, already optimized
    <img src="/brand/nova-wordmark.png" alt="NOVA" width={Math.round((height * 433) / 117)} height={height} className={cn("select-none dark:brightness-[1.35]", className)} draggable={false} />
  );
}
