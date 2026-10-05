"use client";

import { Badge, Button, cn, Popover, PopoverContent, PopoverTrigger, Skeleton, Tooltip } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  ExternalLink,
  FileText,
  Gauge,
  Orbit,
  Pause,
  Play,
  RotateCcw,
  Sparkles,
  Square,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/shell/page";
import { NovaOrb, ORB_LABEL } from "@/components/shell/nova-orb";
import { api } from "@/lib/api/client";
import { keys, useArtifactTypes, useSendIntent, useTask } from "@/lib/api/hooks";
import type { ArtifactSummary, OrbState, Recommendation, RecommendationAction, Today, WorkItem } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { useLang, useT } from "@/lib/i18n";
import { typeName } from "@/lib/i18n/catalog";
import { useVoiceAvailable } from "@/components/voice/voice-button";
import { useComposer, useUi } from "@/stores/ui";

import { M } from "./command-center.messages";

type T = ReturnType<typeof useT<(typeof M)["en"]>>;

// --- NOVA presence + daily brief ----------------------------------------------------------------

function stateSentence(state: OrbState, today: Today, t: T): string {
  const { running, waiting, results_ready } = today.brief;
  if (state === "working" || state === "thinking") return t("stateWorking", { n: running });
  if (state === "clarification") return t("stateClarification");
  if (state === "waiting") return t("stateWaiting", { n: waiting });
  if (state === "completed") return t("stateCompleted", { n: results_ready });
  return t("stateIdle");
}

function BriefTile({ value, label, tone, hint, onClick }: { value: number; label: string; tone: "accent" | "neutral" | "success" | "warning"; hint?: string; onClick?: () => void }) {
  const body = (
    <span className="flex items-baseline gap-2">
      <span
        className={cn(
          "text-[22px] font-semibold tabular-nums",
          value === 0 ? "text-subtle" : tone === "accent" ? "text-accent" : tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : "text-text",
        )}
      >
        {value}
      </span>
      <span className="text-[13px] text-muted">{label}</span>
    </span>
  );
  const className = "rounded-[14px] bg-surface/70 px-4 py-2.5 text-left backdrop-blur transition-colors";
  const element = onClick ? (
    <button onClick={onClick} className={cn(className, "hover:bg-surface")}>{body}</button>
  ) : (
    <div className={className}>{body}</div>
  );
  return hint ? <Tooltip content={hint}>{element}</Tooltip> : element;
}

