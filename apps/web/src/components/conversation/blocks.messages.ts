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
    next: "Ensuite : {label}",
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
    addSkill: "Ajouter une compétence",
    addSkillPlaceholder: "Ajouter une compétence…",
    cancel: "Annuler",
    runWorkflow: "Lancer le workflow",
    needsInfo: "NOVA a besoin de quelques précisions",
    continue: "Continuer",
    usingContext: "Contexte ORBIT utilisé",
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
  approved: "approuvée",
  rejected: "rejetée",
  expired: "expirée",
  cancelled: "annulée",
};

export function statusLabel(status: string, lang: Lang): string {
  return lang === "fr" ? (STATUS_FR[status] ?? status) : status;
}

/** Localizes an English catalog name (Skill name, Artifact type name, section title); unknown names pass through. */
export type CatalogNames = (english: string) => string;
const same: CatalogNames = (name) => name;

/**
 * System text generated in English by the API (phases, progress lines and details, notice titles and messages,
 * action buttons, approval titles, failure messages, NOVA's own summaries). It is not user, LLM or ORBIT content,
 * so it is shown in French when known; unknown text passes through.
 */
const SYSTEM_FR: Record<string, string> = {
  // phases & progress lines
  "Understanding your request": "Analyse de votre demande",
  // NOVA Core: Validation agent, revisions, routing
  "Verifying the deliverable": "Vérification du livrable",
  "Revising after review": "Révision après relecture",
  "Checking the revision": "Vérification de la révision",
  "Revision requested": "Révision demandée",
  "Produces the requested deliverable": "Produit le livrable demandé",
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
  // progress details
  "No relevant context found": "Aucun contexte pertinent trouvé",
  "No change needed": "Aucune modification nécessaire",
  "No changes were needed": "Aucune modification n’était nécessaire",
  // notices & actions
  "NOVA couldn't finish this task": "NOVA n’a pas pu terminer cette tâche",
  "Retry": "Relancer",
  "Reload": "Recharger",
  "Request access": "Demander l’accès",
  "Choose another source": "Choisir une autre source",
  "Choose a project": "Choisir un projet",
  "Reconnect ORBIT": "Reconnecter ORBIT",
  "Connect ORBIT": "Connecter ORBIT",
  "No project selected": "Aucun projet sélectionné",
  "NOVA worked without project context. Choose a project to use ORBIT context.": "NOVA a travaillé sans contexte projet. Choisissez un projet pour utiliser le contexte ORBIT.",
  "NOVA couldn't access this project's context": "NOVA n’a pas pu accéder au contexte de ce projet",
  "ORBIT returned insufficient permissions.": "ORBIT a signalé des droits insuffisants.",
  "NOVA couldn't find this project in ORBIT": "NOVA n’a pas trouvé ce projet dans ORBIT",
  "The project does not exist or you are not a member.": "Le projet n’existe pas ou vous n’en êtes pas membre.",
  "Your ORBIT session has expired": "Votre session ORBIT a expiré",
  "Reconnect ORBIT to let NOVA use your project context.": "Reconnectez ORBIT pour que NOVA puisse utiliser le contexte de votre projet.",
  "ORBIT is not connected": "ORBIT n’est pas connecté",
  "Connect your ORBIT account so NOVA can use your project context.": "Connectez votre compte ORBIT pour que NOVA puisse utiliser le contexte de votre projet.",
  "ORBIT is unavailable": "ORBIT est indisponible",
  "NOVA continued without project context.": "NOVA a poursuivi sans contexte projet.",
  "ORBIT rejected the context request": "ORBIT a refusé la demande de contexte",
  // ORBIT errors (context errors shown on Home, Projects, Context)
  "ORBIT session expired": "La session ORBIT a expiré",
  "Insufficient permissions in ORBIT": "Droits insuffisants dans ORBIT",
  "Not found in ORBIT": "Introuvable dans ORBIT",
  "ORBIT is unreachable": "ORBIT est injoignable",
  "ORBIT did not return a session": "ORBIT n’a pas renvoyé de session",
  "ORBIT is not connected for this user": "ORBIT n’est pas connecté pour cet utilisateur",
  "This project is not linked to ORBIT.": "Ce projet n’est pas lié à ORBIT.",
  // classification warnings
  "This context includes C3 · Secret material. Outputs inherit this classification.": "Ce contexte contient des éléments C3 · Secret. Les résultats héritent de cette classification.",
  "This context includes C2 · Confidential material. Outputs inherit this classification.": "Ce contexte contient des éléments C2 · Confidentiel. Les résultats héritent de cette classification.",
  // approvals
  "Approve external change": "Valider la modification externe",
  // failures
  "No step to execute.": "Aucune étape à exécuter.",
  "No plan to execute.": "Aucun plan à exécuter.",
  "NOVA can't access the Artifact to update.": "NOVA ne peut pas accéder à l’Artefact à mettre à jour.",
  "NOVA can't access this Artifact.": "NOVA ne peut pas accéder à cet Artefact.",
  "Which element do you mean? Select it in the Artifact or quote it.": "De quel élément parlez-vous ? Sélectionnez-le dans l’Artefact ou citez-le.",
  "NOVA has no Skill for this request yet.": "NOVA n’a pas encore de compétence pour cette demande.",
  "The model could not produce a valid result.": "Le modèle n’a pas pu produire de résultat valide.",
  "The model returned no usable content.": "Le modèle n’a renvoyé aucun contenu exploitable.",
  "Something went wrong.": "Une erreur s’est produite.",
  "The inference server did not respond correctly. You can retry: NOVA resumes from the last completed step.": "Le serveur d’inférence n’a pas répondu correctement. Vous pouvez relancer : NOVA reprend à partir de la dernière étape terminée.",
  "A service NOVA depends on is unavailable. You can retry: completed steps are kept.": "Un service dont dépend NOVA est indisponible. Vous pouvez relancer : les étapes terminées sont conservées.",
  "Malformed response from inference server": "Réponse du serveur d’inférence mal formée",
  "Rejected by the user": "Refusé par l’utilisateur",
  "No project context: choose a project first": "Aucun contexte projet : choisissez d’abord un projet",
  "Artifact not found or not accessible": "Artefact introuvable ou inaccessible",
  // NOVA's own summaries (text blocks)
  "Workflow cancelled. Nothing was created.": "Workflow annulé. Rien n’a été créé.",
  "No Artifact was changed.": "Aucun Artefact n’a été modifié.",
  "_No ORBIT source was recorded for this element: it was proposed by NOVA from your request._": "_Aucune source ORBIT n’a été enregistrée pour cet élément : NOVA l’a proposé à partir de votre demande._",
};

