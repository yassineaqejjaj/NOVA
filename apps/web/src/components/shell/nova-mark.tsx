"use client";

import { cn } from "@nova/ui";
import { motion } from "framer-motion";

import type { NovaPhase } from "@/lib/api/types";

const ACTIVE: NovaPhase[] = ["retrieving_context", "planning", "executing"];

/** NOVA's orb — a soft glowing sphere that doubles as its activity indicator (pulses while working). */
export function NovaMark({ phase = "idle", size = 22, className }: { phase?: NovaPhase; size?: number; className?: string }) {
  const active = ACTIVE.includes(phase);
  const waiting = phase === "waiting_user";
  return (
    <span className={cn("relative inline-flex shrink-0 items-center justify-center", className)} style={{ width: size, height: size }}>
      {active || waiting ? (
        <motion.span
          className="absolute inset-[-20%] rounded-full"
          style={{ background: waiting ? "radial-gradient(circle, rgb(245 158 11 / 0.35), transparent 65%)" : "radial-gradient(circle, var(--glow), transparent 65%)" }}
          animate={{ scale: [0.9, 1.25, 0.9], opacity: [0.9, 0.35, 0.9] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
        />
      ) : null}
      <span
        aria-hidden
        className="relative block size-full rounded-full"
        style={{
          background:
            "radial-gradient(circle at 34% 30%, #fff 0%, #ffe3ea 18%, #f9a8bf 42%, #f0463c 78%, #c2263f 100%)",
          boxShadow: "0 0 12px 1px var(--glow), inset -2px -3px 6px rgb(160 20 50 / 0.25)",
        }}
      />
    </span>
  );
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