export function Hero({ today, onScrollTo }: { today: Today; onScrollTo: (id: string) => void }) {
  const t = useT(M);
  const voice = useVoiceAvailable();
  const openVoice = useUi((s) => s.openVoice);
  const state = today.nova.state;
  const last = today.continue[0];
  const brief = today.brief;
  const [hello, setHello] = useState("");
  useEffect(() => {
    const h = new Date().getHours();
    setHello(t(h >= 5 && h < 12 ? "morning" : h >= 12 && h < 18 ? "afternoon" : "evening"));
  }, [t]);
  return (
    <section className="relative overflow-hidden rounded-[28px] bg-[radial-gradient(120%_140%_at_85%_10%,rgb(246_71_95/0.16),transparent_55%),linear-gradient(180deg,var(--surface),var(--surface-2))] px-6 py-7 md:px-9 md:py-8">
      <div className="flex flex-col-reverse gap-6 md:flex-row md:items-center">
        <div className="min-w-0 flex-1">
          <p className="text-[14px] text-muted">
            {hello}, {today.user.first_name}.
          </p>
          <h1 className="mt-1 text-[32px] font-semibold leading-[1.1] tracking-tight md:text-[40px]">
            {t("whatMatters")} <span className="text-accent">{t("today")}</span>
          </h1>
          <p className="mt-2 flex items-center gap-2 text-[14px] text-text/80" aria-live="polite">
            <span className={cn("size-2 rounded-full", state === "idle" ? "bg-success" : state === "waiting" || state === "clarification" ? "bg-warning" : "bg-accent")} />
            {stateSentence(state, today, t)}
          </p>
          <div className="mt-5 grid grid-cols-2 gap-2 xl:flex xl:flex-wrap" aria-label={t("yourDay")}>
            <BriefTile value={brief.actions_required} label={t("actionsRequired", { n: brief.actions_required })} tone="accent" onClick={() => onScrollTo("attention")} />
            <BriefTile value={brief.running + brief.paused} label={t("running")} tone="neutral" onClick={() => onScrollTo("working")} />
            <BriefTile value={brief.results_ready} label={t("resultsReady", { n: brief.results_ready })} tone="success" hint={t("resultsHint")} onClick={() => onScrollTo("results")} />
            <BriefTile
              value={brief.projects_at_risk.length}
              label={t("projectsAtRisk", { n: brief.projects_at_risk.length })}
              tone="warning"
              hint={
                brief.projects_at_risk.length
                  ? t("riskNamed", { names: brief.projects_at_risk.join(", ") })
                  : t("riskRule")
              }
            />
          </div>
          {last ? (
            <Button variant="primary" className="mt-5 rounded-full px-5" asChild>
              <Link href={`/c/${last.conversation_id}`}>
                {t("continueWhere")} <ArrowRight />
              </Link>
            </Button>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-center gap-3 md:pr-4">
          {voice ? (
            <button
              type="button"
              onClick={() => openVoice({ conversationId: null, projectId: useComposer.getState().projectId })}
              aria-label={t("talk")}
              className="group rounded-full outline-none transition-transform hover:scale-[1.03] focus-visible:ring-2 focus-visible:ring-accent"
            >
              <NovaOrb state={state} size={112} reflection title={`NOVA — ${ORB_LABEL[state]}`} />
            </button>
          ) : (
            <NovaOrb state={state} size={112} reflection title={`NOVA — ${ORB_LABEL[state]}`} />
          )}
          <span className="mt-3 rounded-full bg-surface/80 px-3 py-1 text-[12px] font-medium text-muted backdrop-blur">{ORB_LABEL[state]}</span>
        </div>
      </div>
    </section>
  );
}

// --- Ask NOVA suggestions ---------------------------------------------------------------------

const SUGGESTIONS = [
  { label: "sugSprint", text: "sugSprintText" },
  { label: "sugBacklog", text: "sugBacklogText" },
  { label: "sugPrd", text: null },
  { label: "sugRisks", text: "sugRisksText" },
] as const;

export function Suggestions() {
  const t = useT(M);
  const composer = useComposer();
  return (
    <div className="flex flex-wrap gap-2" aria-label={t("suggested")}>
      {SUGGESTIONS.map((s) => (
        <button
          key={s.label}
          onClick={() => {
            composer.setDraft(s.text ? t(s.text) : "/prd ");
            document.getElementById("nova-composer")?.focus();
          }}
          className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3.5 py-1.5 text-[13px] text-text/80 transition-colors hover:bg-accent-soft hover:text-accent"
        >
          <Sparkles className="size-3.5 opacity-60" /> {t(s.label)}
        </button>
      ))}
    </div>
  );
}

// --- Continue ---------------------------------------------------------------------------------

export function ContinueList({ items }: { items: Today["continue"] }) {
  const t = useT(M);
  if (!items.length) return null;
  return (
    <section aria-labelledby="continue-title">
      <h2 id="continue-title" className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-subtle">{t("continue")}</h2>
      <ul className="grid gap-2 sm:grid-cols-3">
        {items.map((c) => (
          <li key={c.conversation_id}>
            <Link href={`/c/${c.conversation_id}`} className="group block rounded-[16px] bg-surface-2/70 px-4 py-3 transition-colors hover:bg-surface-2">
              <span className="line-clamp-1 text-[14px] font-medium group-hover:text-accent">{c.title}</span>
              <span className="mt-0.5 block truncate text-[12px] text-subtle">{[c.project_name, t("lastActive", { when: timeAgo(c.updated_at) })].filter(Boolean).join(" · ")}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

// --- Priority 1: needs your attention ---------------------------------------------------------

function useRecommendationActions() {
  const t = useT(M);
  const router = useRouter();
  const client = useQueryClient();
  const send = useSendIntent();
  const dismiss = useMutation({
    mutationFn: (id: string) => api.post(`/today/dismiss`, { id }),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: keys.today });
      client.setQueryData<Today>(keys.today, (old) =>
        old ? { ...old, recommendations: old.recommendations.filter((r) => r.id !== id), brief: { ...old.brief, actions_required: Math.max(0, old.brief.actions_required - 1) } } : old,
      );
    },
    onSettled: () => client.invalidateQueries({ queryKey: keys.today }),
  });
  const run = async (rec: Recommendation, action: RecommendationAction) => {
    if (action.kind === "ignore") {
      dismiss.mutate(rec.id);
      toast(t("ignored"));
    } else if (action.kind === "review") {
      if (action.href.startsWith("http")) window.open(action.href, "_blank", "noopener");
      else router.push(action.href);
    } else if (action.kind === "retry") {
      await api.post(`/executions/${action.task_id}/retry`);
      toast(t("retrying"));
      if (rec.conversation_id) router.push(`/c/${rec.conversation_id}`);
    } else {
      const result = await send.mutateAsync({
        conversationId: null,
        payload: {
          text: action.prompt,
          project_id: rec.project_id ?? null,
          context_mode: "auto",
          pinned_context_ref_ids: [],
          excluded_context_refs: [],
          artifact_refs: action.artifact_id ? [action.artifact_id] : [],
          active_artifact_id: null,
          attachments: [],
        },
      });
      router.push(`/c/${result.conversation.id}`);
    }
  };
  return { run, pending: send.isPending };
}

function ActionButtons({ rec, run, pending, large }: { rec: Recommendation; run: (r: Recommendation, a: RecommendationAction) => void; pending: boolean; large?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {rec.actions.map((a, i) =>
        a.kind === "ignore" ? (
          <Button key={a.kind} variant="ghost" size="sm" className="text-subtle" onClick={() => run(rec, a)}>
            {a.label}
          </Button>
        ) : (
          <Button
            key={`${a.kind}-${i}`}
            variant={i === 0 && large ? "primary" : "secondary"}
            size={large ? "md" : "sm"}
            className="rounded-full"
            disabled={pending && a.kind === "fix"}
            onClick={() => run(rec, a)}
          >
            {a.kind === "fix" ? <Sparkles /> : a.kind === "retry" ? <RotateCcw /> : null}
            {a.label}
            {a.kind === "review" && "href" in a && a.href.startsWith("http") ? <ExternalLink /> : null}
          </Button>
        ),
      )}
    </div>
  );
}

function SourceIcon({ rec }: { rec: Recommendation }) {
  if (rec.risk) return <AlertTriangle className="size-4 text-warning" />;
  if (rec.source === "orbit") return <Orbit className="size-4 text-muted" />;
  return <Sparkles className="size-4 text-accent" />;
}

export function Attention({ items, loading }: { items: Recommendation[]; loading: boolean }) {
  const t = useT(M);
  const { run, pending } = useRecommendationActions();
  const [expanded, setExpanded] = useState(false);
  const [featured, ...rest] = items;
  const others = expanded ? rest : rest.slice(0, 3);
  return (
    <section id="attention" aria-labelledby="attention-title" className="scroll-mt-6">
      <h2 id="attention-title" className="mb-3 flex items-center gap-2 text-[17px] font-semibold tracking-tight">
        {t("needsAttention")}
        {items.length ? <span className="rounded-full bg-accent px-2 text-[12px] font-semibold leading-5 text-accent-fg">{items.length}</span> : null}
      </h2>
      {loading ? <Skeleton className="h-40 rounded-[22px]" /> : null}
      {!loading && !featured ? (
        <p className="flex items-center gap-2 rounded-[18px] bg-surface-2/60 px-5 py-4 text-[14px] text-muted">
          <Check className="size-4 text-success" /> {t("nothing")}
        </p>
      ) : null}
      <AnimatePresence initial={false}>
        {featured ? (
          <motion.article
            key={featured.id}
            layout
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, height: 0 }}
            className="rounded-[22px] bg-surface p-6 shadow-[0_18px_50px_-30px_rgb(0_0_0/0.3)] ring-1 ring-border"
          >
            <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-subtle">
              <SourceIcon rec={featured} />
              {featured.project_name ? <span className="font-medium text-text">{featured.project_name}</span> : null}
              <span>·</span>
              <span>{featured.context}</span>
              {featured.classification !== undefined && featured.classification !== null ? <ClassificationBadge level={featured.classification} /> : null}
              <span className="ml-auto">{timeAgo(featured.at)}</span>
            </div>
            <h3 className="mt-3 text-[21px] font-semibold leading-snug tracking-tight">{featured.title}</h3>
            {featured.subtitle && featured.subtitle !== featured.suggestion.replace(/\.$/, "") ? (
              <p className="mt-1 line-clamp-2 text-[14px] text-muted">{featured.subtitle}</p>
            ) : null}
            <p className="mt-4 flex items-start gap-2.5 rounded-[14px] bg-accent-soft/70 px-4 py-3 text-[14px] text-text/90">
              <NovaOrb size={18} className="mt-0.5" /> {featured.suggestion}
            </p>
            <div className="mt-4">
              <ActionButtons rec={featured} run={(r, a) => void run(r, a)} pending={pending} large />
            </div>
          </motion.article>
        ) : null}
      </AnimatePresence>
      {others.length ? (
        <ul className="mt-2 divide-y divide-border/70">
          {others.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-2 py-3">
              <SourceIcon rec={r} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] font-medium">{r.title}</div>
                <div className="truncate text-[12.5px] text-subtle">{[r.project_name, r.context, timeAgo(r.at)].filter(Boolean).join(" · ")}</div>
              </div>
              <ActionButtons rec={r} run={(rec, a) => void run(rec, a)} pending={pending} />
            </li>
          ))}
        </ul>
      ) : null}
      {rest.length > 3 ? (
        <button onClick={() => setExpanded(!expanded)} className="mt-1 px-2 text-[13px] text-muted hover:text-accent">
          {expanded ? t("showLess") : t("showMore", { n: rest.length - 3 })}
        </button>
      ) : null}
    </section>
  );
}

