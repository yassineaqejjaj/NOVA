"use client";

import { cn, Tooltip } from "@nova/ui";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronRight, CircleDashed, FileText, Forward, Loader2, Pause, TriangleAlert, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { systemLabel } from "@/components/conversation/blocks.messages";
import { NovaOrb, type OrbState } from "@/components/shell/nova-orb";
import { useSkills } from "@/lib/api/hooks";
import type { SkillSummary } from "@/lib/api/types";
import { type AgentKey, agentAvatarStyle, agentLook, agentOf, AGENTS, SUPPORT_AGENTS } from "@/lib/agents";
import { type Lang, useLang, useT } from "@/lib/i18n";
import { planStepTitle, skillName, useCatalogNames } from "@/lib/i18n/catalog";

import { M } from "./sub-agents.messages";

// --- data -------------------------------------------------------------------------------------------

export interface StepValidation {
  status: "passed" | "revised" | "warning";
  checks: { key: string; index: number | null; label: string; passed: boolean; detail: string }[];
  criteria: { key: string; passed: boolean; comment: string }[];
  issues: { section: string; problem: string; fix: string }[];
  summary: string;
  reviewed: boolean;
  revisions: number;
}

export interface StepHandoff {
  from: string;
  to: string;
  to_step: string;
  title: string;
  note: string;
  validation?: string | null;
}

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
  goal?: string;
  rationale?: string;
  validation?: StepValidation | null;
  handoff?: StepHandoff | null;
}

export interface ActivityLine {
  key: string;
  label: string;
  status: string;
  detail: string;
}

type RowStatus = "queued" | "working" | "waiting" | "paused" | "done" | "failed" | "skipped";

/** Activity keys "<step>:<sub>" written by the Validation agent and the revision NOVA requests. */
const VALIDATION_SUBS = new Set(["validate", "recheck"]);

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

type SkillTr = { steps?: Record<string, string>; checks?: string[]; criteria?: Record<string, string> };

function skillTr(skill: SkillSummary | undefined, lang: Lang): SkillTr {
  return ((skill?.translations as Record<string, SkillTr> | undefined)?.[lang] ?? {}) as SkillTr;
}

type Names = ReturnType<typeof useCatalogNames>;

/** A sub-step's label: the Skill step title in the interface language, else the API's label. */
function activityLabel(line: ActivityLine, skill: SkillSummary | undefined, lang: Lang, names?: Names): string {
  const sub = line.key.split(":")[1] ?? "";
  return skillTr(skill, lang).steps?.[sub] || systemLabel(line.label, lang, names);
}

// --- avatars & chips --------------------------------------------------------------------------------

