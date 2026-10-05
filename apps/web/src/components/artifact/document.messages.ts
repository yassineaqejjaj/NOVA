import type { ArtifactTypeDef, QualityCheck } from "@/lib/api/types";
import { defineMessages, type Lang } from "@/lib/i18n";
import { sectionTitle } from "@/lib/i18n/catalog";

export const M = defineMessages({
  en: {
    draft: "Draft",
    in_review: "In review",
    final: "Final",
    archived: "Archived",
    saving: "Saving…",
    conflict: "Changed elsewhere — reload to continue",
    lastUpdated: (v: { when: string }) => `Last updated ${v.when}`,
    qualityCheck: "Quality check",
    unavailable: "This Artifact is not available.",
    linkCopiedProject: (v: { project: string }) => `Link copied — visible to ${v.project} members.`,
    linkCopiedPrivate: "Link copied — this Artifact is private to you.",
    projects: "Projects",
    artifactTitle: "Artifact title",
    reload: "Reload",
    share: "Share",
    more: "More",
    markAs: (v: { status: string }) => `Mark as ${v.status}`,
    exportMarkdown: "Export Markdown",
    exportJson: "Export JSON",
    openWithConversation: "Open with conversation",
    forgeEvaluation: "FORGE evaluation",
    proposed: (v: { version: number }) => `NOVA proposed version ${v.version}.`,
    review: "Review",
    approve: "Approve",
    viewing: (v: { version: number; state: string }) => `Viewing version ${v.version} (${v.state}) — read-only.`,
    state_current: "current",
    state_proposed: "proposed",
    state_superseded: "superseded",
    state_rejected: "rejected",
    backToCurrent: "Back to current",
    tabWrite: "Write",
    tabReview: "Review",
    tabEvidence: "Evidence",
    context: "Context",
    sourcesCited: (v: { n: number }) => `source${v.n === 1 ? "" : "s"} cited`,
    contextRetrieved: (v: { when: string }) => `Context retrieved ${v.when}`,
    noContext: "No ORBIT context recorded",
    keyEvidence: "Key evidence",
    sourcesCount: (v: { n: number }) => `${v.n} source${v.n > 1 ? "s" : ""}`,
    noEvidence: "No cited evidence yet. Use “Ask NOVA → Add evidence” on a section.",
    comments: "Comments",
    noComments: "No comments yet. Add one from any section in Write.",
    sourcesTitle: "Sources cited in this Artifact",
    sourcesHint: "Recorded when NOVA wrote it — exactly what ORBIT served, never re-searched.",
    noSource: "No source cited.",
    excerpt: "“{text}”",
  },
  fr: {
    draft: "Brouillon",
    in_review: "En revue",
    final: "Final",
    archived: "Archivé",
    saving: "Enregistrement…",
    conflict: "Modifié ailleurs — rechargez pour continuer",
    lastUpdated: (v: { when: string }) => `Dernière mise à jour ${v.when}`,
    qualityCheck: "Contrôle qualité",
    unavailable: "Cet Artefact n’est pas disponible.",
    linkCopiedProject: (v: { project: string }) => `Lien copié — visible par les membres de ${v.project}.`,
    linkCopiedPrivate: "Lien copié — cet Artefact n’est visible que par vous.",
    projects: "Projets",
    artifactTitle: "Titre de l’Artefact",
    reload: "Recharger",
    share: "Partager",
    more: "Plus",
    markAs: (v: { status: string }) => `Marquer comme ${v.status.toLowerCase()}`,
    exportMarkdown: "Exporter en Markdown",
    exportJson: "Exporter en JSON",
    openWithConversation: "Ouvrir avec la conversation",
    forgeEvaluation: "Évaluation FORGE",
    proposed: (v: { version: number }) => `NOVA propose la version ${v.version}.`,
    review: "Examiner",
    approve: "Approuver",
    viewing: (v: { version: number; state: string }) => `Version ${v.version} (${v.state}) — lecture seule.`,
    state_current: "actuelle",
    state_proposed: "proposée",
    state_superseded: "remplacée",
    state_rejected: "rejetée",
    backToCurrent: "Revenir à la version actuelle",
    tabWrite: "Rédiger",
    tabReview: "Revue",
    tabEvidence: "Preuves",
    context: "Contexte",
    sourcesCited: (v: { n: number }) => `source${v.n > 1 ? "s" : ""} citée${v.n > 1 ? "s" : ""}`,
    contextRetrieved: (v: { when: string }) => `Contexte récupéré ${v.when}`,
    noContext: "Aucun contexte ORBIT enregistré",
    keyEvidence: "Preuves clés",
    sourcesCount: (v: { n: number }) => `${v.n} source${v.n > 1 ? "s" : ""}`,
    noEvidence: "Aucune preuve citée pour l’instant. Utilisez « Demander à NOVA → Ajouter des preuves » sur une section.",
    comments: "Commentaires",
    noComments: "Aucun commentaire pour l’instant. Ajoutez-en un depuis n’importe quelle section de l’onglet Rédiger.",
    sourcesTitle: "Sources citées dans cet Artefact",
    sourcesHint: "Enregistrées au moment où NOVA l’a rédigé — exactement ce qu’ORBIT a fourni, sans nouvelle recherche.",
    noSource: "Aucune source citée.",
    excerpt: "« {text} »",
  },
});

