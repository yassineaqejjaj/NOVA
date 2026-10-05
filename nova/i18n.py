"""Server-generated interface text (Home, Timeline) in the user's language.

The language is the user's preference, else the browser's ``Accept-Language``. Content written by users,
ORBIT or the model is never translated here.
"""

from __future__ import annotations

from typing import Literal

Lang = Literal["en", "fr"]

MESSAGES: dict[str, dict[str, str]] = {
    # --- Home: actions -------------------------------------------------------------------------
    "ignore": {"en": "Ignore", "fr": "Ignorer"},
    "review": {"en": "Review", "fr": "Examiner"},
    "retry": {"en": "Retry", "fr": "Relancer"},
    "fix_with_nova": {"en": "Fix with NOVA", "fr": "Corriger avec NOVA"},
    "check_impact": {"en": "Check impact with NOVA", "fr": "Vérifier l’impact avec NOVA"},
    "check_affected": {"en": "Check affected work", "fr": "Voir le travail impacté"},
    "find_updates": {"en": "Find what to update", "fr": "Trouver quoi mettre à jour"},
    "resolve_in_orbit": {"en": "Resolve in ORBIT", "fr": "Résoudre dans ORBIT"},
    "refresh_with_nova": {"en": "Refresh with NOVA", "fr": "Actualiser avec NOVA"},
    # --- Home: ORBIT changes -------------------------------------------------------------------
    "s_new_version": {
        "en": "NOVA can check which of your artifacts are affected by the new version of “{subject}”.",
        "fr": "NOVA peut vérifier lesquels de vos artefacts sont impactés par la nouvelle version de « {subject} ».",
    },
    "p_new_version": {
        "en": 'Review the impact of the new version of "{subject}" on my work.',
        "fr": "Analyse l’impact de la nouvelle version de « {subject} » sur mon travail.",
    },
    "s_decision": {
        "en": "NOVA can list the artifacts this decision affects.",
        "fr": "NOVA peut lister les artefacts concernés par cette décision.",
    },
    "p_decision": {
        "en": 'Which of my artifacts are affected by the decision "{subject}"?',
        "fr": "Lesquels de mes artefacts sont concernés par la décision « {subject} » ?",
    },
    "s_superseded": {
        "en": "NOVA can tell you what to update now that it was superseded.",
        "fr": "NOVA peut vous dire quoi mettre à jour maintenant que c’est remplacé.",
    },
    "p_superseded": {
        "en": '"{subject}" was superseded. What should I update?',
        "fr": "« {subject} » a été remplacé. Que dois-je mettre à jour ?",
    },
    "s_conflict": {
        "en": "Two pieces of project knowledge contradict each other. Resolve it in ORBIT so NOVA uses the right one.",
        "fr": "Deux connaissances du projet se contredisent. Résolvez-le dans ORBIT pour que NOVA utilise la bonne.",
    },
    "s_stale": {
        "en": "NOVA can draft a refreshed version from the latest project context.",
        "fr": "NOVA peut rédiger une version actualisée à partir du contexte projet le plus récent.",
    },
    "p_stale": {"en": 'Help me refresh "{subject}".', "fr": "Aide-moi à actualiser « {subject} »."},
    # --- Home: NOVA's own state ----------------------------------------------------------------
    "ac_title_one": {"en": "1 story needs acceptance criteria", "fr": "1 story sans critères d’acceptation"},
    "ac_title_other": {"en": "{n} stories need acceptance criteria", "fr": "{n} stories sans critères d’acceptation"},
    "ac_context": {"en": "{type} · Backlog quality", "fr": "{type} · Qualité du backlog"},
    "ac_suggestion_one": {
        "en": "NOVA can generate acceptance criteria for this story.",
        "fr": "NOVA peut générer les critères d’acceptation de cette story.",
    },
    "ac_suggestion_other": {
        "en": "NOVA can generate acceptance criteria for these {n} stories.",
        "fr": "NOVA peut générer les critères d’acceptation de ces {n} stories.",
    },
    "ac_prompt": {
        "en": "/acceptance-criteria Complete the missing acceptance criteria of the referenced artifact.",
        "fr": "/acceptance-criteria Complète les critères d’acceptation manquants de l’artefact référencé.",
    },
    "wait_approval": {
        "en": "NOVA prepared changes and needs your approval",
        "fr": "NOVA a préparé des modifications et attend votre validation",
    },
    "wait_approval_action": {"en": "Review changes", "fr": "Examiner les modifications"},
    "wait_workflow": {
        "en": "NOVA proposed a workflow and waits for your go",
        "fr": "NOVA propose un workflow et attend votre feu vert",
    },
    "wait_workflow_action": {"en": "Review the plan", "fr": "Examiner le plan"},
    "wait_questions": {"en": "NOVA needs a clarification to continue", "fr": "NOVA a besoin d’une précision pour continuer"},
    "wait_questions_action": {"en": "Answer", "fr": "Répondre"},
    "wait_default": {"en": "NOVA is waiting for you", "fr": "NOVA vous attend"},
    "wait_default_action": {"en": "Continue", "fr": "Continuer"},
    "waiting_context": {"en": "Waiting for you", "fr": "En attente de vous"},
    "failed_subtitle": {"en": "The task stopped before the end.", "fr": "La tâche s’est arrêtée avant la fin."},
    "failed_context": {"en": "Didn't finish", "fr": "Inachevée"},
    "failed_suggestion": {
        "en": "NOVA can resume from the last completed step.",
        "fr": "NOVA peut reprendre à la dernière étape terminée.",
    },
    # --- Timeline ------------------------------------------------------------------------------
    "started_with": {"en": "NOVA started {skills}", "fr": "NOVA a démarré {skills}"},
    "started": {"en": "NOVA started working on your request", "fr": "NOVA a commencé à traiter votre demande"},
    "completed": {"en": "Completed", "fr": "Terminé"},
    "failed": {"en": "Failed", "fr": "Échec"},
    "cancelled": {"en": "Cancelled", "fr": "Annulé"},
    "paused": {"en": "Paused", "fr": "En pause"},
    "artifact_created": {"en": "{who} created {title} (v{version})", "fr": "{who} a créé {title} (v{version})"},
    "artifact_updated": {"en": "{who} updated {title} (v{version})", "fr": "{who} a mis à jour {title} (v{version})"},
    "artifact_proposed": {"en": "{who} proposed {title} (v{version})", "fr": "{who} a proposé {title} (v{version})"},
    "you": {"en": "You", "fr": "Vous"},
    "retrieved_one": {"en": "Retrieved {title}", "fr": "A récupéré {title}"},
    "retrieved_other": {"en": "Retrieved {n} context items", "fr": "A récupéré {n} éléments de contexte"},
    "and_more": {"en": "{shown} and {n} more", "fr": "{shown} et {n} autres"},
    "forge_evaluated": {"en": "FORGE evaluated the output", "fr": "FORGE a évalué le résultat"},
    "forge_queued": {"en": "FORGE evaluation queued", "fr": "Évaluation FORGE en file d’attente"},
    "score": {"en": "Score {score}", "fr": "Score {score}"},
    "passed": {"en": "passed", "fr": "réussi"},
    "decision_status": {"en": "Marked {title} as {status}", "fr": "{title} marqué comme {status}"},
    "decision_cancel_workflow": {"en": "Cancelled a proposed workflow", "fr": "Workflow proposé annulé"},
    "decision_confirm_workflow": {"en": "Confirmed a workflow", "fr": "Workflow confirmé"},
    "decision_approve": {"en": "Approved changes", "fr": "Modifications approuvées"},
    "decision_reject": {"en": "Rejected changes", "fr": "Modifications refusées"},
    "decision_other": {"en": "Answered an approval", "fr": "Demande de validation traitée"},
    "status_draft": {"en": "draft", "fr": "brouillon"},
    "status_in_review": {"en": "in review", "fr": "en revue"},
    "status_final": {"en": "final", "fr": "final"},
    "status_archived": {"en": "archived", "fr": "archivé"},
}


def resolve_lang(preference: str | None, accept_language: str | None = None) -> Lang:
    if preference in ("en", "fr"):
        return preference  # type: ignore[return-value]
    if accept_language and accept_language.strip().lower().startswith("fr"):
        return "fr"
    return "en"


def tr(lang: Lang, key: str, **values: object) -> str:
    entry = MESSAGES[key]
    text = entry.get(lang) or entry["en"]
    return text.format(**values) if values else text


def tr_count(lang: Lang, key: str, n: int, **values: object) -> str:
    """Picks ``<key>_one`` or ``<key>_other`` (French treats 0 and 1 as singular)."""
    one = n == 1 or (lang == "fr" and n == 0)
    return tr(lang, f"{key}_{'one' if one else 'other'}", n=n, **values)