export function AgentAvatar({ profile, size = 28, active = false, dim = false, className }: { profile: AgentKey; size?: number; active?: boolean; dim?: boolean; className?: string }) {
  const Icon = agentLook(profile).icon;
  const style = agentAvatarStyle(profile);
  return (
    <span className={cn("relative inline-flex shrink-0 items-center justify-center rounded-full border", dim && "opacity-45 grayscale-[35%]", className)} style={{ width: size, height: size, ...style }}>
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

function StatusChip({ status, elapsed }: { status: RowStatus; elapsed?: string | null }) {
  const t = useT(M);
  const tone = { queued: "text-subtle", working: "text-accent", waiting: "text-warning", paused: "text-warning", done: "text-success", failed: "text-danger", skipped: "text-subtle" }[status];
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

function LineIcon({ status, color }: { status: string; color?: string }) {
  if (status === "running") return <Loader2 className="size-3 shrink-0 animate-spin" style={{ color }} />;
  if (status === "failed") return <XCircle className="size-3 shrink-0 text-danger" />;
  if (status === "completed") return <Check className="size-3 shrink-0 text-success" />;
  return <CircleDashed className="size-3 shrink-0 text-subtle" />;
}

// --- NOVA Core: orchestration lanes -----------------------------------------------------------------

type LaneState = "done" | "running" | "pending";

function Lanes({ lanes }: { lanes: { key: string; label: string; detail: string; state: LaneState }[] }) {
  return (
    <ol className="grid grid-cols-2 gap-1.5 @[560px]:grid-cols-4" data-testid="orchestration">
      {lanes.map((lane) => (
        <li
          key={lane.key}
          data-lane={lane.key}
          data-state={lane.state}
          className={cn(
            "min-w-0 rounded-[10px] border px-2.5 py-1.5",
            lane.state === "running" ? "border-accent/40 bg-accent-soft/50" : lane.state === "done" ? "border-border bg-surface-2/60" : "border-dashed border-border",
          )}
        >
          <div className="flex items-center gap-1.5 text-[11.5px] font-medium">
            {lane.state === "done" ? <Check className="size-3 text-success" /> : lane.state === "running" ? <Loader2 className="size-3 animate-spin text-accent" /> : <CircleDashed className="size-3 text-subtle" />}
            <span className="truncate">{lane.label}</span>
          </div>
          <div className="truncate pl-[18px] text-[11px] text-subtle">{lane.detail}</div>
        </li>
      ))}
    </ol>
  );
}

/**
 * NOVA Core: NOVA turns the intent into a task, decomposes it, assigns each step to the specialist sub-agent
 * (Product, Project, Design, Engineering), has the Research agent bring the context and the Validation agent verify
 * each deliverable, relays handoffs between agents and supervises the whole — shown live.
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
  const skillOf = (s: AgentStep) => (s.skill_id ? skills?.find((k) => k.id === s.skill_id) : undefined);
  const done = steps.filter((s) => s.status === "completed" || s.status === "skipped").length;
  const statuses = steps.map((s) => rowStatus(s, taskStatus));
  const working = statuses.includes("working");
  const finished = steps.length > 0 && done === steps.length;
  const orb: OrbState = statuses.includes("failed") ? "idle" : working ? "working" : statuses.includes("waiting") ? "waiting" : finished ? "completed" : live ? "thinking" : "idle";
  const team = [...new Set(steps.map((s) => agentOf(s.agent)))];
  const validated = steps.filter((s) => s.validation && s.validation.status !== "warning").length;
  const revisions = steps.reduce((n, s) => n + (s.validation?.revisions ?? 0), 0);
  const deliverables = [...new Set(steps.map((s) => skillOf(s)).filter(Boolean).map((k) => (k!.translations?.[lang]?.artifact_type_name as string | undefined) || k!.artifact_type_name).filter(Boolean))];
  const research = activity.find((l) => l.key === "context");

  const lanes: { key: string; label: string; detail: string; state: LaneState }[] = [
    { key: "planning", label: t("lanePlanning"), detail: t("lanePlanningDetail", { n: deliverables.length || steps.length }), state: "done" },
    { key: "decomposition", label: t("laneDecomposition"), detail: t("laneDecompositionDetail", { n: steps.length }), state: "done" },
    { key: "assignment", label: t("laneAssignment"), detail: t("laneAssignmentDetail", { n: team.length }), state: "done" },
    {
      key: "supervision",
      label: t("laneSupervision"),
      detail: t("laneSupervisionDetail", { validated, total: steps.length }) + (revisions ? ` · ${t("revisions", { n: revisions })}` : ""),
      state: finished ? "done" : live || working ? "running" : "pending",
    },
  ];

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="@container rounded-[14px] border border-border bg-surface" data-testid="sub-agents">
      <div className="space-y-2.5 px-4 pb-3 pt-3">
        <div className="flex items-center gap-3">
          <NovaOrb state={orb} size={30} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 text-[13px]">
              <span className="font-semibold">{novaName} Core</span>
              <span className="text-subtle">{t("orchestrator")}</span>
            </div>
            {objective ? (
              <p className="truncate text-[12.5px] text-muted" title={objective}>
                <span className="text-subtle">{t("task")} · </span>
                {objective}
              </p>
            ) : null}
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
        {deliverables.length ? <p className="text-[12px] text-subtle">{t("deliverables", { list: deliverables.join(" · ") })}</p> : null}
        <Lanes lanes={lanes} />
      </div>
      <ol className="relative border-t border-border px-4 pb-3 pt-1" aria-label={t("team")}>
        {research ? <ResearchRow line={research} /> : null}
        {steps.map((step, i) => (
          <AgentRow
            key={step.id}
            step={step}
            status={statuses[i]!}
            last={i === steps.length - 1}
            skill={skillOf(step)}
            lines={activity.filter((l) => l.key.startsWith(`${step.id}:`))}
            now={now}
            onOpenArtifact={onOpenArtifact}
          />
        ))}
      </ol>
      {assumptions?.length ? <div className="border-t border-border px-4 py-2 text-[12px] text-subtle">{t("assumptions", { list: assumptions.join(" · ") })}</div> : null}
    </motion.div>
  );
}

function Rail({ last }: { last: boolean }) {
  return (
    <>
      <span aria-hidden className="absolute left-[16px] top-0 w-px bg-border" style={{ height: last ? 14 : "100%" }} />
      <span aria-hidden className="absolute left-[16px] top-[14px] h-px w-3 bg-border" />
    </>
  );
}

function ResearchRow({ line }: { line: ActivityLine }) {
  const t = useT(M);
  const lang = useLang();
  const names = useCatalogNames();
  const status: RowStatus = line.status === "running" ? "working" : line.status === "failed" ? "failed" : line.status === "skipped" ? "skipped" : "done";
  return (
    <li className="relative flex gap-3 pl-[3px]" data-agent="research" data-status={status}>
      <Rail last={false} />
      <div className="relative z-[1] pl-5 pt-1.5">
        <AgentAvatar profile="research" size={26} active={status === "working"} />
      </div>
      <div className="min-w-0 flex-1 border-b border-border/60 py-2">
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-[12px] font-semibold" style={{ color: SUPPORT_AGENTS.research.color }}>{SUPPORT_AGENTS.research.name[lang]}</span>
          <span className="truncate text-[13.5px]">{t("researchTitle")}</span>
          <span className="ml-auto"><StatusChip status={status} /></span>
        </div>
        {line.detail ? <div className="mt-0.5 truncate text-[12px] text-subtle">{systemLabel(line.detail, lang, names)}</div> : null}
      </div>
    </li>
  );
}

function AgentRow({
  step,
  status,
  last,
  skill,
  lines,
  now,
  onOpenArtifact,
}: {
  step: AgentStep;
  status: RowStatus;
  last: boolean;
  skill: SkillSummary | undefined;
  lines: ActivityLine[];
  now: number;
  onOpenArtifact?: (id: string) => void;
}) {
  const t = useT(M);
  const lang = useLang();
  const names = useCatalogNames();
  const { data: skills } = useSkills();
  const title = planStepTitle(step, skills, lang, names);
  const profile = agentOf(step.agent);
  const agent = AGENTS[profile];
  const active = status === "working";
  const [open, setOpen] = useState(false);
  const own = lines.filter((l) => !VALIDATION_SUBS.has(l.key.split(":")[1] ?? ""));
  const checking = lines.filter((l) => VALIDATION_SUBS.has(l.key.split(":")[1] ?? ""));
  const validating = checking.some((l) => l.status === "running");
  const expanded = (active && !validating) || open;
  const current = [...own].reverse().find((l) => l.status === "running");
  const label = skill ? skillName(skill, lang) : step.skill_name;
  const color = agent.color;
  return (
    <li className="relative flex gap-3 pl-[3px]" data-agent={profile} data-status={status}>
      <Rail last={last} />
      <div className="relative z-[1] pl-5 pt-1.5">
        <AgentAvatar profile={profile} size={26} active={active && !validating} dim={status === "queued"} />
      </div>
      <div className={cn("min-w-0 flex-1 border-b border-border/60 py-2", last && "border-b-0")}>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-1.5 text-left" aria-expanded={expanded}>
            <ChevronRight className={cn("size-3 shrink-0 text-subtle transition-transform", expanded && "rotate-90")} />
            <span className="shrink-0 text-[12px] font-semibold" style={{ color }}>{agent.name[lang]}</span>
            <span className={cn("truncate text-[13.5px]", status === "queued" ? "text-muted" : "text-text")}>{title}</span>
          </button>
          <StatusChip status={status} elapsed={stepElapsed(step, now)} />
        </div>
        <div className="mt-0.5 flex min-w-0 items-center gap-2 pl-[18px] text-[12px] text-subtle">
          {label && label !== title ? <span className="shrink-0 truncate">{label}</span> : null}
          {active && current && !validating ? (
            <span className="truncate text-muted">
              {label && label !== title ? "· " : ""}
              <span className="shimmer-text">{activityLabel(current, skill, lang, names)}</span>
            </span>
          ) : status === "waiting" ? (
            <span className="text-warning">{t("needsYou")}</span>
          ) : status === "failed" && step.detail ? (
            <span className="truncate text-danger">{systemLabel(step.detail, lang, names)}</span>
          ) : null}
          {step.artifact_id && onOpenArtifact ? (
            <button onClick={() => onOpenArtifact(step.artifact_id!)} className="ml-auto inline-flex shrink-0 items-center gap-1 text-accent hover:underline">
              <FileText className="size-3" /> {t("open")}
            </button>
          ) : null}
        </div>
        <AnimatePresence initial={false}>
          {expanded ? (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.18 }} className="space-y-1 overflow-hidden pl-[18px] pt-1.5">
              {step.goal ? (
                <p className="text-[12px] text-muted"><span className="text-subtle">{t("goal")} · </span>{step.goal}</p>
              ) : null}
              <p className="text-[12px] text-muted" data-testid="assignment">
                <span className="text-subtle">{t("assigned", { agent: agent.name[lang] })} · </span>
                {step.rationale ? systemLabel(step.rationale, lang, names) : t("owner", { skill: label ?? "" })}
              </p>
              {own.length ? (
                <ul>
                  {own.map((line) => (
                    <li key={line.key} className="flex items-center gap-2 py-0.5 text-[12px]">
                      <LineIcon status={line.status} color={color} />
                      <span className={line.status === "running" ? "text-text" : "text-muted"}>{line.key.endsWith(":revise") ? t("revising") : activityLabel(line, skill, lang, names)}</span>
                      {line.detail ? <span className="ml-auto max-w-[50%] truncate text-right text-subtle">{systemLabel(line.detail, lang, names)}</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </motion.div>
          ) : null}
        </AnimatePresence>
        {checking.length || step.validation ? <ValidationRow step={step} skill={skill} lines={checking} /> : null}
        {step.handoff ? <HandoffNote handoff={step.handoff} /> : null}
      </div>
    </li>
  );
}

function ValidationRow({ step, skill, lines }: { step: AgentStep; skill: SkillSummary | undefined; lines: ActivityLine[] }) {
  const t = useT(M);
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const v = step.validation;
  const running = !v && lines.some((l) => l.status === "running");
  const revising = !v && lines.some((l) => l.key.endsWith(":validate") && l.status === "completed");
  const tr = skillTr(skill, lang);
  const checkLabel = (c: StepValidation["checks"][number]) => (c.key === "filled" ? t("checkFilled") : (c.index !== null && tr.checks?.[c.index]) || c.label);
  const verdict = v ? t(`v_${v.status}`) : revising ? t("revisionRequested") : running ? t("verifying") : t("verifying");
  const tone = v ? (v.status === "warning" ? "text-warning" : "text-success") : "text-muted";
  const passed = v ? v.checks.filter((c) => c.passed).length : 0;
  return (
    <div className="mt-1.5 rounded-[10px] bg-surface-2/60 px-2.5 py-1.5" data-testid="validation" data-validation={v?.status ?? (running ? "running" : "pending")}>
      <button type="button" onClick={() => setOpen(!open)} disabled={!v} className="flex w-full min-w-0 items-center gap-2 text-left text-[12px] disabled:cursor-default">
        <AgentAvatar profile="validation" size={18} active={running} />
        <span className="shrink-0 font-semibold" style={{ color: SUPPORT_AGENTS.validation.color }}>{SUPPORT_AGENTS.validation.name[lang]}</span>
        <span className={cn("truncate", tone)}>
          {running ? <span className="shimmer-text">{verdict}</span> : verdict}
          {v ? <span className="text-subtle"> · {t("checks", { passed, total: v.checks.length })}</span> : null}
        </span>
        {v ? <ChevronRight className={cn("ml-auto size-3 shrink-0 text-subtle transition-transform", open && "rotate-90")} /> : null}
      </button>
      <AnimatePresence initial={false}>
        {open && v ? (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.18 }} className="space-y-1 overflow-hidden pl-[26px] pt-1.5 text-[12px]">
            {v.summary ? <p className="text-muted">{v.summary}</p> : null}
            <ul>
              {v.checks.map((c, i) => (
                <li key={`${c.key}-${i}`} className="flex items-center gap-2 py-0.5">
                  {c.passed ? <Check className="size-3 shrink-0 text-success" /> : <TriangleAlert className="size-3 shrink-0 text-warning" />}
                  <span className="text-muted">{checkLabel(c)}</span>
                </li>
              ))}
              {v.criteria.map((c) => (
                <li key={c.key} className="flex items-start gap-2 py-0.5">
                  {c.passed ? <Check className="mt-0.5 size-3 shrink-0 text-success" /> : <TriangleAlert className="mt-0.5 size-3 shrink-0 text-warning" />}
                  <span className="text-muted">
                    {tr.criteria?.[c.key] || c.key}
                    {c.comment ? <span className="text-subtle"> — {c.comment}</span> : null}
                  </span>
                </li>
              ))}
            </ul>
            {v.issues.length ? (
              <div>
                <div className="text-subtle">{v.status === "revised" ? t("fixedIssues") : t("openIssues")}</div>
                <ul className="list-disc pl-4 text-muted">
                  {v.issues.map((issue, i) => <li key={i}>{issue.problem} → {issue.fix}</li>)}
                </ul>
              </div>
            ) : null}
            {!v.reviewed ? <p className="text-subtle">{t("checksOnly")}</p> : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function HandoffNote({ handoff }: { handoff: StepHandoff }) {
  const t = useT(M);
  const lang = useLang();
  const to = AGENTS[agentOf(handoff.to)];
  return (
    <div className="mt-1.5 flex min-w-0 items-start gap-2 text-[12px]" data-testid="handoff">
      <Forward className="mt-0.5 size-3.5 shrink-0" style={{ color: to.color }} />
      <p className="min-w-0 text-muted">
        <span className="font-medium" style={{ color: to.color }}>{t("handoffTo", { agent: to.name[lang] })}</span>
        <span className="text-subtle"> · {handoff.title}</span>
        {handoff.note ? <span className="block truncate text-subtle" title={handoff.note}>« {handoff.note} »</span> : null}
      </p>
    </div>
  );
}

/** Compact team view for lists (Home, Tasks): the sub-agents of a task and who is working now. */
export function AgentStack({ steps, taskStatus, size = 20 }: { steps: AgentStep[]; taskStatus?: string; size?: number }) {
  const lang = useLang();
  const t = useT(M);
  const names = useCatalogNames();
  const { data: skills } = useSkills();
  if (!steps.length) return null;
  return (
    <span className="inline-flex items-center -space-x-1" data-testid="agent-stack">
      {steps.map((s) => {
        const profile = agentOf(s.agent);
        const status = rowStatus(s, taskStatus);
        return (
          <Tooltip key={s.id} content={`${AGENTS[profile].name[lang]} · ${planStepTitle(s, skills, lang, names)} — ${t(status)}`}>
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
