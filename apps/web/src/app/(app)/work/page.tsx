"use client";

import { Badge, Button, cn, Skeleton, Tabs, TabsList, TabsTrigger } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { FileText, FlaskConical, ListTodo, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { AgentStack, SubAgents } from "@/components/agents/sub-agents";
import { evaluationStatusLabel } from "@/components/artifact/document.messages";
import { EmptyState, Page, PageHeader } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { useProjects, useSkills, useTask, useTasks } from "@/lib/api/hooks";
import type { SkillSummary, WorkItem } from "@/lib/api/types";
import { dateTime, duration, timeAgo } from "@/lib/format";
import { defineMessages, type Lang, useLang, useT } from "@/lib/i18n";
import { findSkill, skillName, useSystemLabel } from "@/lib/i18n/catalog";

const M = defineMessages({
  en: {
    status_queued: "Queued",
    status_scheduled: "Scheduled",
    status_running: "Running",
    status_waiting_user: "Waiting for you",
    status_paused: "Paused",
    status_completed: "Completed",
    status_failed: "Failed",
    status_cancelled: "Cancelled",
    scheduledFor: "scheduled for {date}",
    steps: (v: { done: number; total: number }) => `${v.done} / ${v.total} steps`,
    retrying: "Retrying from the last completed step.",
    cancelled: "Cancelled.",
    close: "Close",
    plan: "Plan",
    planLater: "The plan is created when the work starts.",
    noPlan: "No plan yet.",
    outputs: "Outputs",
    created: "Created",
    duration: "Duration",
    model: "Model",
    tokens: "Tokens",
    tokensValue: "{input} in · {output} out",
    traceId: "Trace ID",
    forgeEvaluation: "FORGE evaluation",
    evalQueued: "queued",
    passed: " · passed",
    notPassed: " · not passed",
    notEvaluated: "Not evaluated",
    openConversation: "Open conversation",
    retry: "Retry",
    cancel: "Cancel",
    empty_active: "NOVA has no active tasks.",
    empty_scheduled: "Nothing scheduled.",
    empty_completed: "Completed work will appear here.",
    empty_failed: "No failed work. Good.",
    emptyActiveHint: "Ask NOVA for something on Today.",
    title: "Work",
    description: "Everything NOVA is doing, has done, or will do for you.",
    tab_active: "Active",
    tab_scheduled: "Scheduled",
    tab_completed: "Completed",
    tab_failed: "Failed",
  },
  fr: {
    status_queued: "En file d’attente",
    status_scheduled: "Planifiée",
    status_running: "En cours",
    status_waiting_user: "En attente de votre retour",
    status_paused: "En pause",
    status_completed: "Terminée",
    status_failed: "Échec",
    status_cancelled: "Annulée",
    scheduledFor: "planifiée le {date}",
    steps: (v: { done: number; total: number }) => `${v.done} / ${v.total} étape${v.total > 1 ? "s" : ""}`,
    retrying: "Nouvelle tentative à partir de la dernière étape terminée.",
    cancelled: "Tâche annulée.",
    close: "Fermer",
    plan: "Plan",
    planLater: "Le plan est établi au démarrage du travail.",
    noPlan: "Pas encore de plan.",
    outputs: "Livrables",
    created: "Créée",
    duration: "Durée",
    model: "Modèle",
    tokens: "Tokens",
    tokensValue: "{input} en entrée · {output} en sortie",
    traceId: "ID de trace",
    forgeEvaluation: "Évaluation FORGE",
    evalQueued: "en file d’attente",
    passed: " · réussie",
    notPassed: " · non réussie",
    notEvaluated: "Non évaluée",
    openConversation: "Ouvrir la conversation",
    retry: "Relancer",
    cancel: "Annuler",
    empty_active: "NOVA n’a aucune tâche en cours.",
    empty_scheduled: "Rien de planifié.",
    empty_completed: "Le travail terminé apparaîtra ici.",
    empty_failed: "Aucun travail en échec. Parfait.",
    emptyActiveHint: "Demandez quelque chose à NOVA depuis l’Accueil.",
    title: "Tâches",
    description: "Tout ce que NOVA fait, a fait ou fera pour vous.",
    tab_active: "En cours",
    tab_scheduled: "Planifiées",
    tab_completed: "Terminées",
    tab_failed: "En échec",
  },
});

type Key = keyof typeof M.en;
type Tone = "accent" | "warning" | "success" | "danger" | "neutral";

const STATUS: Record<string, Tone> = {
  queued: "neutral",
  scheduled: "neutral",
  running: "accent",
  waiting_user: "warning",
  paused: "neutral",
  completed: "success",
  failed: "danger",
  cancelled: "neutral",
};

function useStatus() {
  const t = useT(M);
  return (status: string) => {
    const known = status in STATUS ? status : "queued";
    return { label: t(`status_${known}` as Key), tone: STATUS[known]! };
  };
}

/** The task's Skills (the API lists their English names), localized. */
const skillNames = (names: string[], skills: SkillSummary[] | undefined, lang: Lang) =>
  names.map((name) => { const skill = findSkill(skills, name); return skill ? skillName(skill, lang) : name; });

function WorkRow({ item, projectName, selected, onSelect }: { item: WorkItem; projectName?: string; selected: boolean; onSelect: () => void }) {
  const t = useT(M);
  const lang = useLang();
  const { data: skills } = useSkills();
  const s = useStatus()(item.status);
  return (
    <button onClick={onSelect} className={cn("flex w-full items-center gap-4 border-b border-border px-4 py-3 text-left transition-colors hover:bg-surface", selected && "bg-surface")}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] text-text">{item.objective}</div>
        <div className="mt-0.5 truncate text-[12px] text-subtle">
          {[projectName, skillNames(item.skills, skills, lang).join(" → ") || null, item.scheduled_for ? t("scheduledFor", { date: dateTime(item.scheduled_for) }) : timeAgo(item.created_at)].filter(Boolean).join(" · ")}
        </div>
      </div>
      {item.progress_total ? (
        <div className="hidden w-28 sm:block">
          <div className="h-1 overflow-hidden rounded-full bg-surface-3">
            <motion.div className="h-full bg-accent" initial={false} animate={{ width: `${(item.progress_done / item.progress_total) * 100}%` }} transition={{ duration: 0.25 }} />
          </div>
          <div className="mt-1 text-right text-[11px] text-subtle">{t("steps", { done: item.progress_done, total: item.progress_total })}</div>
        </div>
      ) : null}
      {item.steps?.length ? <span className="hidden md:inline-flex"><AgentStack steps={item.steps} taskStatus={item.status} size={18} /></span> : null}
      <Badge tone={s.tone}>{s.label}</Badge>
    </button>
  );
}

function WorkDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: task } = useTask(id);
  const router = useRouter();
  const client = useQueryClient();
  const t = useT(M);
  const lang = useLang();
  const label = useSystemLabel();
  const status = useStatus();
  const retry = useMutation({
    mutationFn: () => api.post(`/executions/${id}/retry`),
    onSuccess: () => { toast(t("retrying")); void client.invalidateQueries({ queryKey: ["tasks"] }); },
  });
  const cancel = useMutation({
    mutationFn: () => api.post(`/executions/${id}/cancel`),
    onSuccess: () => { toast(t("cancelled")); void client.invalidateQueries({ queryKey: ["tasks"] }); },
  });
  if (!task) return <div className="p-5"><Skeleton className="h-32 w-full" /></div>;
  const s = status(task.status);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b border-border px-5 py-4">
        <div className="min-w-0 flex-1">
          <Badge tone={s.tone}>{s.label}</Badge>
          <h2 className="mt-1.5 text-[15px] font-semibold leading-snug">{task.objective}</h2>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label={t("close")}><X /></Button>
      </div>
      <div className="flex-1 space-y-6 overflow-y-auto px-5 py-4 text-[13px]">
        <section>
          <h3 className="mb-2 text-[11.5px] font-medium uppercase tracking-wider text-subtle">{t("plan")}</h3>
          {task.steps?.length ? (
            <SubAgents steps={task.steps} taskStatus={task.status} live={["queued", "running"].includes(task.status)} onOpenArtifact={(artifactId) => router.push(`/artifacts/${artifactId}`)} />
          ) : <p className="text-subtle">{task.status === "scheduled" ? t("planLater") : t("noPlan")}</p>}
        </section>
        {task.artifacts?.length ? (
          <section>
            <h3 className="mb-2 text-[11.5px] font-medium uppercase tracking-wider text-subtle">{t("outputs")}</h3>
            {task.artifacts.map((a) => (
              <Link key={a.id} href={`/artifacts/${a.id}`} className="flex items-center gap-2 rounded-[10px] px-2 py-1.5 hover:bg-surface-2">
                <FileText className="size-3.5 text-accent" /> <span className="truncate">{a.title}</span> <Badge>v{a.version}</Badge>
              </Link>
            ))}
          </section>
        ) : null}
        <section className="grid grid-cols-2 gap-x-4 gap-y-2">
          <Meta label={t("created")} value={dateTime(task.created_at)} />
          <Meta label={t("duration")} value={duration(task.duration_seconds)} />
          <Meta label={t("model")} value={task.model ?? "—"} />
          <Meta label={t("tokens")} value={task.usage?.input_tokens != null ? t("tokensValue", { input: task.usage.input_tokens, output: task.usage.output_tokens ?? 0 }) : "—"} />
          <Meta label={t("traceId")} value={task.trace_id ?? "—"} mono />
          <Meta
            label={t("forgeEvaluation")}
            value={
              task.evaluation ? (
                <a href={task.evaluation.url ?? "#"} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                  <FlaskConical className="size-3" />
                  {task.evaluation.composite_score != null ? `${Math.round(task.evaluation.composite_score)} / 100` : task.evaluation.status ? evaluationStatusLabel(task.evaluation.status, lang) : t("evalQueued")}
                  {task.evaluation.passed != null ? (task.evaluation.passed ? t("passed") : t("notPassed")) : ""}
                </a>
              ) : t("notEvaluated")
            }
          />
        </section>
        {task.error ? <p className="rounded-[10px] bg-danger/[0.06] px-3 py-2 text-muted">{label(task.error)}</p> : null}
      </div>
      <div className="flex gap-2 border-t border-border px-5 py-3">
        {task.conversation_id ? <Button variant="secondary" size="sm" asChild><Link href={`/c/${task.conversation_id}`}>{t("openConversation")}</Link></Button> : null}
        {task.status === "failed" ? <Button size="sm" variant="primary" onClick={() => retry.mutate()} disabled={retry.isPending}>{t("retry")}</Button> : null}
        {["queued", "running", "waiting_user", "scheduled"].includes(task.status) ? <Button size="sm" variant="ghost" onClick={() => cancel.mutate()}>{t("cancel")}</Button> : null}
      </div>
    </div>
  );
}