/** Built-in tools (`nova/agent/tools/builtin.py`), shown on tool execution lines. */
const TOOLS_FR: Record<string, string> = {
  search_orbit: "recherche dans ORBIT",
  retrieve_orbit_context: "récupération du contexte ORBIT",
  get_artifact: "lecture d’un Artefact",
  list_artifacts: "liste des Artefacts",
  propose_orbit_decision: "proposition de décision dans ORBIT",
  publish_artifact_to_orbit: "publication de l’Artefact dans ORBIT",
};

export function toolLabel(tool: string, lang: Lang): string {
  return (lang === "fr" && TOOLS_FR[tool]) || tool.replaceAll("_", " ");
}

const plural = (n: number, one: string, other: string) => `${n} ${n > 1 ? other : one}`;
const s = (n: number) => (n > 1 ? "s" : "");
const list = (text: string, names: CatalogNames) => text.split(", ").map(names).join(", ");

type Pattern = [RegExp, (m: string[], names: CatalogNames) => string];

/** Parametrized system text (English template → French). */
const PATTERNS_FR: Pattern[] = [
  [/^Running (.+)$/, (m, names) => `Exécution de ${names(m[1]!)}`],
  [/^Updating (.+)$/, (m, names) => `Mise à jour : ${list(m[1]!, names)}`],
  [/^Update (.+)$/, (m, names) => `Mettre à jour : ${list(m[1]!, names)}`],
  [/^Using tools: (.+)$/, (m) => `Outils utilisés : ${m[1]!.split(", ").map((tool) => toolLabel(tool, "fr")).join(", ")}`],
  [/^(\d+) items?$/, (m) => plural(+m[1]!, "élément", "éléments")],
  [/^(\d+) sections?$/, (m) => plural(+m[1]!, "section", "sections")],
  [/^(\d+) unverifiable citation\(s\) removed$/, (m) => `${plural(+m[1]!, "citation invérifiable retirée", "citations invérifiables retirées")}`],
  [/^Saved v(\d+)$/, (m) => `v${m[1]!} enregistrée`],
  [/^Approved · (\d+)\/(\d+) checks$/, (m) => `Approuvé · ${m[1]!}/${m[2]!} contrôles`],
  [/^Approved after revision · (\d+)\/(\d+) checks$/, (m) => `Approuvé après révision · ${m[1]!}/${m[2]!} contrôles`],
  [/^Delivered with reservations · (\d+)\/(\d+) checks$/, (m) => `Livré avec réserves · ${m[1]!}/${m[2]!} contrôles`],
  [/^Requested with \/([a-z0-9-]+)$/, (m) => `Demandé avec /${m[1]!}`],
  [/^Proposed v(\d+)$/, (m) => `v${m[1]!} proposée`],
  [/^(\d+) sources? found$/, (m) => plural(+m[1]!, "source trouvée", "sources trouvées")],
  [/^(\d+) flagged as suspicious$/, (m) => `${m[1]!} signalée${s(+m[1]!)} comme suspecte${s(+m[1]!)}`],
  [/^(\d+) sources? provided$/, (m) => plural(+m[1]!, "source fournie", "sources fournies")],
  [/^(\d+) recorded sources?$/, (m) => plural(+m[1]!, "source enregistrée", "sources enregistrées")],
  [/^(\d+) steps?: (.+)$/, (m, names) => `${plural(+m[1]!, "étape", "étapes")} : ${m[2]!.split(" → ").map(names).join(" → ")}`],
  [/^Skill (.+) changed during execution; retry the task\.$/, (m) => `La compétence ${m[1]!} a changé pendant l’exécution ; relancez la tâche.`],
  [/^(.+): the model returned no content for '(.+)'\.$/, (m, names) => `${names(m[1]!)} : le modèle n’a renvoyé aucun contenu pour « ${names(m[2]!)} ».`],
  [/^ORBIT unavailable \((.+)\)$/, (m) => `ORBIT indisponible (${m[1]!})`],
  [/^ORBIT rejected the request \((.+)\)$/, (m) => `ORBIT a refusé la demande (${m[1]!})`],
  [/^ORBIT could not be reached \((.+)\)\. You can retry\.$/, (m, names) => `ORBIT n’a pas pu être joint (${frSystem(m[1]!, names) ?? m[1]!}). Vous pouvez relancer.`],
  [/^Apply changes to (.+)$/, (m) => `Appliquer les modifications à « ${m[1]!} »`],
  [
    /^NOVA proposes version (\d+) \((.*)\)\. Review and approve to make it current\.$/,
    (m, names) => `NOVA propose la version ${m[1]!} (${m[2] === "no section" ? "aucune section" : list(m[2]!, names)}). Examinez-la et approuvez-la pour qu’elle devienne la version courante.`,
  ],
  [/^Created \*\*(.+)\*\* \(v(\d+)\)\.$/, (m) => `Création de **${m[1]!}** (v${m[2]!}).`],
  [/^Updated \*\*(.+)\*\* \(v(\d+)\)\.$/, (m) => `Mise à jour de **${m[1]!}** (v${m[2]!}).`],
  [/^No change was needed to \*\*(.+)\*\* \(still v(\d+)\)\.$/, (m) => `Aucune modification nécessaire pour **${m[1]!}** (toujours en v${m[2]!}).`],
  [
    /^([\s\S]*?) ?(\d+) Artifact\(s\) produced before the failure were kept\.$/,
    (m, names) => {
      const n = +m[2]!;
      const kept = n > 1 ? `${n} Artefacts produits avant l’échec ont été conservés.` : `${n} Artefact produit avant l’échec a été conservé.`;
      return m[1] ? `${frSystem(m[1], names) ?? m[1]} ${kept}` : kept;
    },
  ],
  [/^Unknown tool '(.+)'$/, (m) => `Outil inconnu « ${m[1]!} »`],
  [/^Tool '(.+)' is not declared by this Skill$/, (m) => `L’outil « ${m[1]!} » n’est pas déclaré par cette compétence`],
  [/^Missing permission '(.+)' for tool '(.+)'$/, (m) => `Permission « ${m[1]!} » manquante pour l’outil « ${m[2]!} »`],
  [/^Inference server unreachable(.*)$/, (m) => `Serveur d’inférence injoignable${m[1]!}`],
  [/^Anthropic API unreachable(.*)$/, (m) => `API Anthropic injoignable${m[1]!}`],
  [/^Anthropic API error (.*)$/, (m) => `Erreur de l’API Anthropic ${m[1]!}`],
  [/^Malformed response from the Anthropic API$/, () => "Réponse mal formée de l’API Anthropic"],
  [/^No Anthropic API key configured \((.+)\)$/, (m) => `Aucune clé API Anthropic configurée (${m[1]!})`],
  [/^No model configured \((.+)\)$/, (m) => `Aucun modèle configuré (${m[1]!})`],
  [/^Inference server error (.*)$/, (m) => `Erreur du serveur d’inférence ${m[1]!}`],
  [/^The model did not return valid structured output: ([\s\S]*)$/, (m) => `Le modèle n’a pas renvoyé de sortie structurée valide : ${m[1]!}`],
];