// --- Priority 2: NOVA is working on -----------------------------------------------------------

function elapsed(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

function useTaskControl() {
  const t = useT(M);
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "pause" | "continue" | "cancel" }) => api.post(`/executions/${id}/${action}`),
    onSuccess: (_, { action }) => {
      toast(t(action === "pause" ? "toastPause" : action === "continue" ? "toastContinue" : "toastStop"));
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: keys.today });
    },
  });
}

function WorkingRow({ task, now }: { task: WorkItem; now: number }) {
  const t = useT(M);
  const { data: detail } = useTask(task.id);
  const control = useTaskControl();
  const steps = detail?.steps ?? [];
  const current = steps.find((s) => s.status === "running" || s.status === "waiting_user") ?? steps.find((s) => s.status === "pending");
  const paused = task.status === "paused";
  const pct = task.progress_total ? Math.round((task.progress_done / task.progress_total) * 100) : 0;
  const state: OrbState = paused ? "idle" : task.status === "waiting_user" ? "waiting" : task.phase === "executing" ? "working" : "thinking";
  return (
    <li className="flex flex-wrap items-center gap-4 py-3.5">
      <NovaOrb state={state} size={28} />
      <div className="min-w-0 flex-1 basis-60">
        <div className="flex flex-wrap items-center gap-2">
          <Link href={task.conversation_id ? `/c/${task.conversation_id}` : `/work?task=${task.id}`} className="truncate text-[14.5px] font-medium hover:text-accent">
            {task.objective}
          </Link>
          {paused ? <Badge tone="warning">{t("paused")}</Badge> : null}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-subtle">
          {task.skills[0] ? <span className="inline-flex items-center gap-1"><Sparkles className="size-3.5" /> {task.skills.join(" → ")}</span> : null}
          <span className="inline-flex items-center gap-1"><CircleDot className="size-3.5" /> {paused ? t("pausedBefore") : current?.title ?? task.phase_label ?? t("starting")}</span>
          <span className="inline-flex items-center gap-1"><Clock3 className="size-3.5" /> {elapsed(task.created_at, now)}</span>
        </div>
        {task.progress_total ? (
          <div className="mt-2 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
              <motion.div className="h-full rounded-full bg-gradient-to-r from-[#f9a8bf] to-accent" initial={false} animate={{ width: `${Math.max(pct, 3)}%` }} />
            </div>
            <span className="text-[11.5px] tabular-nums text-subtle">{task.progress_done}/{task.progress_total}</span>
          </div>
        ) : null}
      </div>
      <div className="flex items-center gap-1">
        {paused ? (
          <Button variant="secondary" size="sm" className="rounded-full" onClick={() => control.mutate({ id: task.id, action: "continue" })} disabled={control.isPending}>
            <Play /> {t("resume")}
          </Button>
        ) : task.status === "running" || task.status === "queued" ? (
          <Tooltip content={t("pauseHint")}>
            <Button variant="ghost" size="sm" onClick={() => control.mutate({ id: task.id, action: "pause" })} disabled={control.isPending} aria-label={t("pause")}>
              <Pause /> {t("pause")}
            </Button>
          </Tooltip>
        ) : null}
        <Tooltip content={t("stopHint")}>
          <Button variant="ghost" size="icon" className="size-8 text-subtle" onClick={() => control.mutate({ id: task.id, action: "cancel" })} disabled={control.isPending} aria-label={t("stop")}>
            <Square className="!size-3.5" />
          </Button>
        </Tooltip>
      </div>
    </li>
  );
}

