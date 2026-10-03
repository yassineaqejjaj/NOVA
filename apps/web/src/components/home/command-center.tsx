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
import { keys, useSendIntent, useTask } from "@/lib/api/hooks";
import type { ArtifactSummary, OrbState, Recommendation, RecommendationAction, Today, WorkItem } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { useComposer } from "@/stores/ui";

// --- NOVA presence + daily brief ----------------------------------------------------------------

function stateSentence(state: OrbState, today: Today): string {
  const { running, waiting, results_ready } = today.brief;
  if (state === "working" || state === "thinking") return `NOVA is working on ${running} task${running > 1 ? "s" : ""}`;
  if (state === "clarification") return "NOVA needs a clarification from you";
  if (state === "waiting") return `NOVA is waiting for you on ${waiting} task${waiting > 1 ? "s" : ""}`;
  if (state === "completed") return `NOVA finished ${results_ready} task${results_ready > 1 ? "s" : ""} today`;
  return "NOVA is ready";
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
  const state = today.nova.state;
  const last = today.continue[0];
  const brief = today.brief;
  const [hello, setHello] = useState("Hello");
  useEffect(() => {
    const h = new Date().getHours();
    setHello(h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening");
  }, []);
  return (
    <section className="relative overflow-hidden rounded-[28px] bg-[radial-gradient(120%_140%_at_85%_10%,rgb(246_71_95/0.16),transparent_55%),linear-gradient(180deg,var(--surface),var(--surface-2))] px-6 py-7 md:px-9 md:py-8">
      <div className="flex flex-col-reverse gap-6 md:flex-row md:items-center">
        <div className="min-w-0 flex-1">
          <p className="text-[14px] text-muted">
            {hello}, {today.user.first_name}.
          </p>
          <h1 className="mt-1 text-[32px] font-semibold leading-[1.1] tracking-tight md:text-[40px]">
            Here&apos;s what matters <span className="text-accent">today.</span>
          </h1>
          <p className="mt-2 flex items-center gap-2 text-[14px] text-text/80" aria-live="polite">
            <span className={cn("size-2 rounded-full", state === "idle" ? "bg-success" : state === "waiting" || state === "clarification" ? "bg-warning" : "bg-accent")} />
            {stateSentence(state, today)}
          </p>
          <div className="mt-5 grid grid-cols-2 gap-2 xl:flex xl:flex-wrap" aria-label="Your day">
            <BriefTile value={brief.actions_required} label={brief.actions_required === 1 ? "action required" : "actions required"} tone="accent" onClick={() => onScrollTo("attention")} />
            <BriefTile value={brief.running + brief.paused} label="running" tone="neutral" onClick={() => onScrollTo("working")} />
            <BriefTile value={brief.results_ready} label={brief.results_ready === 1 ? "result ready" : "results ready"} tone="success" hint="Tasks completed in the last 24 hours" onClick={() => onScrollTo("results")} />
            <BriefTile
              value={brief.projects_at_risk.length}
              label={brief.projects_at_risk.length === 1 ? "project at risk" : "projects at risk"}
              tone="warning"
              hint={
                brief.projects_at_risk.length
                  ? `${brief.projects_at_risk.join(", ")} — a task failed recently or ORBIT found contradicting knowledge`
                  : "A project is at risk when a task failed recently or ORBIT finds contradicting knowledge"
              }
            />
          </div>
          {last ? (
            <Button variant="primary" className="mt-5 rounded-full px-5" asChild>
              <Link href={`/c/${last.conversation_id}`}>
                Continue where you left off <ArrowRight />
              </Link>
            </Button>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-center gap-3 md:pr-4">
          <NovaOrb state={state} size={112} reflection title={`NOVA — ${ORB_LABEL[state]}`} />
          <span className="mt-3 rounded-full bg-surface/80 px-3 py-1 text-[12px] font-medium text-muted backdrop-blur">{ORB_LABEL[state]}</span>
        </div>
      </div>
    </section>
  );
}

// --- Ask NOVA suggestions ---------------------------------------------------------------------

const SUGGESTIONS = [
  { label: "Prepare my next sprint", text: "/sprint-planning Prepare my next sprint." },
  { label: "Review my backlog", text: "/backlog-refinement Review my backlog and tell me what to fix first." },
  { label: "Create a PRD", text: "/prd " },
  { label: "Summarize project risks", text: "/risk-analysis Summarize the current risks of this project." },
];

export function Suggestions() {
  const composer = useComposer();
  return (
    <div className="flex flex-wrap gap-2" aria-label="Suggested requests">
      {SUGGESTIONS.map((s) => (
        <button
          key={s.label}
          onClick={() => {
            composer.setDraft(s.text);
            document.getElementById("nova-composer")?.focus();
          }}
          className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3.5 py-1.5 text-[13px] text-text/80 transition-colors hover:bg-accent-soft hover:text-accent"
        >
          <Sparkles className="size-3.5 opacity-60" /> {s.label}
        </button>
      ))}
    </div>
  );
}

// --- Continue ---------------------------------------------------------------------------------

export function ContinueList({ items }: { items: Today["continue"] }) {
  if (!items.length) return null;
  return (
    <section aria-labelledby="continue-title">
      <h2 id="continue-title" className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-subtle">Continue</h2>
      <ul className="grid gap-2 sm:grid-cols-3">
        {items.map((c) => (
          <li key={c.conversation_id}>
            <Link href={`/c/${c.conversation_id}`} className="group block rounded-[16px] bg-surface-2/70 px-4 py-3 transition-colors hover:bg-surface-2">
              <span className="line-clamp-1 text-[14px] font-medium group-hover:text-accent">{c.title}</span>
              <span className="mt-0.5 block truncate text-[12px] text-subtle">{[c.project_name, `Last active ${timeAgo(c.updated_at)}`].filter(Boolean).join(" · ")}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

// --- Priority 1: needs your attention ---------------------------------------------------------

function useRecommendationActions() {
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
      toast("Ignored. NOVA will bring it back if something changes.");
    } else if (action.kind === "review") {
      if (action.href.startsWith("http")) window.open(action.href, "_blank", "noopener");
      else router.push(action.href);
    } else if (action.kind === "retry") {
      await api.post(`/executions/${action.task_id}/retry`);
      toast("Retrying from the last completed step.");
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
  const { run, pending } = useRecommendationActions();
  const [expanded, setExpanded] = useState(false);
  const [featured, ...rest] = items;
  const others = expanded ? rest : rest.slice(0, 3);
  return (
    <section id="attention" aria-labelledby="attention-title" className="scroll-mt-6">
      <h2 id="attention-title" className="mb-3 flex items-center gap-2 text-[17px] font-semibold tracking-tight">
        Needs your attention
        {items.length ? <span className="rounded-full bg-accent px-2 text-[12px] font-semibold leading-5 text-accent-fg">{items.length}</span> : null}
      </h2>
      {loading ? <Skeleton className="h-40 rounded-[22px]" /> : null}
      {!loading && !featured ? (
        <p className="flex items-center gap-2 rounded-[18px] bg-surface-2/60 px-5 py-4 text-[14px] text-muted">
          <Check className="size-4 text-success" /> Nothing needs you right now. NOVA will tell you when something does.
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
          {expanded ? "Show less" : `Show ${rest.length - 3} more`}
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
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "pause" | "continue" | "cancel" }) => api.post(`/executions/${id}/${action}`),
    onSuccess: (_, { action }) => {
      toast(action === "pause" ? "NOVA will pause after the current step." : action === "continue" ? "NOVA resumes where it stopped." : "Task stopped.");
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: keys.today });
    },
  });
}

function WorkingRow({ task, now }: { task: WorkItem; now: number }) {
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
          {paused ? <Badge tone="warning">Paused</Badge> : null}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-subtle">
          {task.skills[0] ? <span className="inline-flex items-center gap-1"><Sparkles className="size-3.5" /> {task.skills.join(" → ")}</span> : null}
          <span className="inline-flex items-center gap-1"><CircleDot className="size-3.5" /> {paused ? "Paused before the next step" : current?.title ?? task.phase_label ?? "Starting"}</span>
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
            <Play /> Resume
          </Button>
        ) : task.status === "running" || task.status === "queued" ? (
          <Tooltip content="Pause after the current step — completed steps are kept">
            <Button variant="ghost" size="sm" onClick={() => control.mutate({ id: task.id, action: "pause" })} disabled={control.isPending} aria-label="Pause">
              <Pause /> Pause
            </Button>
          </Tooltip>
        ) : null}
        <Tooltip content="Stop this task">
          <Button variant="ghost" size="icon" className="size-8 text-subtle" onClick={() => control.mutate({ id: task.id, action: "cancel" })} disabled={control.isPending} aria-label="Stop">
            <Square className="!size-3.5" />
          </Button>
        </Tooltip>
      </div>
    </li>
  );
}

export function WorkingOn({ tasks }: { tasks: WorkItem[] }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const live = tasks.filter((t) => t.status !== "waiting_user");
  return (
    <section id="working" aria-labelledby="working-title" className="scroll-mt-6">
      <h2 id="working-title" className="mb-1 flex items-center gap-2 text-[15px] font-semibold tracking-tight">
        NOVA is working on
        <span className="text-[13px] font-normal text-subtle">{live.length || "nothing right now"}</span>
      </h2>
      {live.length ? <ul className="divide-y divide-border/70">{live.map((t) => <WorkingRow key={t.id} task={t} now={now} />)}</ul> : null}
    </section>
  );
}

// --- Priority 3: recent results (timeline) ---------------------------------------------------

export function RecentResults({ artifacts }: { artifacts: ArtifactSummary[] }) {
  return (
    <section id="results" aria-labelledby="results-title" className="scroll-mt-6">
      <div className="mb-1 flex items-center justify-between">
        <h2 id="results-title" className="text-[15px] font-semibold tracking-tight">Recent results</h2>
        <Link href="/artifacts" className="text-[12.5px] text-subtle hover:text-accent">All results</Link>
      </div>
      {artifacts.length ? (
        <ol className="relative ml-1.5 border-l border-border pl-4">
          {artifacts.map((a) => (
            <li key={a.id} className="relative py-2">
              <span className="absolute -left-[21px] top-3.5 size-2 rounded-full bg-border-strong" aria-hidden />
              <Link href={`/artifacts/${a.id}`} className="group flex items-baseline gap-2">
                <FileText className="size-3.5 shrink-0 translate-y-0.5 text-subtle" />
                <span className="truncate text-[13.5px] group-hover:text-accent">{a.title}</span>
                <span className="ml-auto shrink-0 text-[12px] text-subtle">{a.type_name} · v{a.version} · {timeAgo(a.updated_at)}</span>
              </Link>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-[13.5px] text-subtle">Your work with NOVA will appear here.</p>
      )}
    </section>
  );
}

// --- Background capabilities: ORBIT context, FORGE quality ------------------------------------

export function ContextStatus({ context }: { context: Today["context"] }) {
  if (!context.linked) {
    return (
      <Link href="/settings#orbit" className="block rounded-[18px] bg-surface-2/60 px-4 py-3.5 transition-colors hover:bg-surface-2">
        <div className="text-[11.5px] font-semibold uppercase tracking-wide text-subtle">Context</div>
        <div className="mt-1 flex items-center gap-2 text-[14px] font-medium">
          <Orbit className="size-4 text-subtle" /> ORBIT · Not linked
        </div>
        <div className="mt-0.5 text-[12.5px] text-muted">Link your account so NOVA knows your projects. <ChevronRight className="inline size-3.5" /></div>
      </Link>
    );
  }
  const t = context.totals;
  const total = t.documents + t.memory_items;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="block w-full rounded-[18px] bg-surface-2/60 px-4 py-3.5 text-left transition-colors hover:bg-surface-2">
          <div className="text-[11.5px] font-semibold uppercase tracking-wide text-subtle">Context</div>
          <div className="mt-1 flex items-center gap-2 text-[14px] font-medium">
            <Orbit className="size-4 text-accent" /> ORBIT · {context.error ? "Degraded" : "Connected"}
          </div>
          <div className="mt-0.5 text-[12.5px] text-muted">
            {total} sources available{context.projects.length > 1 ? ` across ${context.projects.length} projects` : ""}
            {context.changes_24h ? ` · ${context.changes_24h} updated today` : ""}
          </div>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80">
        <div className="text-[13px] font-semibold">What NOVA can use</div>
        <dl className="mt-2 grid grid-cols-2 gap-2">
          {[
            ["Documents", t.documents],
            ["Memory", t.memory_items],
            ["Decisions", t.decisions],
            ["Sources", t.sources],
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
              <span className="text-subtle">{p.documents} docs · {p.memory_items} memory</span>
            </li>
          ))}
        </ul>
        {context.error ? <p className="mt-2 text-[12px] text-warning">{context.error}</p> : null}
        <Link href="/context" className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">
          Open context <ArrowRight className="size-3.5" />
        </Link>
      </PopoverContent>
    </Popover>
  );
}

export function QualityStatus({ quality }: { quality: Today["quality"] }) {
  const last = quality.last_evaluation;
  return (
    <a
      href={last?.url ?? quality.url}
      target="_blank"
      rel="noreferrer"
      className="block rounded-[18px] bg-surface-2/60 px-4 py-3.5 transition-colors hover:bg-surface-2"
    >
      <div className="text-[11.5px] font-semibold uppercase tracking-wide text-subtle">Quality</div>
      <div className="mt-1 flex items-center gap-2 text-[14px] font-medium">
        <Gauge className={cn("size-4", quality.monitoring ? "text-accent" : "text-subtle")} /> FORGE · {quality.monitoring ? "Monitoring" : "Not connected"}
      </div>
      <div className="mt-0.5 text-[12.5px] text-muted">
        {last?.score !== null && last?.score !== undefined
          ? `Last evaluation: ${Math.round(last.score)}/100 · ${timeAgo(last.at)}`
          : last
            ? `Last evaluation ${last.status ?? "queued"} · ${timeAgo(last.at)}`
            : "No evaluation yet"}
      </div>
    </a>
  );
}
