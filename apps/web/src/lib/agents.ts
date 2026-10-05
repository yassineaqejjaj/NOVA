import { Code2, KanbanSquare, type LucideIcon, PenTool, Search, ShieldCheck, Target } from "lucide-react";

import type { Lang } from "@/lib/i18n";

/** NOVA's specialist sub-agents — one per user profile (`nova/domain/agents.py`). */
export type AgentProfile = "product" | "project" | "design" | "engineering";

export const AGENT_PROFILES: AgentProfile[] = ["product", "project", "design", "engineering"];

interface AgentDef {
  icon: LucideIcon;
  /** Identity color of the agent (avatar, rail). */
  color: string;
  name: Record<Lang, string>;
  short: Record<Lang, string>;
  /** Who this profile is, as offered in onboarding and Settings. */
  role: Record<Lang, string>;
  mission: Record<Lang, string>;
  /** Requests suggested on Home for this profile: a Skill and the request text. */
  suggestions: { skill: string; en: string; fr: string }[];
}

export const AGENTS: Record<AgentProfile, AgentDef> = {
  product: {
    icon: Target,
    color: "#f8485e",
    name: { en: "Product agent", fr: "Agent Produit" },
    short: { en: "Product", fr: "Produit" },
    role: { en: "Product Manager · Product Owner", fr: "Product Manager · Product Owner" },
    mission: {
      en: "Frames the value: problems, users, outcomes, strategy, priorities and requirements.",
      fr: "Cadre la valeur : problèmes, utilisateurs, résultats, stratégie, priorités et exigences.",
    },
    suggestions: [
      { skill: "prd", en: "Write a PRD for this feature", fr: "Rédige un PRD pour cette fonctionnalité" },
      { skill: "vision-to-backlog", en: "Turn the vision into a prioritized backlog", fr: "Transforme la vision en backlog priorisé" },
      { skill: "okr-definition", en: "Define OKRs for next quarter", fr: "Définis les OKR du prochain trimestre" },
      { skill: "sprint-planning", en: "Prepare my next sprint", fr: "Prépare mon prochain sprint" },
    ],
  },
  project: {
    icon: KanbanSquare,
    color: "#f59e0b",
    name: { en: "Project agent", fr: "Agent Projet" },
    short: { en: "Project", fr: "Projet" },
    role: { en: "Project Manager · Delivery Lead · Scrum Master", fr: "Chef de projet · Delivery Lead · Scrum Master" },
    mission: {
      en: "Orchestrates the delivery: scope, plans, milestones, risks, dependencies, roles and status.",
      fr: "Orchestre la livraison : périmètre, plans, jalons, risques, dépendances, rôles et avancement.",
    },
    suggestions: [
      { skill: "status-report", en: "Write the weekly status report", fr: "Rédige le rapport d’avancement de la semaine" },
      { skill: "raid-log", en: "Build the RAID log of the project", fr: "Construis le registre RAID du projet" },
      { skill: "project-charter", en: "Draft the project charter", fr: "Rédige la charte de projet" },
      { skill: "raci-matrix", en: "Clarify who does what with a RACI", fr: "Clarifie qui fait quoi avec une matrice RACI" },
    ],
  },
  design: {
    icon: PenTool,
    color: "#a78bfa",
    name: { en: "Design agent", fr: "Agent Design" },
    short: { en: "Design", fr: "Design" },
    role: { en: "Product Designer · UX/UI · UX Researcher", fr: "Product Designer · UX/UI · UX Researcher" },
    mission: {
      en: "Champions the user experience: research, journeys, interaction, content and usability.",
      fr: "Porte l’expérience utilisateur : recherche, parcours, interaction, contenus et utilisabilité.",
    },
    suggestions: [
      { skill: "design-brief", en: "Write the design brief for onboarding", fr: "Rédige le brief de design de l’onboarding" },
      { skill: "usability-test-plan", en: "Plan a usability test of the new flow", fr: "Prépare un test utilisateur du nouveau parcours" },
      { skill: "ux-writing", en: "Write the error and empty-state texts", fr: "Écris les textes d’erreur et d’états vides" },
      { skill: "design-review", en: "Review the checkout flow (heuristics and accessibility)", fr: "Fais la revue du parcours de paiement (heuristiques et accessibilité)" },
    ],
  },
  engineering: {
    icon: Code2,
    color: "#38bdf8",
    name: { en: "Engineering agent", fr: "Agent Ingénierie" },
    short: { en: "Engineering", fr: "Ingénierie" },
    role: { en: "Engineer · Tech Lead · Architect · QA", fr: "Développeur · Tech Lead · Architecte · QA" },
    mission: {
      en: "Secures the solution: architecture, interfaces, quality, reliability, security and estimates.",
      fr: "Sécurise la solution : architecture, interfaces, qualité, fiabilité, sécurité et estimations.",
    },
    suggestions: [
      { skill: "technical-design", en: "Write the technical design of this feature", fr: "Rédige la conception technique de cette fonctionnalité" },
      { skill: "api-design", en: "Specify the API endpoints", fr: "Spécifie les endpoints de l’API" },
      { skill: "effort-estimation", en: "Estimate the effort for this epic", fr: "Estime la charge de cet epic" },
      { skill: "test-strategy", en: "Write the test plan for the release", fr: "Rédige le plan de test de la release" },
    ],
  },
};

/** Agents of NOVA Core that serve every task (not profiles): context research and deliverable validation. */
export type SupportAgent = "research" | "validation";
export type AgentKey = AgentProfile | SupportAgent;

export const SUPPORT_AGENTS: Record<SupportAgent, { icon: LucideIcon; color: string; name: Record<Lang, string>; mission: Record<Lang, string> }> = {
  research: {
    icon: Search,
    color: "#14b8a6",
    name: { en: "Research agent", fr: "Agent Recherche" },
    mission: { en: "Finds the relevant project context in ORBIT, as you.", fr: "Trouve le contexte projet pertinent dans ORBIT, avec vos droits." },
  },
  validation: {
    icon: ShieldCheck,
    color: "#22c55e",
    name: { en: "Validation agent", fr: "Agent Validation" },
    mission: {
      en: "Verifies every deliverable against the Skill’s checks and criteria before NOVA hands it over.",
      fr: "Vérifie chaque livrable selon les contrôles et critères de la compétence avant que NOVA ne le remette.",
    },
  },
};

export function agentLook(key: AgentKey): { icon: LucideIcon; color: string; name: Record<Lang, string> } {
  return key in SUPPORT_AGENTS ? SUPPORT_AGENTS[key as SupportAgent] : AGENTS[key as AgentProfile];
}

export function agentOf(value: string | null | undefined): AgentProfile {
  return value && value in AGENTS ? (value as AgentProfile) : "product";
}

/** Avatar of a sub-agent: its icon on a tinted disc of its identity color. */
export function agentAvatarStyle(profile: AgentKey): { color: string; background: string; borderColor: string } {
  const color = agentLook(profile).color;
  return { color, background: `color-mix(in srgb, ${color} 14%, transparent)`, borderColor: `color-mix(in srgb, ${color} 35%, transparent)` };
}