export function WorkingOn({ tasks }: { tasks: WorkItem[] }) {
  const t = useT(M);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const live = tasks.filter((t) => t.status !== "waiting_user");
  return (
    <section id="working" aria-labelledby="working-title" className="scroll-mt-6">
      <h2 id="working-title" className="mb-1 flex items-center gap-2 text-[15px] font-semibold tracking-tight">
        {t("workingOn")}
        <span className="text-[13px] font-normal text-subtle">{live.length || t("nothingNow")}</span>
      </h2>
      {live.length ? <ul className="divide-y divide-border/70">{live.map((t) => <WorkingRow key={t.id} task={t} now={now} />)}</ul> : null}
    </section>
  );
}

// --- Priority 3: recent results (timeline) ---------------------------------------------------

export function RecentResults({ artifacts }: { artifacts: ArtifactSummary[] }) {
  const t = useT(M);
  const lang = useLang();
  const { data: types } = useArtifactTypes();
  const defs = new Map(types?.map((d) => [d.type, d]));
  return (
    <section id="results" aria-labelledby="results-title" className="scroll-mt-6">
      <div className="mb-1 flex items-center justify-between">
        <h2 id="results-title" className="text-[15px] font-semibold tracking-tight">{t("recentResults")}</h2>
        <Link href="/artifacts" className="text-[12.5px] text-subtle hover:text-accent">{t("allResults")}</Link>
      </div>
      {artifacts.length ? (
        <ol className="relative ml-1.5 border-l border-border pl-4">
          {artifacts.map((a) => (
            <li key={a.id} className="relative py-2">
              <span className="absolute -left-[21px] top-3.5 size-2 rounded-full bg-border-strong" aria-hidden />
              <Link href={`/artifacts/${a.id}`} className="group flex items-baseline gap-2">
                <FileText className="size-3.5 shrink-0 translate-y-0.5 text-subtle" />
                <span className="truncate text-[13.5px] group-hover:text-accent">{a.title}</span>
                <span className="ml-auto shrink-0 text-[12px] text-subtle">{typeName(defs.get(a.type), lang, a.type_name)} · v{a.version} · {timeAgo(a.updated_at)}</span>
              </Link>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-[13.5px] text-subtle">{t("noResults")}</p>
      )}
    </section>
  );
}

// --- Background capabilities: ORBIT context, FORGE quality ------------------------------------

export function ContextStatus({ context }: { context: Today["context"] }) {
  const t = useT(M);
  if (!context.linked) {
    return (
      <Link href="/settings#orbit" className="block rounded-[18px] bg-surface-2/60 px-4 py-3.5 transition-colors hover:bg-surface-2">
        <div className="text-[11.5px] font-semibold uppercase tracking-wide text-subtle">{t("contextLabel")}</div>
        <div className="mt-1 flex items-center gap-2 text-[14px] font-medium">
          <Orbit className="size-4 text-subtle" /> {t("notLinked")}
        </div>
        <div className="mt-0.5 text-[12.5px] text-muted">{t("linkHint")} <ChevronRight className="inline size-3.5" /></div>
      </Link>
    );
  }
  const totals = context.totals;
  const total = totals.documents + totals.memory_items;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="block w-full rounded-[18px] bg-surface-2/60 px-4 py-3.5 text-left transition-colors hover:bg-surface-2">
          <div className="text-[11.5px] font-semibold uppercase tracking-wide text-subtle">{t("contextLabel")}</div>
          <div className="mt-1 flex items-center gap-2 text-[14px] font-medium">
            <Orbit className="size-4 text-accent" /> ORBIT · {context.error ? t("degraded") : t("connected")}
          </div>
          <div className="mt-0.5 text-[12.5px] text-muted">
            {t("sources", { n: total })}
            {context.projects.length > 1 ? t("acrossProjects", { n: context.projects.length }) : ""}
            {context.changes_24h ? t("updatedToday", { n: context.changes_24h }) : ""}
          </div>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80">
        <div className="text-[13px] font-semibold">{t("whatNovaCanUse")}</div>
        <dl className="mt-2 grid grid-cols-2 gap-2">
          {[
            [t("documents"), totals.documents],
            [t("memory"), totals.memory_items],
            [t("decisions"), totals.decisions],
            [t("sourcesLabel"), totals.sources],
          ].map(([label, value]) => (
            <div key={label as string} className="rounded-[10px] bg-surface-2 px-3 py-2">
              <dt className="text-[11.5px] text-subtle">{label}</dt>
              <dd className="text-[17px] font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        <ul className="mt-3 space-y-1">
          {context.projects.map((p) => (
            <li key={p.id} className="flex items-center justify-between text-[12.5px]">
              <Link href={`/projects/${p.id}`} className="truncate hover:text-accent">{p.name}</Link>
              <span className="text-subtle">{t("docsMemory", { docs: p.documents, memory: p.memory_items })}</span>
            </li>
          ))}
        </ul>
        {context.error ? <p className="mt-2 text-[12px] text-warning">{context.error}</p> : null}
        <Link href="/context" className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">
          {t("openContext")} <ArrowRight className="size-3.5" />
        </Link>
      </PopoverContent>
    </Popover>
  );
}

export function QualityStatus({ quality }: { quality: Today["quality"] }) {
  const t = useT(M);
  const last = quality.last_evaluation;
  return (
    <a
      href={last?.url ?? quality.url}
      target="_blank"
      rel="noreferrer"
      className="block rounded-[18px] bg-surface-2/60 px-4 py-3.5 transition-colors hover:bg-surface-2"
    >
      <div className="text-[11.5px] font-semibold uppercase tracking-wide text-subtle">{t("quality")}</div>
      <div className="mt-1 flex items-center gap-2 text-[14px] font-medium">
        <Gauge className={cn("size-4", quality.monitoring ? "text-accent" : "text-subtle")} /> FORGE · {quality.monitoring ? t("monitoring") : t("notConnected")}
      </div>
      <div className="mt-0.5 text-[12.5px] text-muted">
        {last?.score !== null && last?.score !== undefined
          ? t("lastEvaluation", { score: Math.round(last.score), when: timeAgo(last.at) })
          : last
            ? t("lastEvaluationStatus", { status: last.status ?? t("queued"), when: timeAgo(last.at) })
            : t("noEvaluation")}
      </div>
    </a>
  );
}
