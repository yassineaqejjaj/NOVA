"use client";

import { Badge, Button, Skeleton } from "@nova/ui";
import { ArrowLeft, ExternalLink, GraduationCap, Loader2, RotateCcw, Sparkles, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AgentAvatar } from "@/components/agents/sub-agents";
import { Page, PageHeader } from "@/components/shell/page";
import { AGENT_PROFILES, AGENTS, type AgentProfile } from "@/lib/agents";
import {
  type AgentTraining,
  type CycleStatus,
  type CycleView,
  OPEN_CYCLE,
  type TrainingOverview,
  useActivatePolicy,
  useAgentTraining,
  useCancelCycle,
  useRollback,
  useStartAllTraining,
  useStartTraining,
  useTraining,
} from "@/lib/api/training";
import { dateTime, timeAgo } from "@/lib/format";
import { defineMessages, type Lang, useLang, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "Agent training",
    description:
      "FORGE evaluates each specialist on every one of its Skills. NOVA turns FORGE's feedback into lessons and applies them only once a FORGE experiment has validated them.",
    back: "Your team",
    trainAll: "Train every agent",
    train: "Train",
    training: "Training…",
    notConfigured: "Training is not configured. Missing settings:",
    autoPromote: (v: { days: number }) =>
      v.days > 0 ? `Automatic promotion when FORGE validates · one cycle every ${v.days} days` : "Automatic promotion when FORGE validates · manual cycles only",
    manualPromote: "FORGE-validated versions wait for an administrator",
    active: (v: { v: number }) => `Learned version v${v.v}`,
    noPolicy: "Not trained yet",
    lessons: (v: { n: number }) => `${v.n} lesson${v.n > 1 ? "s" : ""}`,
    score: "FORGE score",
    lastCycle: "Last cycle",
    current: "Current cycle",
    steps: "Baseline evaluation → Experiment → Decision",
    openForge: "Open in FORGE",
    cancel: "Cancel",
    standards: "Learned standards (all Skills)",
    noStandards: "No agent-wide lesson yet.",
    skills: "Skills",
    skill: "Skill",
    skillLessons: "Lessons",
    none: "—",
    history: "Training history",
    noHistory: "No training cycle yet.",
    versions: "Versions",
    rollback: "Restore previous version",
    apply: "Apply",
    advice: "FORGE advice outside the instructions",
    adviceHint: "Needs a change in NOVA itself (retrieval, tools, model…): shared with the team, not applied automatically.",
    scheduled: "scheduled",
    manual: "manual",
    delta: (v: { d: string }) => `${v.d} pts`,
    skillsCount: (v: { n: number }) => `${v.n} Skills`,
    confirmRollback: "Restore the previous learned version for this agent?",
  },
  fr: {
    title: "Entraînement des agents",
    description:
      "FORGE évalue chaque spécialiste sur chacune de ses compétences. NOVA transforme ses retours en leçons et ne les applique qu'après validation par une expérience FORGE.",
    back: "Votre équipe",
    trainAll: "Entraîner tous les agents",
    train: "Entraîner",
    training: "Entraînement…",
    notConfigured: "L'entraînement n'est pas configuré. Paramètres manquants :",
    autoPromote: (v: { days: number }) =>
      v.days > 0
        ? `Promotion automatique si FORGE valide · un cycle tous les ${v.days} jours`
        : "Promotion automatique si FORGE valide · cycles manuels uniquement",
    manualPromote: "Les versions validées par FORGE attendent un administrateur",
    active: (v: { v: number }) => `Version apprise v${v.v}`,
    noPolicy: "Pas encore entraîné",
    lessons: (v: { n: number }) => `${v.n} leçon${v.n > 1 ? "s" : ""}`,
    score: "Score FORGE",
    lastCycle: "Dernier cycle",
    current: "Cycle en cours",
    steps: "Évaluation de référence → Expérience → Décision",
    openForge: "Ouvrir dans FORGE",
    cancel: "Annuler",
    standards: "Standards appris (toutes les compétences)",
    noStandards: "Aucune leçon commune pour l'instant.",
    skills: "Compétences",
    skill: "Compétence",
    skillLessons: "Leçons",
    none: "—",
    history: "Historique d'entraînement",
    noHistory: "Aucun cycle d'entraînement pour l'instant.",
    versions: "Versions",
    rollback: "Rétablir la version précédente",
    apply: "Appliquer",
    advice: "Recommandations FORGE hors consignes",
    adviceHint: "Elles demandent une évolution de NOVA (recherche, outils, modèle…) : partagées avec l'équipe, non appliquées automatiquement.",
    scheduled: "planifié",
    manual: "manuel",
    delta: (v: { d: string }) => `${v.d} pts`,
    skillsCount: (v: { n: number }) => `${v.n} compétences`,
    confirmRollback: "Rétablir la version apprise précédente de cet agent ?",
  },
});