function frSystem(text: string, names: CatalogNames): string | null {
  const exact = SYSTEM_FR[text];
  if (exact) return exact;
  for (const [pattern, render] of PATTERNS_FR) {
    const m = pattern.exec(text);
    if (m) return render([...m], names);
  }
  // Details combine parts ("3 items · 1 unverifiable citation(s) removed"): translate each known part.
  if (text.includes(" · ")) {
    const parts = text.split(" · ");
    const translated = parts.map((part) => frSystem(part, names));
    if (translated.some((part) => part !== null)) return translated.map((part, i) => part ?? parts[i]!).join(" · ");
  }
  const name = names(text);
  return name !== text ? name : null;
}

/**
 * French text for a known API system text, or null when unknown. English always returns the text.
 * `names` localizes the catalog names embedded in the text (Skill names, section titles).
 */
export function knownSystemLabel(label: string, lang: Lang, names: CatalogNames = same): string | null {
  if (lang === "en") return label;
  return frSystem(label, names);
}

export function systemLabel(label: string, lang: Lang, names: CatalogNames = same): string {
  return knownSystemLabel(label, lang, names) ?? label;
}

// Only NOVA's own summary lines are matched in Markdown, never free text that happens to look like a label.
const SUMMARY = [/^Created \*\*/, /^Updated \*\*/, /^No change was needed to \*\*/];

/** Markdown written by NOVA itself (e.g. "Created **PRD** (v1)."): known paragraphs are translated, the rest is kept. */
export function systemMarkdown(markdown: string, lang: Lang, names: CatalogNames = same): string {
  if (lang === "en") return markdown;
  return markdown
    .split("\n\n")
    .map((paragraph) => SYSTEM_FR[paragraph] ?? (SUMMARY.some((p) => p.test(paragraph)) ? frSystem(paragraph, names) : null) ?? paragraph)
    .join("\n\n");
}

/** Conversation titles are the user's words, except the API's default title. */
export function conversationTitle(title: string, lang: Lang): string {
  return lang === "fr" && title === "New conversation" ? "Nouvelle conversation" : title;
}

/** An answer to NOVA's question is the user's text, except the API's placeholder for an unanswered question. */
export function answerLabel(answer: string, lang: Lang): string {
  if (lang === "fr" && answer === "(not provided — make a reasonable assumption and state it)") return "(non renseigné — NOVA formule une hypothèse raisonnable)";
  return answer;
}
