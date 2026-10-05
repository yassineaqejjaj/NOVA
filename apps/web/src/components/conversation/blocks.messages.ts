import { defineMessages, type Lang } from "@/lib/i18n";

export const M = defineMessages({
  en: {
    next: "Next: {label}",
    novaWorking: "NOVA is working",
    novaDid: "What NOVA did",
    steps: (v: { n: number }) => `${v.n} step${v.n > 1 ? "s" : ""}`,
    plan: "Plan",
    stepsComplete: "{done} / {total} steps complete",
    open: "Open",
    assumptions: "Assumptions: {list}",
    proposedWorkflow: "Proposed workflow",
    workflowCancelled: "Workflow cancelled",
    workflow: "Workflow",
    moveUp: "Move up",
    moveDown: "Move down",
    removeStep: "Remove step",
    addSkill: "Add a Skill",
    addSkillPlaceholder: "Add a Skill…",
    cancel: "Cancel",
    runWorkflow: "Run workflow",
    needsInfo: "NOVA needs a little more information",
    continue: "Continue",
    usingContext: "Using context from ORBIT",
    flaggedHint: "Instruction-like text was found in this source; NOVA treated it strictly as data.",
    flagged: "flagged",
    viewInOrbit: "View in ORBIT",
    sourceExcluded: "This source will be excluded from your next request.",
    removeFromContext: "Remove from context",
    updatedAgo: "updated {when}",
    relevance: "relevance {pct}%",
    excludedByGovernance: (v: { n: number }) => `${v.n} item${v.n > 1 ? "s" : ""} excluded by ORBIT governance`,
    previousContext: "Previous context",
    contextPinned: "Context pinned to your next message.",
    reuse: "Reuse",
    refresh: "Refresh",
    refreshPrompt: "Refresh the context and update your answer.",
    awaitingApproval: "awaiting approval",
    created: "created",
    updatedSections: "updated {titles}",
    reviewChanges: "Review changes",
    openDocument: "Open document",
    reject: "Reject",
    approve: "Approve",
    retrying: "Retrying from the last completed step.",
    askOwner: "Ask a project owner in ORBIT to grant you access.",
    recordedSources: "Recorded sources",
    sources: "Sources",
    openArtifact: "Open the Artifact",
    excerpt: "“{text}”",
  },
  fr: {
    next: "Suite : {label}",
    novaWorking: "NOVA travaille",
    novaDid: "Ce que NOVA a fait",
    steps: (v: { n: number }) => `${v.n} étape${v.n > 1 ? "s" : ""}`,
    plan: "Plan",
    stepsComplete: (v: { done: number; total: number }) => `${v.done} / ${v.total} étape${v.total > 1 ? "s" : ""} terminée${v.total > 1 ? "s" : ""}`,
    open: "Ouvrir",
    assumptions: "Hypothèses : {list}",
    proposedWorkflow: "Workflow proposé",
    workflowCancelled: "Workflow annulé",
    workflow: "Workflow",
    moveUp: "Monter",
    moveDown: "Descendre",
    removeStep: "Supprimer l’étape",
    addSkill: "Ajouter une Skill",
    addSkillPlaceholder: "Ajouter une Skill…",
    cancel: "Annuler",
    runWorkflow: "Lancer le workflow",
    needsInfo: "NOVA a besoin de quelques précisions",
    continue: "Continuer",
    usingContext: "Contexte utilisé depuis ORBIT",
    flaggedHint: "Un texte ressemblant à une instruction a été détecté dans cette source ; NOVA l’a traité strictement comme une donnée.",
    flagged: "signalé",
    viewInOrbit: "Voir dans ORBIT",
    sourceExcluded: "Cette source sera exclue de votre prochaine demande.",
    removeFromContext: "Retirer du contexte",
    updatedAgo: "mis à jour {when}",
    relevance: "pertinence {pct} %",
    excludedByGovernance: (v: { n: number }) => `${v.n} élément${v.n > 1 ? "s" : ""} exclu${v.n > 1 ? "s" : ""} par la gouvernance ORBIT`,
    previousContext: "Contexte précédent",
    contextPinned: "Contexte épinglé à votre prochain message.",
    reuse: "Réutiliser",
    refresh: "Actualiser",
    refreshPrompt: "Actualisez le contexte et mettez à jour votre réponse.",
    awaitingApproval: "en attente de validation",
    created: "créé",
    updatedSections: "mis à jour : {titles}",
    reviewChanges: "Examiner les modifications",
    openDocument: "Ouvrir le document",
    reject: "Rejeter",
    approve: "Approuver",
    retrying: "Nouvelle tentative à partir de la dernière étape terminée.",
    askOwner: "Demandez à un responsable du projet dans ORBIT de vous accorder l’accès.",
    recordedSources: "Sources enregistrées",
    sources: "Sources",
    openArtifact: "Ouvrir l’Artefact",
    excerpt: "« {text} »",
  },
});

/** Approval statuses shown on a decided decision block (English keeps the raw API value). */
const STATUS_FR: Record<string, string> = {
  pending: "en attente",
  approved: "approuvé",
  rejected: "rejeté",
  expired: "expiré",
  cancelled: "annulé",
};

export function statusLabel(status: string, lang: Lang): string {
  return lang === "fr" ? (STATUS_FR[status] ?? status) : status;
}

/**
 * System labels generated in English by the API (phases, progress lines, notice titles, action buttons).
 * They are not user, LLM or ORBIT content, so they are shown in French when known; unknown labels pass through.
 */
const SYSTEM_FR: Record<string, string> = {
  // phases & progress lines
  "Understanding your request": "Analyse de votre demande",
  "Planning": "Planification",
  "Planning the work": "Planification du travail",
  "Retrieving context": "Récupération du contexte",
  "Looking up the sources": "Consultation des sources",
  "Using the provided context": "Utilisation du contexte fourni",
  "Executing": "Exécution",
  "Preparing the answer": "Préparation de la réponse",
  "Waiting for your approval": "En attente de votre validation",
  "Waiting for your answers": "En attente de vos réponses",
  "Waiting for you to confirm the workflow": "En attente de la confirmation du workflow",
  "Waiting for you": "En attente de votre retour",
  "Completed": "Terminé",
  "Cancelled": "Annulé",
  "Failed": "Échec",
  // notices & actions
  "NOVA couldn't finish this task": "NOVA n’a pas pu terminer cette tâche",
  "Retry": "Réessayer",
  "Reload": "Recharger",
  "Request access": "Demander l’accès",
  "Choose another source": "Choisir une autre source",
  "Choose a project": "Choisir un projet",
  "Reconnect ORBIT": "Reconnecter ORBIT",
  "Connect ORBIT": "Connecter ORBIT",
};

/** French label for a known API system label, or null when unknown. English always returns the label. */
export function knownSystemLabel(label: string, lang: Lang): string | null {
  if (lang === "en") return label;
  const running = /^Running (.+)$/.exec(label);
  if (running) return `Exécution de ${running[1]}`;
  return SYSTEM_FR[label] ?? null;
}

export function systemLabel(label: string, lang: Lang): string {
  return knownSystemLabel(label, lang) ?? label;
}
