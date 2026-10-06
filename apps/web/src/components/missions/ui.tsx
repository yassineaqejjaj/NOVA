"use client";

import { Button, cn, Tooltip } from "@nova/ui";
import { motion } from "framer-motion";
import { AlertTriangle, Check, CircleDashed, Eye, FileText, Hand, Lightbulb, Loader2, MessageSquare, Play, ShieldCheck, Sparkles, UserRound, XCircle, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { AgentAvatar } from "@/components/agents/sub-agents";
import { NovaOrb, type OrbState } from "@/components/shell/nova-orb";
import { api } from "@/lib/api/client";
import { useSendIntent } from "@/lib/api/hooks";
import { type Confidence, type GoalAutonomy, type InboxAction, type InboxItem, type Milestone, type MissionState, useDismiss, useGoalAction, usePresence, useValidateDeliverable } from "@/lib/api/missions";
import { agentOf } from "@/lib/agents";
import { timeAgo } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSystemLabel } from "@/lib/i18n/catalog";

import { M } from "./missions.messages";

// --- Autonomy levels ------------------------------------------------------------------------------------

export const LEVELS: { value: GoalAutonomy; icon: typeof Eye }[] = [
  { value: "observe", icon: Eye },
  { value: "suggest", icon: Lightbulb },
  { value: "execute_with_approval", icon: ShieldCheck },
  { value: "execute_automatically", icon: Zap },
];