export const VERSION_STATES = ["current", "proposed", "superseded", "rejected"] as const;

const CHECK_LABELS_FR: Record<string, string> = {
  grounded: "Fondé sur des sources",
  unsupported: "Aucune affirmation non étayée",
  complete: "Toutes les sections rédigées",
  acceptance: "Les user stories ont des critères d’acceptation",
  forge: "Cohérent avec le contexte (FORGE)",
};

const EVALUATION_STATUS_FR: Record<string, string> = {
  pending: "en attente",
  queued: "en file d’attente",
  running: "en cours",
  completed: "terminée",
  failed: "échouée",
};

/** Status of a FORGE evaluation (English keeps the raw API value). */
export function evaluationStatusLabel(status: string, lang: Lang): string {
  return lang === "fr" ? (EVALUATION_STATUS_FR[status] ?? status) : status;
}

const s = (n: number) => (n > 1 ? "s" : "");

/** Server-side quality checks are computed in English; the known ones are localized by key, unknown text is kept. */
function checkDetailFr(check: QualityCheck, definition: ArtifactTypeDef): string {
  const d = check.detail;
  let m: RegExpMatchArray | null;
  if ((m = d.match(/^(\d+) sources? cited$/))) return `${m[1]!} source${s(+m[1]!)} citée${s(+m[1]!)}`;
  if (d === "Citations no longer resolvable") return "Citations introuvables";
  if (d === "No source cited") return "Aucune source citée";
  if (d === "Every citation matches a served source") return "Chaque citation correspond à une source fournie";
  if ((m = d.match(/^(\d+) unverifiable citation\(s\) removed by NOVA$/))) return `${m[1]!} citation${s(+m[1]!)} invérifiable${s(+m[1]!)} retirée${s(+m[1]!)} par NOVA`;
  if (d === "Complete") return "Complet";
  if ((m = d.match(/^(\d+) empty: (.*?)(…?)$/))) {
    const titles = m[2]!.split(", ").map((title) => {
      const section = definition.sections.find((x) => x.title === title);
      return section ? sectionTitle(definition, section, "fr") : title;
    });
    return `${m[1]!} vide${s(+m[1]!)} : ${titles.join(", ")}${m[3]!}`;
  }
  if ((m = d.match(/^(\d+) stories$/))) return `${m[1]!} user stor${+m[1]! > 1 ? "ies" : "y"}`;
  if ((m = d.match(/^(\d+) of (\d+) missing$/))) return `${m[1]!} sur ${m[2]!} sans critères`;
  if ((m = d.match(/^Score (\d+)$/))) return `Score ${m[1]!}`;
  if ((m = d.match(/^Evaluation (.+)$/))) return `Évaluation ${EVALUATION_STATUS_FR[m[1]!] ?? m[1]!}`;
  return d;
}

export function localizeCheck(check: QualityCheck, definition: ArtifactTypeDef, lang: Lang): { label: string; detail: string } {
  if (lang !== "fr") return { label: check.label, detail: check.detail };
  return { label: CHECK_LABELS_FR[check.key] ?? check.label, detail: checkDetailFr(check, definition) };
}
