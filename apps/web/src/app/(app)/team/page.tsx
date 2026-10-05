"use client";

import { Skeleton } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { FileText, GraduationCap, Loader2 } from "lucide-react";
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

const M = defineMessages({
  en: {
    title: "Your product team",
    description: "You talk to NOVA. NOVA delegates to its specialists, checks their work and brings you the result.",
    partner: "Product partner",
    partnerHint: "Plans, delegates, supervises — your single point of contact",
    skills: (v: { n: number }) => `${v.n} Skills`,
    delivered: (v: { n: number }) => `${v.n} delivered (30 days)`,
    available: "Available",
    workingOn: "Working on",
    last: "Last deliverable",
    support: "Behind every task",
    checked: (v: { n: number; r: number }) => `${v.n} deliverables checked · ${v.r} revised`,
    research: (v: { n: number }) => `${v.n} tasks with project context`,
    training: "Training with FORGE",
  },
  fr: {
    title: "Votre équipe produit",
    description: "Vous parlez à NOVA. NOVA délègue à ses spécialistes, contrôle leur travail et vous apporte le résultat.",
    partner: "Partenaire produit",
    partnerHint: "Planifie, délègue, supervise — votre interlocuteur unique",
    skills: (v: { n: number }) => `${v.n} compétences`,
    delivered: (v: { n: number }) => `${v.n} livré${v.n > 1 ? "s" : ""} (30 jours)`,
    available: "Disponible",
    workingOn: "Travaille sur",
    last: "Dernier livrable",
    support: "Derrière chaque tâche",
    checked: (v: { n: number; r: number }) => `${v.n} livrable${v.n > 1 ? "s" : ""} contrôlé${v.n > 1 ? "s" : ""} · ${v.r} révisé${v.r > 1 ? "s" : ""}`,
    research: (v: { n: number }) => `${v.n} tâche${v.n > 1 ? "s" : ""} avec contexte projet`,
    training: "Entraînement avec FORGE",
  },
});

export default function TeamPage() {
  const t = useT(M);
  const lang = useLang();
  const { data } = useQuery({ queryKey: ["team"], queryFn: () => api.get<TeamData>("/team"), refetchInterval: 10_000 });
  const byId = new Map(data?.agents.map((a) => [a.id, a]));
  return (
    <Page>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Link href="/team/training" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface-2 px-3 text-[13px] hover:bg-surface-3">
            <GraduationCap className="size-4" aria-hidden /> {t("training")}
          </Link>
        }
      />
      <div className="flex flex-col items-center text-center">
        <NovaOrb state={data?.agents.some((a) => a.working.length) ? "working" : "idle"} size={96} />
        <div className="mt-2 text-[17px] font-semibold">NOVA</div>
        <div className="text-[13px] text-muted">{t("partner")}</div>
        <div className="text-[12px] text-subtle">{t("partnerHint")}</div>
      </div>
      <div aria-hidden className="mx-auto mt-4 h-6 w-px bg-border" />
      <div aria-hidden className="mx-auto hidden h-px w-3/4 bg-border sm:block" />
      {!data ? <Skeleton className="mt-6 h-48" /> : null}
      <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="team">
        {AGENT_PROFILES.map((p) => {
          const agent = AGENTS[p];
          const stats = byId.get(p);
          return (
            <li key={p} className="rounded-[16px] border border-border bg-surface p-4" data-agent={p}>
              <div className="flex items-center gap-2.5">
                <AgentAvatar profile={p} size={36} active={!!stats?.working.length} />
                <div className="min-w-0">
                  <div className="text-[14px] font-semibold" style={{ color: agent.color }}>{agent.name[lang]}</div>
                  <div className="text-[11.5px] text-subtle">{stats ? t("skills", { n: stats.skills }) : ""}</div>
                </div>
              </div>
              <p className="mt-2 text-[12.5px] text-muted">{agent.mission[lang]}</p>
              <div className="mt-3 border-t border-border pt-2 text-[12px]">
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
      <section className="mt-8">
        <h2 className="mb-2 text-[13px] font-medium uppercase tracking-wider text-subtle">{t("support")}</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {(["research", "validation"] as const).map((key) => (
            <div key={key} className="flex items-start gap-3 rounded-[14px] border border-border bg-surface p-3.5" data-agent={key}>
              <AgentAvatar profile={key} size={30} />
              <div>
                <div className="text-[13.5px] font-semibold" style={{ color: SUPPORT_AGENTS[key].color }}>{SUPPORT_AGENTS[key].name[lang]}</div>
                <p className="text-[12.5px] text-muted">{SUPPORT_AGENTS[key].mission[lang]}</p>
                {data ? <p className="mt-1 text-[12px] text-subtle">{key === "validation" ? t("checked", { n: data.support.validation.checked, r: data.support.validation.revised }) : t("research", { n: data.support.research.runs })}</p> : null}
              </div>
            </div>
          ))}
        </div>
      </section>
    </Page>
  );
}
