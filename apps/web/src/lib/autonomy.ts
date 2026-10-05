import type { AutonomyMode } from "@/lib/api/types";
import type { Lang } from "@/lib/i18n";

type Option = { value: AutonomyMode; label: string; hint: string };

const OPTIONS: Record<Lang, Option[]> = {
  en: [
    { value: "observe", label: "Observe", hint: "NOVA analyses and recommends; nothing runs" },
    { value: "suggest", label: "Suggest", hint: "NOVA proposes; nothing runs without you" },
    { value: "assist", label: "Assist", hint: "Single Skills run; workflows wait for your OK (default)" },
    { value: "execute_with_approval", label: "Execute with approval", hint: "Runs workflows; changes to existing Artifacts wait for approval" },
    { value: "execute_automatically", label: "Autonomous", hint: "No confirmation; external changes still follow company policy" },
  ],
  fr: [
    { value: "observe", label: "Observer", hint: "NOVA analyse et recommande ; rien ne s’exécute" },
    { value: "suggest", label: "Proposer", hint: "NOVA propose ; rien ne s’exécute sans vous" },
    { value: "assist", label: "Assister", hint: "Une Skill seule s’exécute ; les workflows attendent votre accord (par défaut)" },
    { value: "execute_with_approval", label: "Exécuter avec validation", hint: "Exécute les workflows ; les modifications d’Artefacts existants attendent votre validation" },
    { value: "execute_automatically", label: "Autonome", hint: "Sans confirmation ; les modifications externes suivent toujours la politique de l’entreprise" },
  ],
};

/** Autonomy levels, localized. */
export function autonomyOptions(lang: Lang): Option[] {
  return OPTIONS[lang];
}

/** @deprecated use autonomyOptions(lang) */
export const AUTONOMY = OPTIONS.en;