const STATUS: Record<CycleStatus, { tone: "neutral" | "accent" | "success" | "warning" | "danger"; en: string; fr: string }> = {
  queued: { tone: "neutral", en: "Queued", fr: "En file" },
  evaluating: { tone: "accent", en: "Baseline evaluation", fr: "Évaluation de référence" },
  experimenting: { tone: "accent", en: "Experiment running", fr: "Expérience en cours" },
  promoted: { tone: "success", en: "Promoted", fr: "Promue" },
  validated: { tone: "success", en: "Validated · awaiting approval", fr: "Validée · en attente" },
  rejected: { tone: "warning", en: "Not promoted", fr: "Non promue" },
  no_change: { tone: "neutral", en: "Nothing to learn", fr: "Rien à apprendre" },
  failed: { tone: "danger", en: "Failed", fr: "Échec" },
  cancelled: { tone: "neutral", en: "Cancelled", fr: "Annulé" },
};

const POLICY: Record<string, { en: string; fr: string }> = {
  active: { en: "active", fr: "active" },
  candidate: { en: "candidate", fr: "candidate" },
  retired: { en: "retired", fr: "retirée" },
  rejected: { en: "rejected", fr: "rejetée" },
};

/** FORGE composite scores are on a 0–100 scale. */
const pct = (v: number | null | undefined) => (typeof v === "number" ? v.toFixed(1) : "—");
const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}`;

function StatusBadge({ status, lang }: { status: CycleStatus; lang: Lang }) {
  const meta = STATUS[status];
  return (
    <Badge tone={meta.tone}>
      {OPEN_CYCLE.includes(status) ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
      {meta[lang]}
    </Badge>
  );
}

export default function TrainingPage() {
  return (
    <Suspense fallback={<Page wide><Skeleton className="h-64" /></Page>}>
      <Training />
    </Suspense>
  );
}

function Training() {
  const t = useT(M);
  const router = useRouter();
  const params = useSearchParams();
  const selected = (AGENT_PROFILES as string[]).includes(params.get("agent") ?? "") ? (params.get("agent") as AgentProfile) : "product";
  const { data } = useTraining();
  const startAll = useStartAllTraining();
  const canTrain = !!data?.can_manage && data.missing.length === 0;

  return (
    <Page wide>
      <Link href="/team" className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted hover:text-text">
        <ArrowLeft className="size-3.5" aria-hidden /> {t("back")}
      </Link>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          data?.can_manage ? (
            <Button variant="primary" size="sm" disabled={!canTrain || startAll.isPending} onClick={() => startAll.mutate()}>
              <GraduationCap className="size-4" aria-hidden /> {t("trainAll")}
            </Button>
          ) : null
        }
      />
      {data?.missing.length ? (
        <div role="status" className="mb-4 flex items-start gap-2 rounded-[12px] border border-warning/40 bg-warning/10 p-3 text-[13px]">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <span>
            {t("notConfigured")} <code className="text-[12px]">{data.missing.join(", ")}</code>
          </span>
        </div>
      ) : null}
      {data ? (
        <p className="mb-4 text-[12.5px] text-subtle">{data.auto_promote ? t("autoPromote", { days: data.interval_days }) : t("manualPromote")}</p>
      ) : null}

      {!data ? <Skeleton className="h-36" /> : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" role="tablist" aria-label={t("title")}>
        {data?.agents.map((a) => (
          <AgentCard key={a.agent} item={a} selected={a.agent === selected} canTrain={canTrain} onSelect={() => router.replace(`/team/training?agent=${a.agent}`, { scroll: false })} />
        ))}
      </div>

      <AgentDetail agent={selected} />
    </Page>
  );
}

function AgentCard({
  item,
  selected,
  canTrain,
  onSelect,
}: {
  item: TrainingOverview["agents"][number];
  selected: boolean;
  canTrain: boolean;
  onSelect: () => void;
}) {
  const t = useT(M);
  const lang = useLang();
  const start = useStartTraining();
  const agent = AGENTS[item.agent];
  const last = item.last_cycle;
  return (
    <div
      className={`rounded-[16px] border bg-surface p-4 transition-colors ${selected ? "border-accent" : "border-border hover:border-border-strong"}`}
      data-agent={item.agent}
    >
      <button type="button" role="tab" aria-selected={selected} onClick={onSelect} className="flex w-full items-center gap-2.5 text-left">
        <AgentAvatar profile={item.agent} size={34} active={item.training} />
        <span className="min-w-0">
          <span className="block text-[14px] font-semibold" style={{ color: agent.color }}>
            {agent.name[lang]}
          </span>
          <span className="block text-[11.5px] text-subtle">{t("skillsCount", { n: item.skills_count })}</span>
        </span>
      </button>
      <div className="mt-3 space-y-1 text-[12.5px]">
        <div className="font-medium">{item.active ? t("active", { v: item.active.version }) : t("noPolicy")}</div>
        {item.active ? (
          <div className="text-muted">
            {t("lessons", { n: item.active.lessons_count + item.active.standards_count })}
            {item.active.score !== null ? ` · ${t("score")} ${pct(item.active.score)}` : ""}
          </div>
        ) : null}
        {last ? (
          <div className="flex flex-wrap items-center gap-1.5 text-subtle">
            <StatusBadge status={last.status} lang={lang} /> {timeAgo(last.created_at)}
          </div>
        ) : null}
      </div>
      {canTrain ? (
        <Button className="mt-3 w-full" size="sm" disabled={item.training || start.isPending} onClick={() => start.mutate(item.agent)}>
          {item.training ? (
            <>
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> {t("training")}
            </>
          ) : (
            t("train")
          )}
        </Button>
      ) : null}
    </div>
  );
}

function skillLabel(skill: AgentTraining["skills"][number], lang: Lang) {
  return skill.translations?.[lang]?.name || skill.name;
}

function AgentDetail({ agent }: { agent: AgentProfile }) {
  const t = useT(M);
  const lang = useLang();
  const { data } = useAgentTraining(agent);
  const rollback = useRollback();
  const activate = useActivatePolicy();
  if (!data) return <Skeleton className="mt-6 h-72" />;
  const open = data.cycles.find((c) => OPEN_CYCLE.includes(c.status));
  const names = new Map(data.skills.map((s) => [s.id, skillLabel(s, lang)]));
  const advice = data.policies.find((p) => p.recommendations?.length)?.recommendations ?? [];

  return (
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]" role="tabpanel" aria-label={AGENTS[agent].name[lang]}>
      <div className="min-w-0 space-y-5">
        {open ? <CurrentCycle cycle={open} canManage={data.can_manage} /> : null}

        <section className="rounded-[16px] border border-border bg-surface p-4">
          <h2 className="mb-2 text-[13px] font-semibold">{t("standards")}</h2>
          {data.active?.standards?.length ? (
            <ul className="list-disc space-y-1 pl-5 text-[13px]">
              {data.active.standards.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-muted">{t("noStandards")}</p>
          )}
        </section>

        <section className="rounded-[16px] border border-border bg-surface">
          <h2 className="border-b border-border px-4 py-3 text-[13px] font-semibold">{t("skills")}</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-[11.5px] uppercase tracking-wider text-subtle">
                  <th scope="col" className="px-4 py-2 font-medium">{t("skill")}</th>
                  <th scope="col" className="px-2 py-2 font-medium">{t("score")}</th>
                  <th scope="col" className="px-4 py-2 font-medium">{t("skillLessons")}</th>
                </tr>
              </thead>
              <tbody>
                {data.skills.map((s) => (
                  <tr key={s.id} className="border-t border-border align-top">
                    <td className="px-4 py-2 font-medium">{skillLabel(s, lang)}</td>
                    <td className="px-2 py-2 tabular-nums text-muted">{pct(s.score)}</td>
                    <td className="px-4 py-2 text-muted">
                      {s.lessons.length ? (
                        <ul className="space-y-0.5">
                          {s.lessons.map((l) => (
                            <li key={l}>· {l}</li>
                          ))}
                        </ul>
                      ) : (
                        t("none")
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {advice.length ? (
          <section className="rounded-[16px] border border-border bg-surface p-4">
            <h2 className="text-[13px] font-semibold">{t("advice")}</h2>
            <p className="mb-2 text-[12px] text-subtle">{t("adviceHint")}</p>
            <ul className="space-y-1 text-[13px]">
              {advice.slice(0, 8).map((r, i) => (
                <li key={`${r.skill_id}-${i}`}>
                  <span className="text-subtle">{names.get(r.skill_id) ?? r.skill_id} · {r.category} — </span>
                  {r.title}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>

      <aside className="space-y-5">
        <section className="rounded-[16px] border border-border bg-surface p-4">
          <h2 className="mb-2 text-[13px] font-semibold">{t("history")}</h2>
          {data.cycles.length === 0 ? <p className="text-[13px] text-muted">{t("noHistory")}</p> : null}
          <ol className="space-y-3">
            {data.cycles.map((c) => (
              <li key={c.id} className="text-[12.5px]">
                <div className="flex flex-wrap items-center gap-1.5">
                  <StatusBadge status={c.status} lang={lang} />
                  <span className="text-subtle">
                    {dateTime(c.created_at)} · {c.trigger === "scheduled" ? t("scheduled") : t("manual")}
                  </span>
                </div>
                {c.result.decision?.reason || c.error ? <p className="mt-0.5 text-muted">{c.error ?? c.result.decision?.reason}</p> : null}
                {typeof c.result.experiment?.delta === "number" ? (
                  <p className="text-muted">
                    v{c.baseline_version} → v{c.candidate_version} · {t("delta", { d: signed(c.result.experiment.delta) })}
                  </p>
                ) : null}
                {c.experiment_url ? (
                  <a href={c.experiment_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                    {t("openForge")} <ExternalLink className="size-3" aria-hidden />
                  </a>
                ) : null}
              </li>
            ))}
          </ol>
        </section>

        <section className="rounded-[16px] border border-border bg-surface p-4">
          <h2 className="mb-2 text-[13px] font-semibold">{t("versions")}</h2>
          <ul className="space-y-2 text-[12.5px]">
            {data.policies.map((p) => (
              <li key={p.id} className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium">
                    v{p.version}{" "}
                    <span className="font-normal text-subtle">· {POLICY[p.status]?.[lang] ?? p.status}{p.score !== null ? ` · ${pct(p.score)}` : ""}</span>
                  </div>
                  <div className="truncate text-muted">{p.summary}</div>
                </div>
                {data.can_manage && p.status === "retired" ? (
                  <Button size="sm" variant="ghost" disabled={activate.isPending} onClick={() => activate.mutate(p.id)}>
                    {t("apply")}
                  </Button>
                ) : null}
                {data.can_manage && p.status === "candidate" && data.cycles.some((c) => c.status === "validated" && c.candidate_version === p.version) ? (
                  <Button size="sm" variant="primary" disabled={activate.isPending} onClick={() => activate.mutate(p.id)}>
                    <Sparkles className="size-3.5" aria-hidden /> {t("apply")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          {data.can_manage && data.active?.parent_id ? (
            <Button
              className="mt-3 w-full"
              size="sm"
              variant="outline"
              disabled={rollback.isPending}
              onClick={() => {
                if (window.confirm(t("confirmRollback"))) rollback.mutate(agent);
              }}
            >
              <RotateCcw className="size-3.5" aria-hidden /> {t("rollback")}
            </Button>
          ) : null}
        </section>
      </aside>
    </div>
  );
}

function CurrentCycle({ cycle, canManage }: { cycle: CycleView; canManage: boolean }) {
  const t = useT(M);
  const lang = useLang();
  const cancel = useCancelCycle();
  return (
    <section className="rounded-[16px] border border-accent/40 bg-accent/5 p-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold">
          {t("current")} <StatusBadge status={cycle.status} lang={lang} />
        </h2>
        <div className="flex items-center gap-2">
          {cycle.experiment_url ? (
            <a href={cycle.experiment_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12.5px] text-accent hover:underline">
              {t("openForge")} <ExternalLink className="size-3" aria-hidden />
            </a>
          ) : null}
          {canManage ? (
            <Button size="sm" variant="ghost" disabled={cancel.isPending} onClick={() => cancel.mutate(cycle.id)}>
              {t("cancel")}
            </Button>
          ) : null}
        </div>
      </div>
      <p className="mt-1 text-[12.5px] text-muted">
        {t("steps")} · {t("skillsCount", { n: cycle.skills_count })} · {timeAgo(cycle.created_at)}
      </p>
    </section>
  );
}
