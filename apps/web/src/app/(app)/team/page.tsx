"use client";

import { Skeleton } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, FileText, GraduationCap, Loader2, RefreshCcw } from "lucide-react";
import Link from "next/link";

import { AgentAvatar } from "@/components/agents/sub-agents";
import { Page, PageHeader } from "@/components/shell/page";
import { NovaOrb } from "@/components/shell/nova-orb";
import { api } from "@/lib/api/client";
import { AGENT_PROFILES, AGENTS, type AgentProfile, SUPPORT_AGENTS } from "@/lib/agents";
import { defineMessages, useLang, useT } from "@/lib/i18n";

interface TeamData {
  agents: { id: AgentProfile; skills: number; delivered: number; working: { title: string; task_id: string; conversation_id: string | null; goal_id: string | null }[]; last: { title: string; artifact_id: string; at: string } | null }[];
  support: { validation: { checked: number; revised: number }; research: { runs: number } };
}

/** What each specialist is called on: the tasks and deliverables of its profile. */
const SPECIALTIES: Record<AgentProfile, { en: string[]; fr: string[] }> = {
  product: {
    en: ["PRD & requirements", "Vision & strategy", "OKRs & goals", "Backlog & priorities", "Sprint planning"],
    fr: ["PRD & exigences", "Vision & stratégie", "OKR & objectifs", "Backlog & priorités", "Sprint planning"],
  },
  project: {
    en: ["Status reports", "RAID log", "Project charter", "RACI & roles", "Plans & milestones"],
    fr: ["Rapports d’avancement", "Registre RAID", "Charte de projet", "RACI & rôles", "Plans & jalons"],
  },
  design: {
    en: ["Wireframes", "Lo-fi & hi-fi mockups", "Accessibility audit (WCAG 2.2)", "User research", "Figma", "Design briefs", "UX writing"],
    fr: ["Wireframes", "Maquettes lo-fi & hi-fi", "Audit d’accessibilité (WCAG 2.2)", "Recherche utilisateur", "Figma", "Briefs de design", "UX writing"],
  },
  engineering: {
    en: ["Technical design", "API specs", "Code from Figma", "Effort estimates", "Test strategy", "Security & reliability"],
    fr: ["Conception technique", "Specs d’API", "Code depuis Figma", "Estimations de charge", "Stratégie de test", "Sécurité & fiabilité"],
  },
};

const M = defineMessages({
  en: {
    title: "Your product team",
    description: "NOVA is not a single assistant: it is an orchestrator that coordinates a team of specialized agents, organized in layers.",
    you: "You",
    youHint: "You state a need, in plain words",
    layer: (v: { n: number }) => `Layer ${v.n}`,
    orchestration: "Orchestration",
    orchestrationHint: "The only agent you talk to. It frames the request, plans and drives everything below.",
    partner: "Product partner",
    duty1: "Understands & plans",
    duty2: "Delegates to specialists",
    duty3: "Supervises the work",
    duty4: "Assembles & hands over",
    context: "Context",
    contextHint: "Before any work starts, grounds the task in your real project data.",
    specialists: "Specialists",
    specialistsHint: "One agent per profile. Each one owns a field and the Skills that go with it.",
    quality: "Quality control",
    qualityHint: "Nothing reaches you unchecked. Failed checks send the work back to its specialist.",
    result: "Deliverable handed over by NOVA",
    skills: (v: { n: number }) => `${v.n} Skills`,
    delivered: (v: { n: number }) => `${v.n} delivered (30 days)`,
    available: "Available",
    workingOn: "Working on",
    last: "Last deliverable",
    handles: "Called on for",
    checked: (v: { n: number; r: number }) => `${v.n} deliverables checked · ${v.r} revised`,
    research: (v: { n: number }) => `${v.n} tasks with project context`,
    loop: "Revision loop",
    training: "Training with FORGE",
  },
  fr: {
    title: "Votre équipe produit",
    description: "NOVA n’est pas un assistant unique : c’est un orchestrateur qui coordonne une équipe d’agents spécialisés, organisée en couches.",
    you: "Vous",
    youHint: "Vous exprimez un besoin, en langage naturel",
    layer: (v: { n: number }) => `Couche ${v.n}`,
    orchestration: "Orchestration",
    orchestrationHint: "Le seul agent auquel vous parlez. Il cadre la demande, planifie et pilote tout ce qui suit.",
    partner: "Partenaire produit",
    duty1: "Comprend & planifie",
    duty2: "Délègue aux spécialistes",
    duty3: "Supervise le travail",
    duty4: "Assemble & remet",
    context: "Contexte",
    contextHint: "Avant tout travail, ancre la tâche dans les données réelles de votre projet.",
    specialists: "Spécialistes",
    specialistsHint: "Un agent par profil. Chacun maîtrise un domaine et les compétences qui vont avec.",
    quality: "Contrôle qualité",
    qualityHint: "Rien ne vous parvient sans vérification. Un contrôle raté renvoie le travail à son spécialiste.",
    result: "Livrable remis par NOVA",
    skills: (v: { n: number }) => `${v.n} compétences`,
    delivered: (v: { n: number }) => `${v.n} livré${v.n > 1 ? "s" : ""} (30 jours)`,
    available: "Disponible",
    workingOn: "Travaille sur",
    last: "Dernier livrable",
    handles: "Sollicité pour",
    checked: (v: { n: number; r: number }) => `${v.n} livrable${v.n > 1 ? "s" : ""} contrôlé${v.n > 1 ? "s" : ""} · ${v.r} révisé${v.r > 1 ? "s" : ""}`,
    research: (v: { n: number }) => `${v.n} tâche${v.n > 1 ? "s" : ""} avec contexte projet`,
    loop: "Boucle de révision",
    training: "Entraînement avec FORGE",
  },
});

