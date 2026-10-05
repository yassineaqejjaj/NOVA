"use client";

import { cn, Tooltip } from "@nova/ui";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronRight, FileText, Loader2, Pause, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { systemLabel } from "@/components/conversation/blocks.messages";
import { NovaOrb, type OrbState } from "@/components/shell/nova-orb";
import { useSkills } from "@/lib/api/hooks";
import { agentAvatarStyle, agentOf, AGENTS, type AgentProfile } from "@/lib/agents";
import { useLang, useT } from "@/lib/i18n";
import { skillName } from "@/lib/i18n/catalog";

import { M } from "./sub-agents.messages";

/** A workflow step as delegated by NOVA (the orchestrator) to the sub-agent owning its Skill. */
export interface AgentStep {
  id: string;
  title: string;
  skill_id: string | null;
  skill_name: string | null;
  agent?: string | null;
  status: string;
  detail?: string;
  artifact_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ActivityLine {
  key: string;
  label: string;
  status: string;
  detail: string;
}

type RowStatus = "queued" | "working" | "waiting" | "paused" | "done" | "failed" | "skipped";

function rowStatus(step: AgentStep, taskStatus: string | undefined): RowStatus {
  if (step.status === "completed") return "done";
  if (step.status === "failed") return "failed";
  if (step.status === "skipped") return "skipped";
  if (step.status === "running" || step.status === "waiting_user") {
    if (taskStatus === "waiting_user" || step.status === "waiting_user") return "waiting";
    if (taskStatus === "paused") return "paused";
    if (taskStatus === "failed" || taskStatus === "cancelled") return "failed";
    return "working";
  }
  return "queued";
}

function useNow(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [enabled]);
  return now;
}