function Meta({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-[11.5px] text-subtle">{label}</div>
      <div className={cn("truncate text-text", mono && "font-mono text-[11.5px]")}>{value}</div>
    </div>
  );
}

const TABS = ["active", "scheduled", "completed", "failed"] as const;

function WorkPage() {
  const params = useSearchParams();
  const router = useRouter();
  const t = useT(M);
  const [tab, setTab] = useState(params.get("tab") ?? "active");
  const selected = params.get("task");
  const { data: items, isLoading } = useTasks(tab);
  const { data: projects } = useProjects();
  const names = new Map(projects?.map((p) => [p.id, p.name]));
  const select = (id: string | null) => router.replace(id ? `/work?tab=${tab}&task=${id}` : `/work?tab=${tab}`, { scroll: false });

  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1">
        <Page wide>
          <PageHeader title={t("title")} description={t("description")} />
          <Tabs value={tab} onValueChange={(v) => { setTab(v); router.replace(`/work?tab=${v}`, { scroll: false }); }}>
            <TabsList>
              {TABS.map((v) => <TabsTrigger key={v} value={v}>{t(`tab_${v}`)}</TabsTrigger>)}
            </TabsList>
          </Tabs>
          <div className="mt-4 overflow-hidden rounded-[14px] border border-border">
            {isLoading ? <div className="space-y-2 p-4"><Skeleton className="h-10" /><Skeleton className="h-10" /></div> : null}
            {items?.map((item) => (
              <WorkRow key={item.id} item={item} projectName={item.project_id ? names.get(item.project_id) : undefined} selected={selected === item.id} onSelect={() => select(item.id)} />
            ))}
          </div>
          {items && items.length === 0 ? <div className="mt-4"><EmptyState icon={<ListTodo />} title={(TABS as readonly string[]).includes(tab) ? t(`empty_${tab}` as Key) : ""} description={tab === "active" ? t("emptyActiveHint") : undefined} /></div> : null}
        </Page>
      </div>
      <AnimatePresence>
        {selected ? (
          <motion.aside initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={{ duration: 0.2 }} className="sticky top-0 h-screen w-[400px] shrink-0 border-l border-border bg-background">
            <WorkDetail id={selected} onClose={() => select(null)} />
          </motion.aside>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export default function WorkRoute() {
  return <Suspense><WorkPage /></Suspense>;
}