/** The autonomy levels (plus "Assist", the conversational default, when ``includeAssist``). */
export function AutonomyLevels<V extends string = GoalAutonomy>({ value, onChange, includeAssist = false }: { value: V; onChange: (v: V) => void; includeAssist?: boolean }) {
  const t = useT(M);
  const levels: { value: GoalAutonomy | "assist"; icon: typeof Eye }[] = includeAssist ? [LEVELS[0]!, LEVELS[1]!, { value: "assist", icon: MessageSquare }, LEVELS[2]!, LEVELS[3]!] : LEVELS;
  return (
    <div role="radiogroup" aria-label={t("autonomy")} className="grid gap-2 sm:grid-cols-2">
      {levels.map(({ value: level, icon: Icon }, i) => (
        <button
          key={level}
          type="button"
          role="radio"
          aria-checked={value === level}
          onClick={() => onChange(level as V)}
          className={cn("flex items-start gap-3 rounded-[12px] border px-3 py-2.5 text-left transition-colors", value === level ? "border-accent/50 bg-accent-soft" : "border-border hover:border-border-strong")}
        >
          <span className={cn("mt-0.5 grid size-7 shrink-0 place-items-center rounded-full", value === level ? "bg-accent text-white" : "bg-surface-2 text-muted")}>
            <Icon className="size-3.5" />
          </span>
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 text-[13.5px] font-medium">
              <span className="text-[11px] tabular-nums text-subtle">{i + 1}</span> {t(`a_${level}`)}
            </span>
            <span className="block text-[12px] leading-snug text-subtle">{t(`a_${level}_hint`)}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

export function autonomyLabel(level: string, t: ReturnType<typeof useT<typeof M.en>>): string {
  return (["observe", "suggest", "execute_with_approval", "execute_automatically"] as const).includes(level as GoalAutonomy) ? t(`a_${level as GoalAutonomy}`) : level;
}

// --- Progress & milestones ----------------------------------------------------------------------------

export function ProgressBar({ percent, className }: { percent: number; className?: string }) {
  return (
    <div className={cn("h-1.5 overflow-hidden rounded-full bg-surface-3", className)} role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
      <motion.div className="h-full rounded-full bg-gradient-to-r from-[#fca5b1] to-accent" initial={false} animate={{ width: `${Math.max(percent, 3)}%` }} transition={{ duration: 0.4 }} />
    </div>
  );
}

export const MISSION_ORB: Record<MissionState, OrbState> = { working: "working", waiting: "waiting", blocked: "clarification", idle: "idle", done: "completed" };

export function MissionChip({ state }: { state: MissionState }) {
  const t = useT(M);
  const tone = { working: "text-accent", waiting: "text-warning", blocked: "text-danger", idle: "text-subtle", done: "text-success" }[state];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[12px] font-medium", tone)} data-mission={state}>
      {state === "working" ? <Loader2 className="size-3 animate-spin" /> : state === "waiting" ? <Hand className="size-3" /> : state === "blocked" ? <AlertTriangle className="size-3" /> : state === "done" ? <Check className="size-3" /> : <CircleDashed className="size-3" />}
      {t(`ms_${state}`)}
    </span>
  );
}

function MilestoneIcon({ m }: { m: Milestone }) {
  if (m.status === "done") return <Check className="size-3.5 text-success" />;
  if (m.status === "working") return <Loader2 className="size-3.5 animate-spin text-accent" />;
  if (m.status === "waiting" || m.status === "ready") return <span className="block size-2.5 rounded-full bg-warning" />;
  if (m.status === "blocked") return <XCircle className="size-3.5 text-danger" />;
  if (m.status === "skipped") return <span className="block size-2.5 rounded-full border border-subtle line-through" />;
  return <span className="block size-2.5 rounded-full border border-subtle" />;
}

export function MilestoneList({ goalId, milestones, interactive = true }: { goalId: string; milestones: Milestone[]; interactive?: boolean }) {
  const t = useT(M);
  const label = useSystemLabel();
  const act = useGoalAction();
  const run = (action: string, milestone_id: string) => act.mutate({ goalId, action, milestone_id }, { onSuccess: () => toast(t("done")) });
  return (
    <ol className="space-y-1" data-testid="milestones">
      {milestones.map((m) => (
        <li key={m.id} className={cn("flex items-start gap-3 rounded-[10px] px-2.5 py-2", m.status === "working" && "bg-accent-soft/40", (m.status === "waiting" || m.status === "ready") && "bg-warning/8")} data-status={m.status}>
          <span className="mt-1 grid w-4 place-items-center"><MilestoneIcon m={m} /></span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("text-[14px]", m.status === "done" || m.status === "skipped" ? "text-muted" : "text-text", m.status === "skipped" && "line-through")}>{m.title}</span>
              {m.kind === "human" ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted"><UserRound className="size-3" /> {t("humanStep")}</span>
              ) : m.agent ? (
                <AgentAvatar profile={agentOf(m.agent)} size={18} />
              ) : null}
              <span className="text-[11.5px] text-subtle">{t(`m_${m.status}`)}</span>
            </div>
            {m.status === "working" && m.activity ? <p className="mt-0.5 text-[12px] text-muted"><span className="shimmer-text">{label(m.activity)}</span></p> : m.goal ? <p className="mt-0.5 text-[12px] text-subtle">{m.goal}</p> : null}
            {m.note && m.status === "blocked" ? <p className="mt-0.5 text-[12px] text-danger">{label(m.note)}</p> : null}
          <div className="mt-1.5 flex flex-wrap items-center gap-1 empty:hidden">
            {m.artifact_ids[0] ? (
              <Link href={`/artifacts/${m.artifact_ids[0]}`} className="inline-flex items-center gap-1 text-[12px] text-accent hover:underline"><FileText className="size-3" /> {t("deliverable")}</Link>
            ) : null}
            {interactive && m.status === "ready" ? <Button size="sm" variant="primary" onClick={() => run("start", m.id)} disabled={act.isPending}><Play className="!size-3" /> {t("start")}</Button> : null}
            {interactive && m.status === "waiting" && m.kind === "human" ? <Button size="sm" variant="secondary" onClick={() => run("done", m.id)} disabled={act.isPending}><Check className="!size-3" /> {t("markDone")}</Button> : null}
            {interactive && m.status === "blocked" ? <Button size="sm" variant="secondary" onClick={() => run("retry", m.id)} disabled={act.isPending}>{t("retry")}</Button> : null}
            {interactive && ["ready", "waiting", "blocked"].includes(m.status) ? <Button size="sm" variant="ghost" className="text-subtle" onClick={() => run("skip", m.id)} disabled={act.isPending}>{t("skip")}</Button> : null}
          </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

// --- Confidence ------------------------------------------------------------------------------------------

export function ConfidenceBadge({ confidence, compact = false }: { confidence: Confidence; compact?: boolean }) {
  const t = useT(M);
  const tone = confidence.level === "high" ? "text-success bg-success/10" : confidence.level === "medium" ? "text-warning bg-warning/10" : "text-danger bg-danger/10";
  const by = confidence.evaluated_by.map((b) => (b === "forge" ? "FORGE" : t("validationAgent"))).join(" + ");
  const details = (
    <div className="space-y-1 text-[12px]">
      <div className="font-medium">{t("confidence")} · {t(`c_${confidence.level}`)} · {confidence.score} %</div>
      {Object.entries(confidence.dimensions).map(([k, v]) => (
        <div key={k} className="flex justify-between gap-6"><span>{t(`d_${k as "quality"}`)}</span><span className="tabular-nums">{v}</span></div>
      ))}
      {confidence.ungrounded ? <div className="pt-1 text-warning">{t("ungrounded")}</div> : null}
      <div className="pt-1 opacity-75">{t("evaluatedBy", { by })}</div>
    </div>
  );
  return (
    <Tooltip content={details}>
      <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium tabular-nums", tone)} data-testid="confidence">
        <ShieldCheck className="size-3" /> {compact ? `${confidence.score} %` : `${t("confidence")} · ${t(`c_${confidence.level}`)} · ${confidence.score} %`}
      </span>
    </Tooltip>
  );
}

// --- Inbox -----------------------------------------------------------------------------------------------

export const KIND_ICON = { decision: Hand, validation: ShieldCheck, anomaly: AlertTriangle, suggestion: Lightbulb, result: Sparkles } as const;
export const KIND_TONE = { decision: "text-warning bg-warning/10", validation: "text-success bg-success/10", anomaly: "text-danger bg-danger/10", suggestion: "text-accent bg-accent-soft", result: "text-muted bg-surface-2" } as const;

export function useInboxActions() {
  const t = useT(M);
  const router = useRouter();
  const send = useSendIntent();
  const goal = useGoalAction();
  const validate = useValidateDeliverable();
  const dismiss = useDismiss();
  const run = async (item: InboxItem, action: InboxAction) => {
    if (action.kind === "goal" && action.goal_id && action.action) {
      await goal.mutateAsync({ goalId: action.goal_id, action: action.action, milestone_id: action.milestone_id });
      toast(t("done"));
    } else if (action.kind === "validate" && action.artifact_id) {
      await validate.mutateAsync({ artifactId: action.artifact_id, inboxId: item.id });
      toast(t("validated"));
    } else if (action.kind === "ignore") {
      dismiss.mutate(item.id);
      toast(t("ignored"));
    } else if (action.kind === "review" && action.href) {
      if (action.href.startsWith("http")) window.open(action.href, "_blank", "noopener");
      else router.push(action.href);
    } else if (action.kind === "retry" && action.task_id) {
      await api.post(`/executions/${action.task_id}/retry`);
      toast(t("retrying"));
    } else if (action.prompt) {
      const result = await send.mutateAsync({
        conversationId: null,
        payload: { text: action.prompt, project_id: null, context_mode: "auto", pinned_context_ref_ids: [], excluded_context_refs: [], artifact_refs: action.artifact_id ? [action.artifact_id] : [], active_artifact_id: null, attachments: [] },
      });
      router.push(`/c/${result.conversation.id}`);
    }
  };
  return { run, pending: send.isPending || goal.isPending || validate.isPending };
}

export function InboxItemCard({ item, large = false }: { item: InboxItem; large?: boolean }) {
  const t = useT(M);
  const label = useSystemLabel();
  const { run, pending } = useInboxActions();
  const Icon = KIND_ICON[item.kind];
  return (
    <li className="flex gap-3 py-3.5" data-kind={item.kind} data-testid="inbox-item">
      <span className={cn("mt-0.5 grid size-8 shrink-0 place-items-center rounded-full", KIND_TONE[item.kind])}><Icon className="size-4" /></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-subtle">
          <span className="font-medium uppercase tracking-wide">{t(`k_${item.kind}`)}</span>
          {item.project_name ? <span>· {item.project_name}</span> : null}
          {item.at ? <span>· {timeAgo(item.at)}</span> : null}
          {item.confidence ? <ConfidenceBadge confidence={item.confidence} compact /> : null}
        </div>
        <div className={cn("mt-0.5 font-medium text-text", large ? "text-[15px]" : "text-[14px]")}>{label(item.title)}</div>
        {item.subtitle ? <p className="mt-0.5 text-[13px] text-muted">{label(item.subtitle)}</p> : null}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.actions.map((a, i) => (
            <Button key={`${a.kind}-${i}`} size="sm" variant={i === 0 ? "primary" : a.kind === "ignore" ? "ghost" : "secondary"} className="rounded-full" disabled={pending} onClick={() => void run(item, a)}>
              {label(a.label)}
            </Button>
          ))}
        </div>
      </div>
    </li>
  );
}

// --- Presence ----------------------------------------------------------------------------------------------

function elapsed(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min`;
}

/** NOVA's presence: what it is doing right now, even when the work runs in the background. */
export function PresencePill({ className, compact = false }: { className?: string; compact?: boolean }) {
  const t = useT(M);
  const label = useSystemLabel();
  const { data } = usePresence();
  if (!data) return null;
  const orb: OrbState = data.state === "working" ? "working" : data.state === "waiting" ? "waiting" : "idle";
  const status = data.mission ? t("presenceWorking", { title: data.mission.title }) : data.waiting ? t("presenceWaiting", { n: data.waiting }) : t("presenceIdle");
  const href = data.mission?.href ?? (data.waiting ? "/inbox" : null);
  if (compact) {
    // Collapsed menu: the orb alone, its status in a tooltip.
    const orbOnly = (
      <span className="flex justify-center" data-testid="presence" data-state={data.state} aria-label={status}>
        <NovaOrb state={orb} size={26} />
      </span>
    );
    return (
      <Tooltip content={status} side="right">
        {href ? <Link href={href} className={cn("block rounded-[12px] py-2 hover:bg-surface-2", className)}>{orbOnly}</Link> : <div className={cn("py-2", className)}>{orbOnly}</div>}
      </Tooltip>
    );
  }
  const body = (
    <span className="flex min-w-0 items-center gap-2.5" data-testid="presence" data-state={data.state}>
      <NovaOrb state={orb} size={26} />
      <span className="min-w-0">
        <span className="block truncate text-[12.5px] font-medium text-text">{status}</span>
        {data.mission ? (
          <span className="block truncate text-[11.5px] text-subtle">
            {data.mission.activity ? label(data.mission.activity) : null} · {elapsed(data.mission.started_at)}
          </span>
        ) : null}
      </span>
    </span>
  );
  return href ? (
    <Link href={href} className={cn("block rounded-[12px] px-2 py-2 hover:bg-surface-2", className)}>{body}</Link>
  ) : (
    <div className={cn("px-2 py-2", className)}>{body}</div>
  );
}
