"use client";

import { cn } from "@nova/ui";

import type { NovaPhase } from "@/lib/api/types";
import { getLang } from "@/lib/i18n";

import { NovaOrb, orbStateFromPhase } from "./nova-orb";

/** NOVA's presence: the glass orb, animated according to the current phase. */
export function NovaMark({ phase = "idle", size = 22, className }: { phase?: NovaPhase; size?: number; className?: string }) {
  return <NovaOrb state={orbStateFromPhase(phase)} size={size} className={className} />;
}

const PHASE_LABEL_TEXT: Record<NovaPhase, { en: string; fr: string }> = {
  idle: { en: "Idle", fr: "Inactif" },
  retrieving_context: { en: "Retrieving context", fr: "Récupère le contexte" },
  planning: { en: "Planning", fr: "Planifie" },
  executing: { en: "Executing", fr: "Exécute" },
  waiting_user: { en: "Waiting for you", fr: "Vous attend" },
  completed: { en: "Completed", fr: "Terminé" },
  failed: { en: "Failed", fr: "Échec" },
};

/** Localized labels (read in the current interface language). */
export const PHASE_LABEL = Object.defineProperties(
  {} as Record<NovaPhase, string>,
  Object.fromEntries(Object.keys(PHASE_LABEL_TEXT).map((k) => [k, { enumerable: true, get: () => PHASE_LABEL_TEXT[k as NovaPhase][getLang()] }])),
);

/** Organization mark + wordmark. */
/** The NOVA wordmark (official artwork, transparent PNG). */
export function NovaLogo({ className, height = 24 }: { className?: string; height?: number }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static brand asset, already optimized
    <img src="/brand/nova-wordmark.png" alt="NOVA" width={Math.round((height * 433) / 117)} height={height} className={cn("select-none dark:brightness-[1.35]", className)} draggable={false} />
  );
}
