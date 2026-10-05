import { defineMessages } from "@/lib/i18n";

export const M = defineMessages({
  en: {
    orchestrator: "orchestrating the sub-agents",
    team: "Sub-agents",
    progress: (v: { done: number; total: number }) => `${v.done}/${v.total} steps`,
    queued: "Queued",
    working: "Working",
    waiting: "Waiting for you",
    paused: "Paused",
    done: "Done",
    failed: "Failed",
    skipped: "Skipped",
    needsYou: "Needs your answer to continue",
    open: "Open",
    assumptions: (v: { list: string }) => `Assumptions: ${v.list}`,
  },
  fr: {
    orchestrator: "orchestre les sous-agents",
    team: "Sous-agents",
    progress: (v: { done: number; total: number }) => `${v.done}/${v.total} étapes`,
    queued: "En attente",
    working: "En cours",
    waiting: "Vous attend",
    paused: "En pause",
    done: "Terminé",
    failed: "Échec",
    skipped: "Ignoré",
    needsYou: "Attend votre réponse pour continuer",
    open: "Ouvrir",
    assumptions: (v: { list: string }) => `Hypothèses : ${v.list}`,
  },
});