function Connector({ label }: { label?: string }) {
  return (
    <div aria-hidden className="flex flex-col items-center py-1.5 text-subtle">
      <div className="h-3 w-px bg-border" />
      <ArrowDown className="size-3.5" />
      {label ? <span className="mt-0.5 text-[11px]">{label}</span> : null}
    </div>
  );
}

/** One layer of the system: a numbered label on the left, the agents of that layer on the right. */
function Layer({ n, title, hint, tone, children }: { n: number; title: string; hint: string; tone?: string; children: React.ReactNode }) {
  const t = useT(M);
  return (
    <section className="grid gap-3 md:grid-cols-[190px_1fr] md:gap-5" data-layer={n}>
      <div className="md:pt-3">
        <div className="text-[11px] font-medium uppercase tracking-wider" style={{ color: tone ?? "var(--subtle)" }}>{t("layer", { n })}</div>
        <h2 className="mt-0.5 text-[16px] font-semibold">{title}</h2>
        <p className="mt-1 text-[12.5px] leading-snug text-muted">{hint}</p>
      </div>
      <div>{children}</div>
    </section>
  );
}

export default function TeamPage() {
  const t = useT(M);
  const lang = useLang();
  const { data } = useQuery({ queryKey: ["team"], queryFn: () => api.get<TeamData>("/team"), refetchInterval: 10_000 });
  const byId = new Map(data?.agents.map((a) => [a.id, a]));
  const duties = [t("duty1"), t("duty2"), t("duty3"), t("duty4")];
  const working = !!data?.agents.some((a) => a.working.length);

  return (
    <Page wide>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Link href="/team/training" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface-2 px-3 text-[13px] hover:bg-surface-3">
            <GraduationCap className="size-4" aria-hidden /> {t("training")}
          </Link>
        }
      />

      {/* You */}
      <div className="flex flex-col items-center text-center">
        <div className="rounded-full border border-border bg-surface px-4 py-1.5 text-[13px] font-medium">{t("you")}</div>
        <div className="mt-1 text-[12px] text-subtle">{t("youHint")}</div>
      </div>
      <Connector />

      {/* 1 · Orchestration */}
      <Layer n={1} title={t("orchestration")} hint={t("orchestrationHint")} tone="var(--accent)">
        <div className="flex flex-col gap-4 rounded-[18px] border border-accent/30 bg-accent/[0.04] p-4 sm:flex-row sm:items-center">
          <div className="flex items-center gap-3 sm:w-[220px] sm:shrink-0">
            <NovaOrb state={working ? "working" : "idle"} size={64} />
            <div>
              <div className="text-[17px] font-semibold">NOVA</div>
              <div className="text-[12.5px] text-muted">{t("partner")}</div>
            </div>
          </div>
          <ol className="grid flex-1 gap-2 sm:grid-cols-2">
            {duties.map((d, i) => (
              <li key={d} className="flex items-center gap-2 rounded-[10px] bg-surface px-3 py-2 text-[12.5px]">
                <span className="grid size-5 shrink-0 place-items-center rounded-full bg-accent/10 text-[11px] font-semibold text-accent">{i + 1}</span>
                {d}
              </li>
            ))}
          </ol>
        </div>
      </Layer>
      <Connector />

      {/* 2 · Context */}
      <Layer n={2} title={t("context")} hint={t("contextHint")} tone={SUPPORT_AGENTS.research.color}>
        <SupportCard
          kind="research"
          stat={data ? t("research", { n: data.support.research.runs }) : null}
        />
      </Layer>
      <Connector />

      {/* 3 · Specialists */}
      <Layer n={3} title={t("specialists")} hint={t("specialistsHint")}>
        {!data ? <Skeleton className="h-48" /> : null}
        <ul className="grid gap-3 sm:grid-cols-2" data-testid="team">
          {AGENT_PROFILES.map((p) => {
            const agent = AGENTS[p];
            const stats = byId.get(p);
            return (
              <li key={p} className="flex flex-col rounded-[16px] border border-border bg-surface p-4" data-agent={p} style={{ borderTop: `3px solid ${agent.color}` }}>
                <div className="flex items-center gap-2.5">
                  <AgentAvatar profile={p} size={36} active={!!stats?.working.length} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[14px] font-semibold" style={{ color: agent.color }}>{agent.name[lang]}</div>
                    <div className="truncate text-[11.5px] text-subtle">{agent.role[lang]}</div>
                  </div>
                  <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted">{stats ? t("skills", { n: stats.skills }) : ""}</span>
                </div>
                <p className="mt-2.5 text-[12.5px] text-muted">{agent.mission[lang]}</p>
                <div className="mt-3">
                  <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-subtle">{t("handles")}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {SPECIALTIES[p][lang].map((s) => (
                      <span key={s} className="rounded-full border px-2 py-0.5 text-[11.5px]" style={{ color: agent.color, borderColor: `color-mix(in srgb, ${agent.color} 30%, transparent)`, background: `color-mix(in srgb, ${agent.color} 8%, transparent)` }}>{s}</span>
                    ))}
                  </div>
                </div>
                <div className="mt-auto border-t border-border pt-2 text-[12px] [margin-top:12px]">
                  {stats?.working.length ? (
                    <div className="space-y-1">
                      <div className="text-subtle">{t("workingOn")}</div>
                      {stats.working.slice(0, 2).map((w) => (
                        <Link key={w.task_id} href={w.conversation_id ? `/c/${w.conversation_id}` : `/work?task=${w.task_id}`} className="flex items-center gap-1.5 text-text hover:text-accent"><Loader2 className="size-3 animate-spin text-accent" /> <span className="truncate">{w.title}</span></Link>
                      ))}
                    </div>
                  ) : <div className="text-success">{t("available")}</div>}
                  {stats?.last ? (
                    <Link href={`/artifacts/${stats.last.artifact_id}`} className="mt-1.5 flex items-center gap-1.5 text-muted hover:text-accent"><FileText className="size-3" /> <span className="truncate">{t("last")} : {stats.last.title}</span></Link>
                  ) : null}
                  <div className="mt-1.5 text-subtle">{stats ? t("delivered", { n: stats.delivered }) : ""}</div>
                </div>
              </li>
            );
          })}
        </ul>
      </Layer>
      <Connector />

      {/* 4 · Quality */}
      <Layer n={4} title={t("quality")} hint={t("qualityHint")} tone={SUPPORT_AGENTS.validation.color}>
        <SupportCard
          kind="validation"
          stat={data ? t("checked", { n: data.support.validation.checked, r: data.support.validation.revised }) : null}
          badge={<span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted"><RefreshCcw className="size-3" />{t("loop")}</span>}
        />
      </Layer>
      <Connector />

      <div className="flex justify-center">
        <div className="flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-1.5 text-[13px] font-medium">
          <NovaOrb state="idle" size={20} />
          {t("result")}
        </div>
      </div>
    </Page>
  );
}

function SupportCard({ kind, stat, badge }: { kind: "research" | "validation"; stat: string | null; badge?: React.ReactNode }) {
  const lang = useLang();
  const a = SUPPORT_AGENTS[kind];
  return (
    <div className="flex items-start gap-3 rounded-[16px] border border-border bg-surface p-4" data-agent={kind} style={{ borderLeft: `3px solid ${a.color}` }}>
      <AgentAvatar profile={kind} size={36} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <div className="text-[14px] font-semibold" style={{ color: a.color }}>{a.name[lang]}</div>
          {badge}
        </div>
        <p className="mt-0.5 text-[12.5px] text-muted">{a.mission[lang]}</p>
        {stat ? <p className="mt-1 text-[12px] text-subtle">{stat}</p> : null}
      </div>
    </div>
  );
}