function clockDuration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${m}:${String(s % 60).padStart(2, "0")}`;
}

function stepElapsed(step: AgentStep, now: number): string | null {
  if (!step.started_at) return null;
  const end = step.finished_at ? new Date(step.finished_at).getTime() : now;
  return clockDuration(end - new Date(step.started_at).getTime());
}

export function AgentAvatar({ profile, size = 28, active = false, dim = false, className }: { profile: AgentProfile; size?: number; active?: boolean; dim?: boolean; className?: string }) {
  const Icon = AGENTS[profile].icon;
  const style = agentAvatarStyle(profile);
  return (
    <span
      className={cn("relative inline-flex shrink-0 items-center justify-center rounded-full border", dim && "opacity-45 grayscale-[35%]", className)}
      style={{ width: size, height: size, ...style }}
    >
      {active ? (
        <motion.span
          aria-hidden
          className="absolute inset-[-3px] rounded-full border"
          style={{ borderColor: style.color }}
          animate={{ opacity: [0.7, 0, 0.7], scale: [1, 1.22, 1] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
        />
      ) : null}
      <Icon style={{ width: size * 0.5, height: size * 0.5 }} strokeWidth={2} />
    </span>
  );
}

function StatusChip({ status, elapsed }: { status: RowStatus; elapsed: string | null }) {
  const t = useT(M);
  const tone = {
    queued: "text-subtle",
    working: "text-accent",
    waiting: "text-warning",
    paused: "text-warning",
    done: "text-success",
    failed: "text-danger",
    skipped: "text-subtle",
  }[status];
  const icon =
    status === "working" ? <Loader2 className="size-3 animate-spin" /> :
    status === "done" ? <Check className="size-3" /> :
    status === "failed" ? <XCircle className="size-3" /> :
    status === "paused" ? <Pause className="size-3" /> : null; // prettier-ignore
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1 text-[11.5px] font-medium tabular-nums", tone)} data-status={status}>
      {icon}
      {t(status)}
      {elapsed && status !== "queued" ? <span className="font-normal text-subtle">· {elapsed}</span> : null}
    </span>
  );
}

/**
 * NOVA as orchestrator and the specialist sub-agents (Product, Project, Design, Engineering) it delegates each step to:
 * who works on what, the activity in progress, the time spent and the result — live.
 */
export function SubAgents({
  objective,
  steps,
  activity = [],
  taskStatus,
  live,
  novaName = "NOVA",
  onOpenArtifact,
  assumptions,
}: {
  objective?: string;
  steps: AgentStep[];
  activity?: ActivityLine[];
  taskStatus?: string;
  live: boolean;
  novaName?: string;
  onOpenArtifact?: (id: string) => void;
  assumptions?: string[];
}) {
  const t = useT(M);
  const lang = useLang();
  const { data: skills } = useSkills();
  const now = useNow(live);
  const done = steps.filter((s) => s.status === "completed" || s.status === "skipped").length;
  const statuses = steps.map((s) => rowStatus(s, taskStatus));
  const working = statuses.includes("working");
  const orb: OrbState = statuses.includes("failed") ? "idle" : working ? "working" : statuses.includes("waiting") ? "waiting" : done === steps.length && steps.length ? "completed" : live ? "thinking" : "idle";
  const team = [...new Set(steps.map((s) => agentOf(s.agent)))];
  const label = (s: AgentStep) => {
    const skill = s.skill_id ? skills?.find((k) => k.id === s.skill_id) : undefined;
    return skill ? skillName(skill, lang) : s.skill_name;
  };
  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="rounded-[14px] border border-border bg-surface" data-testid="sub-agents">
      <div className="flex items-center gap-3 px-4 pb-2.5 pt-3">
        <NovaOrb state={orb} size={30} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 text-[13px]">
            <span className="font-semibold">{novaName}</span>
            <span className="text-subtle">{t("orchestrator")}</span>
          </div>
          {objective ? <p className="truncate text-[12.5px] text-muted" title={objective}>{objective}</p> : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <div className="flex -space-x-1.5">
            {team.map((p) => (
              <Tooltip key={p} content={AGENTS[p].name[lang]}>
                <span><AgentAvatar profile={p} size={20} className="ring-2 ring-surface" /></span>
              </Tooltip>
            ))}
          </div>
          <span className="text-[11.5px] tabular-nums text-subtle">{t("progress", { done, total: steps.length })}</span>
        </div>
      </div>
      <ol className="relative px-4 pb-3" aria-label={t("team")}>
        {steps.map((step, i) => (
          <AgentRow
            key={step.id}
            step={step}
            status={statuses[i]!}
            last={i === steps.length - 1}
            skillLabel={label(step)}
            lines={activity.filter((l) => l.key.startsWith(`${step.id}:`))}
            now={now}
            onOpenArtifact={onOpenArtifact}
          />
        ))}
      </ol>
      {assumptions?.length ? (
        <div className="border-t border-border px-4 py-2 text-[12px] text-subtle">{t("assumptions", { list: assumptions.join(" · ") })}</div>
      ) : null}
    </motion.div>
  );
}

function AgentRow({
  step,
  status,
  last,
  skillLabel,
  lines,
  now,
  onOpenArtifact,
}: {
  step: AgentStep;
  status: RowStatus;
  last: boolean;
  skillLabel: string | null;
  lines: ActivityLine[];
  now: number;
  onOpenArtifact?: (id: string) => void;
}) {
  const t = useT(M);
  const lang = useLang();
  const profile = agentOf(step.agent);
  const agent = AGENTS[profile];
  const active = status === "working";
  const [open, setOpen] = useState(false);
  const expanded = (active || open) && lines.length > 0;
  const current = [...lines].reverse().find((l) => l.status === "running");
  const color = agent.color;
  return (
    <li className="relative flex gap-3 pl-[3px]" data-agent={profile} data-status={status}>
      {/* rail from the orchestrator */}
      <span aria-hidden className="absolute left-[16px] top-0 w-px bg-border" style={{ height: last ? 14 : "100%" }} />
      <span aria-hidden className="absolute left-[16px] top-[14px] h-px w-3 bg-border" />
      <div className="relative z-[1] pt-1.5 pl-5">
        <AgentAvatar profile={profile} size={26} active={active} dim={status === "queued"} />
      </div>
      <div className={cn("min-w-0 flex-1 border-b border-border/60 py-2", last && "border-b-0")}>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setOpen(!open)}
            disabled={!lines.length}
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left disabled:cursor-default"
            aria-expanded={expanded}
          >
            {lines.length ? <ChevronRight className={cn("size-3 shrink-0 text-subtle transition-transform", expanded && "rotate-90")} /> : null}
            <span className="shrink-0 text-[12px] font-semibold" style={{ color }}>{agent.name[lang]}</span>
            <span className={cn("truncate text-[13.5px]", status === "queued" ? "text-muted" : "text-text")}>{step.title}</span>
          </button>
          <StatusChip status={status} elapsed={stepElapsed(step, now)} />
        </div>
        <div className="mt-0.5 flex min-w-0 items-center gap-2 pl-[18px] text-[12px] text-subtle">
          {skillLabel && skillLabel !== step.title ? <span className="truncate">{skillLabel}</span> : null}
          {active && current ? (
            <span className="truncate text-muted">
              {skillLabel && skillLabel !== step.title ? "· " : ""}
              <span className="shimmer-text">{systemLabel(current.label, lang)}</span>
            </span>
          ) : status === "waiting" ? (
            <span className="text-warning">{t("needsYou")}</span>
          ) : status === "failed" && step.detail ? (
            <span className="truncate text-danger">{step.detail}</span>
          ) : null}
          {step.artifact_id && onOpenArtifact ? (
            <button onClick={() => onOpenArtifact(step.artifact_id!)} className="ml-auto inline-flex shrink-0 items-center gap-1 text-accent hover:underline">
              <FileText className="size-3" /> {t("open")}
            </button>
          ) : null}
        </div>
        <AnimatePresence initial={false}>
          {expanded ? (
            <motion.ul initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.18 }} className="overflow-hidden pl-[18px] pt-1">
              {lines.map((line) => (
                <li key={line.key} className="flex items-center gap-2 py-0.5 text-[12px]">
                  {line.status === "running" ? <Loader2 className="size-3 animate-spin" style={{ color }} /> : line.status === "failed" ? <XCircle className="size-3 text-danger" /> : <Check className="size-3 text-success" />}
                  <span className={line.status === "running" ? "text-text" : "text-muted"}>{systemLabel(line.label, lang)}</span>
                  {line.detail ? <span className="ml-auto max-w-[50%] truncate text-right text-subtle">{line.detail}</span> : null}
                </li>
              ))}
            </motion.ul>
          ) : null}
        </AnimatePresence>
      </div>
    </li>
  );
}

/** Compact team view for lists (Home, Tasks): the sub-agents of a task and who is working now. */
export function AgentStack({ steps, taskStatus, size = 20 }: { steps: AgentStep[]; taskStatus?: string; size?: number }) {
  const lang = useLang();
  const t = useT(M);
  if (!steps.length) return null;
  return (
    <span className="inline-flex items-center -space-x-1" data-testid="agent-stack">
      {steps.map((s) => {
        const profile = agentOf(s.agent);
        const status = rowStatus(s, taskStatus);
        return (
          <Tooltip key={s.id} content={`${AGENTS[profile].name[lang]} · ${s.title} — ${t(status)}`}>
            <span className="relative">
              <AgentAvatar profile={profile} size={size} active={status === "working"} dim={status === "queued"} className="ring-2 ring-background" />
              {status === "done" ? <span className="absolute -bottom-0.5 -right-0.5 size-2 rounded-full bg-success ring-2 ring-background" /> : null}
            </span>
          </Tooltip>
        );
      })}
    </span>
  );
}
