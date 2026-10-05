"use client";

import { Badge, Button, cn, Input, Select } from "@nova/ui";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Check,
  ChevronRight,
  CircleDashed,
  ExternalLink,
  FileText,
  Loader2,
  Orbit,
  Pin,
  Plus,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { type ActivityLine, type AgentStep, SubAgents } from "@/components/agents/sub-agents";
import { type ApprovalData, ApprovalDialog } from "@/components/conversation/approval-dialog";
import { ClassificationBadge, ErrorNotice } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { useArtifactTypes, useResume, useSkills } from "@/lib/api/hooks";
import type { Action, Block, ContextSource } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { useLang, useT } from "@/lib/i18n";
import { sectionTitle, skillName, typeName } from "@/lib/i18n/catalog";
import { useComposer } from "@/stores/ui";

import { M, statusLabel, systemLabel } from "./blocks.messages";

export interface BlockContext {
  taskId: string | null;
  conversationId: string;
  onOpenArtifact: (id: string) => void;
  waiting: boolean;
  projectOrbitUrl?: string | null;
  taskStatus?: string;
  /** Text of the user request this reply answers (used to re-ask after a non-fatal warning). */
  requestText?: string;
  resend?: (text: string) => Promise<void>;
  /** Progress lines of the message: the plan shows each sub-agent's activity from them. */
  activity?: ActivityLine[];
  /** The message has a plan: step activity is shown under the sub-agents, not in the progress summary. */
  hasPlan?: boolean;
  live?: boolean;
  novaName?: string;
}

const fade = { initial: { opacity: 0, y: 4 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.2 } };

function StepIcon({ status }: { status: string }) {
  if (status === "completed" || status === "ok") return <Check className="size-3.5 text-success" />;
  if (status === "running") return <Loader2 className="size-3.5 animate-spin text-accent" />;
  if (status === "failed" || status === "error" || status === "denied") return <XCircle className="size-3.5 text-danger" />;
  if (status === "waiting_user") return <CircleDashed className="size-3.5 text-warning" />;
  return <span className="mx-[3px] block size-2 rounded-full border border-subtle" />;
}

// --- text ------------------------------------------------------------------------------------------

function TextBlockView({ block }: { block: Block<{ markdown: string; suggestions?: { skill_id: string; label: string }[]; follow_ups?: string[] }> }) {
  const setDraft = useComposer((s) => s.setDraft);
  const t = useT(M);
  const lang = useLang();
  const { data: skills } = useSkills();
  const focus = (text: string) => {
    setDraft(text);
    setTimeout(() => document.getElementById("nova-composer")?.focus(), 30);
  };
  return (
    <motion.div {...fade}>
      <div className="prose-nova text-[14.5px] leading-relaxed text-text">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.data.markdown}</ReactMarkdown>
      </div>
      {block.data.suggestions?.length || block.data.follow_ups?.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {block.data.suggestions?.map((s) => (
            <button key={s.skill_id} onClick={() => focus(`/${s.skill_id} `)} className="rounded-lg border border-border px-2.5 py-1 text-[12.5px] text-muted hover:border-accent/40 hover:text-text">
              {t("next", { label: skills?.find((k) => k.id === s.skill_id)?.translations?.[lang]?.name || s.label })}
            </button>
          ))}
          {block.data.follow_ups?.map((f) => (
            <button key={f} onClick={() => focus(f)} className="rounded-lg border border-border px-2.5 py-1 text-[12.5px] text-muted hover:text-text">
              {f}
            </button>
          ))}
        </div>
      ) : null}
    </motion.div>
  );
}

// --- progress (operational summary, never raw reasoning) ------------------------------------------

function ProgressBlock({ block, live, ctx }: { block: Block<{ lines: ActivityLine[] }>; live: boolean; ctx: BlockContext }) {
  const [open, setOpen] = useState(live);
  const t = useT(M);
  const lang = useLang();
  // With a plan, the lines of each step ("<step>:<sub-step>") belong to its sub-agent; NOVA's own work stays here.
  const lines = (block.data.lines ?? []).filter((l) => !ctx.hasPlan || !l.key.includes(":"));
  const done = lines.every((l) => l.status === "completed" || l.status === "failed");
  const expanded = open || live;
  return (
    <div className="rounded-[12px] border border-border bg-surface/60">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-[12.5px] text-muted">
        <ChevronRight className={cn("size-3.5 transition-transform", expanded && "rotate-90")} />
        {live && !done ? t("novaWorking") : t("novaDid")}
        <span className="text-subtle">· {t("steps", { n: lines.length })}</span>
      </button>
      <AnimatePresence initial={false}>
        {expanded ? (
          <motion.ul initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden px-3 pb-2.5">
            {lines.map((line) => (
              <li key={line.key} className="flex items-start gap-2.5 py-1 text-[13px]">
                <span className="mt-0.5">
                  <StepIcon status={line.status} />
                </span>
                <span className={cn(line.status === "running" ? "text-text" : "text-muted")}>{systemLabel(line.label, lang)}</span>
                {line.detail ? <span className="ml-auto max-w-[55%] truncate text-right text-[12px] text-subtle">{line.detail}</span> : null}
              </li>
            ))}
          </motion.ul>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

// --- plan -----------------------------------------------------------------------------------------

function PlanBlock({ block, ctx }: { block: Block<{ objective: string; steps: AgentStep[]; done: number; total: number; assumptions?: string[] }>; ctx: BlockContext }) {
  const { objective, steps, assumptions } = block.data;
  return (
    <SubAgents
      objective={objective}
      steps={steps}
      activity={ctx.activity}
      taskStatus={ctx.taskStatus}
      live={!!ctx.live}
      novaName={ctx.novaName}
      onOpenArtifact={ctx.onOpenArtifact}
      assumptions={assumptions}
    />
  );
}

// --- workflow (visible & editable before execution) -----------------------------------------------

function WorkflowBlock({ block, ctx }: { block: Block<{ status: string; objective: string; steps: { id: string; title: string; skill_id: string; rationale?: string }[]; assumptions?: string[] }>; ctx: BlockContext }) {
  const { data: skills } = useSkills();
  const t = useT(M);
  const lang = useLang();
  const resume = useResume();
  const [steps, setSteps] = useState(block.data.steps);
  const [adding, setAdding] = useState<string>("");
  const proposed = block.data.status === "proposed" && ctx.waiting;
  const name = (id: string) => {
    const skill = skills?.find((s) => s.id === id);
    return skill ? skillName(skill, lang) : id;
  };
  const move = (i: number, d: -1 | 1) =>
    setSteps((prev) => {
      const next = [...prev];
      const j = i + d;
      if (j < 0 || j >= next.length) return prev;
      [next[i], next[j]] = [next[j]!, next[i]!];
      return next;
    });
  const decide = (action: "run" | "cancel") =>
    ctx.taskId && resume.mutate({ taskId: ctx.taskId, value: action === "run" ? { action, skill_ids: steps.map((s) => s.skill_id) } : { action } });

  return (
    <motion.div {...fade} className={cn("rounded-[12px] border px-4 py-3", proposed ? "border-accent/35 bg-accent-soft/40" : "border-border bg-surface")}>
      <div className="mb-1 text-[12px] font-medium uppercase tracking-wider text-subtle">
        {proposed ? t("proposedWorkflow") : block.data.status === "cancelled" ? t("workflowCancelled") : t("workflow")}
      </div>
      <p className="mb-2.5 text-[13.5px] text-muted">{block.data.objective}</p>
      <ol className="space-y-1.5">
        {steps.map((s, i) => (
          <li key={s.id} className="flex items-center gap-2 rounded-[10px] bg-surface/70 px-2.5 py-1.5 text-[13.5px]">
            <span className="w-4 text-[12px] text-subtle">{i + 1}</span>
            <span className="shrink-0 whitespace-nowrap text-text">{name(s.skill_id)}</span>
            {s.rationale ? <span className="min-w-0 truncate text-[12px] text-subtle">· {s.rationale}</span> : null}
            {proposed ? (
              <span className="ml-auto flex items-center gap-0.5">
                <Button variant="ghost" size="icon" className="size-6" onClick={() => move(i, -1)} aria-label={t("moveUp")}><ArrowUp /></Button>
                <Button variant="ghost" size="icon" className="size-6" onClick={() => move(i, 1)} aria-label={t("moveDown")}><ArrowDown /></Button>
                <Button variant="ghost" size="icon" className="size-6" onClick={() => setSteps((p) => p.filter((x) => x.id !== s.id))} disabled={steps.length === 1} aria-label={t("removeStep")}><X /></Button>
              </span>
            ) : null}
          </li>
        ))}
      </ol>
      {proposed ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Select
            ariaLabel={t("addSkill")}
            value={adding || undefined}
            placeholder={t("addSkillPlaceholder")}
            onValueChange={(id) => {
              setSteps((p) => [...p, { id: `added-${id}`, title: name(id), skill_id: id }]);
              setAdding("");
            }}
            options={(skills ?? []).filter((s) => !steps.some((x) => x.skill_id === s.id)).map((s) => ({ value: s.id, label: skillName(s, lang) }))}
            className="h-8 w-52 text-[12.5px]"
          />
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => decide("cancel")} disabled={resume.isPending}>{t("cancel")}</Button>
            <Button variant="primary" size="sm" onClick={() => decide("run")} disabled={resume.isPending}>
              {resume.isPending ? <Loader2 className="animate-spin" /> : <Plus className="hidden" />} {t("runWorkflow")}
            </Button>
          </div>
        </div>
      ) : null}
    </motion.div>
  );
}

// --- question -------------------------------------------------------------------------------------

function QuestionBlock({ block, ctx }: { block: Block<{ questions: { key: string; question: string }[]; answered: boolean; answers?: Record<string, string> }>; ctx: BlockContext }) {
  const resume = useResume();
  const t = useT(M);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  if (block.data.answered || !ctx.waiting) {
    return (
      <div className="space-y-1 rounded-[12px] border border-border bg-surface px-4 py-3 text-[13px]">
        {block.data.questions.map((q) => (
          <div key={q.key}>
            <span className="text-muted">{q.question}</span> <span className="text-text">{block.data.answers?.[q.key] ?? "—"}</span>
          </div>
        ))}
      </div>
    );
  }
  return (
    <motion.form
      {...fade}
      className="space-y-3 rounded-[12px] border border-warning/30 bg-warning/[0.05] px-4 py-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (ctx.taskId) resume.mutate({ taskId: ctx.taskId, value: answers });
      }}
    >
      <div className="text-[12px] font-medium uppercase tracking-wider text-warning">{t("needsInfo")}</div>
      {block.data.questions.map((q) => (
        <label key={q.key} className="block space-y-1.5">
          <span className="text-[13.5px] text-text">{q.question}</span>
          <Input value={answers[q.key] ?? ""} onChange={(e) => setAnswers((a) => ({ ...a, [q.key]: e.target.value }))} autoFocus />
        </label>
      ))}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" size="sm" disabled={resume.isPending}>{t("continue")}</Button>
      </div>
    </motion.form>
  );
}

// --- context sources (ORBIT transparency) ---------------------------------------------------------

function ContextBlock({ block }: { block: Block<{ project: string | null; reference_id: string; items: (ContextSource & { ref_id: string })[]; warnings: string[]; excluded_count: number; max_classification: number }> }) {
  const [open, setOpen] = useState(false);
  const pin = useComposer((s) => s.pin);
  const exclude = useComposer((s) => s.exclude);
  const setDraft = useComposer((s) => s.setDraft);
  const t = useT(M);
  const { items, warnings, excluded_count } = block.data;
  return (
    <div className="rounded-[12px] border border-border bg-surface/60">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-[12.5px] text-muted">
        <Orbit className="size-3.5 shrink-0 text-accent" />
        <span className="shrink-0 whitespace-nowrap">{t("usingContext")}</span>
        <span className="min-w-0 truncate text-left text-subtle">· {items.slice(0, 3).map((i) => i.title).join(", ")}{items.length > 3 ? ` +${items.length - 3}` : ""}</span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          <ClassificationBadge level={block.data.max_classification} />
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        </span>
      </button>
      {warnings.length ? (
        <div className="mx-3 mb-2 flex items-start gap-2 rounded-[8px] bg-warning/[0.08] px-2.5 py-1.5 text-[12px] text-warning">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {warnings.join(" ")}
        </div>
      ) : null}
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
            <ul className="divide-y divide-border border-t border-border">
              {items.map((item) => (
                <li key={`${item.citation}-${item.ref_id}`} className="group px-3 py-2">
                  <div className="flex items-center gap-2 text-[13px]">
                    <span className="rounded bg-surface-3 px-1 font-mono text-[10.5px] text-subtle">{item.citation}</span>
                    <span className="truncate font-medium text-text">{item.title}</span>
                    {item.flagged ? <Badge tone="warning" title={t("flaggedHint")}>{t("flagged")}</Badge> : null}
                    <ClassificationBadge level={item.classification} />
                    <span className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      {item.uri ? (
                        <a href={item.uri} target="_blank" rel="noreferrer" className="rounded p-1 text-subtle hover:text-text" aria-label={t("viewInOrbit")}><ExternalLink className="size-3.5" /></a>
                      ) : null}
                      <button onClick={() => { exclude(item.ref_id); toast(t("sourceExcluded")); }} className="rounded p-1 text-subtle hover:text-text" aria-label={t("removeFromContext")}><X className="size-3.5" /></button>
                    </span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11.5px] text-subtle">
                    {item.type ? <span>{item.type}</span> : null}
                    {item.project ? <span>{item.project}</span> : null}
                    <span>{item.source}</span>
                    {item.updated ? <span>{t("updatedAgo", { when: timeAgo(item.updated) })}</span> : null}
                    {item.relevance !== null && item.relevance !== undefined ? <span>{t("relevance", { pct: Math.round(item.relevance * 100) })}</span> : null}
                  </div>
                  {item.excerpt ? <p className="mt-1 line-clamp-2 text-[12px] text-muted">{item.excerpt}</p> : null}
                </li>
              ))}
            </ul>
            <div className="flex items-center gap-2 border-t border-border px-3 py-2 text-[12px] text-subtle">
              {excluded_count ? <span>{t("excludedByGovernance", { n: excluded_count })}</span> : null}
              <span className="ml-auto flex gap-1">
                <Button variant="ghost" size="sm" onClick={() => { pin({ reference_id: block.data.reference_id, label: t("previousContext"), count: items.length }); toast(t("contextPinned")); }}>
                  <Pin /> {t("reuse")}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => { setDraft(t("refreshPrompt")); document.getElementById("nova-composer")?.focus(); }}>
                  {t("refresh")}
                </Button>
              </span>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

// --- artifact -------------------------------------------------------------------------------------

function ArtifactBlock({ block, ctx }: { block: Block<{ artifact_id: string; title: string; type_name: string; version: number; created: boolean; changed_titles: string[]; summary: string; status: string; classification: number }>; ctx: BlockContext }) {
  const d = block.data;
  const t = useT(M);
  const lang = useLang();
  const { data: types } = useArtifactTypes();
  const def = types?.find((x) => x.name === d.type_name);
  const changed = d.changed_titles.map((title) => {
    const section = def?.sections.find((s) => s.title === title);
    return section ? sectionTitle(def, section, lang) : title;
  });
  return (
    <motion.button
      {...fade}
      onClick={() => ctx.onOpenArtifact(d.artifact_id)}
      className="flex w-full items-center gap-3 rounded-[12px] border border-border bg-surface px-4 py-3 text-left transition-colors hover:border-accent/40"
    >
      <span className="flex size-9 items-center justify-center rounded-[10px] bg-accent-soft text-accent">
        <FileText className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-[14px] font-medium">{d.title}</span>
          <Badge>v{d.version}</Badge>
          {d.status === "proposed" ? <Badge tone="warning">{t("awaitingApproval")}</Badge> : null}
          <ClassificationBadge level={d.classification} />
        </span>
        <span className="block truncate text-[12.5px] text-subtle">
          {typeName(def, lang, d.type_name)} · {d.created ? t("created") : t("updatedSections", { titles: changed.join(", ") })}
        </span>
      </span>
      <ChevronRight className="size-4 text-subtle" />
    </motion.button>
  );
}

// --- decision (approval) --------------------------------------------------------------------------

// Each approval opens its dialog automatically once per page load, never again after being dismissed.
const autoOpened = new Set<string>();

function DecisionBlock({ block, ctx }: { block: Block<ApprovalData>; ctx: BlockContext }) {
  const resume = useResume();
  const t = useT(M);
  const lang = useLang();
  const pending = block.data.status === "pending" && ctx.waiting;
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (pending && block.data.action !== "confirm_workflow" && !autoOpened.has(block.data.id)) {
      autoOpened.add(block.data.id);
      setOpen(true);
    }
  }, [pending, block.data.id, block.data.action]);
  return (
    <motion.div {...fade} className={cn("rounded-[14px] border px-4 py-3", pending ? "border-accent/35 bg-accent-soft/50" : "border-border bg-surface")}>
      <div className="text-[13.5px] font-medium">{block.data.title}</div>
      <p className="mt-0.5 text-[13px] text-muted">{block.data.description}</p>
      {pending ? (
        <div className="mt-2.5 flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>{t("reviewChanges")}</Button>
          {block.data.artifact_id ? (
            <Button variant="ghost" size="sm" onClick={() => ctx.onOpenArtifact(block.data.artifact_id!)}>{t("openDocument")}</Button>
          ) : null}
          <Button variant="ghost" size="sm" onClick={() => ctx.taskId && resume.mutate({ taskId: ctx.taskId, value: { action: "reject" } })}>{t("reject")}</Button>
          <Button variant="primary" size="sm" onClick={() => ctx.taskId && resume.mutate({ taskId: ctx.taskId, value: { action: "approve" } })}>{t("approve")}</Button>
        </div>
      ) : (
        <Badge className="mt-2" tone={block.data.status === "approved" ? "success" : "neutral"}>{statusLabel(block.data.status, lang)}</Badge>
      )}
      {pending ? <ApprovalDialog approval={block.data} taskId={ctx.taskId} open={open} onOpenChange={setOpen} /> : null}
    </motion.div>
  );
}

// --- notices --------------------------------------------------------------------------------------

function useActions(ctx: BlockContext) {
  const t = useT(M);
  return async (action: Action) => {
    if (action.action === "retry" && ctx.taskId && ctx.taskStatus === "failed") {
      await api.post(`/executions/${ctx.taskId}/retry`);
      toast(t("retrying"));
    } else if (action.action === "retry" && ctx.requestText && ctx.resend) {
      // The task completed despite a non-fatal problem (e.g. ORBIT unavailable): ask again.
      await ctx.resend(ctx.requestText);
    } else if (action.action === "link_orbit") window.location.href = "/settings#orbit";
    else if (action.action === "request_access" && ctx.projectOrbitUrl) window.open(ctx.projectOrbitUrl, "_blank");
    else if (action.action === "request_access") toast(t("askOwner"));
    else document.getElementById("nova-composer")?.focus();
  };
}

function NoticeBlock({ block, ctx }: { block: Block<{ title: string; message: string; actions: Action[] }>; ctx: BlockContext }) {
  const run = useActions(ctx);
  const lang = useLang();
  if (block.type === "error") {
    return (
      <ErrorNotice
        title={systemLabel(block.data.title, lang)}
        message={block.data.message}
        actions={block.data.actions.map((a) => (
          <Button key={a.action} size="sm" variant="secondary" onClick={() => void run(a)}>{systemLabel(a.label, lang)}</Button>
        ))}
      />
    );
  }
  return (
    <div className="rounded-[12px] border border-warning/25 bg-warning/[0.05] px-4 py-3">
      <div className="flex items-center gap-2 text-[13.5px] font-medium">
        <AlertTriangle className="size-4 text-warning" /> {systemLabel(block.data.title, lang)}
      </div>
      <p className="mt-0.5 text-[13px] text-muted">{block.data.message}</p>
      {block.data.actions.length ? (
        <div className="mt-2 flex gap-2">
          {block.data.actions.map((a) => (
            <Button key={a.action} size="sm" variant="ghost" onClick={() => void run(a)}>{systemLabel(a.label, lang)}</Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// --- citations (sources of an answer / provenance) ------------------------------------------------

function CitationsBlock({ block, ctx }: { block: Block<{ sources: ContextSource[]; provenance?: boolean; artifact_id?: string }>; ctx: BlockContext }) {
  const t = useT(M);
  if (!block.data.sources.length) return null;
  return (
    <div className="rounded-[12px] border border-border bg-surface/60 px-3 py-2.5">
      <div className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wider text-subtle">
        {block.data.provenance ? t("recordedSources") : t("sources")}
      </div>
      <ul className="space-y-1.5">
        {block.data.sources.map((s) => (
          <li key={`${s.label}-${s.reference_id}`} className="text-[13px]">
            <div className="flex items-center gap-2">
              <span className="rounded bg-surface-3 px-1 font-mono text-[10.5px] text-subtle">{s.label}</span>
              {s.uri ? (
                <a href={s.uri} target="_blank" rel="noreferrer" className="truncate text-text hover:underline">{s.title}</a>
              ) : (
                <span className="truncate text-text">{s.title}</span>
              )}
              <ClassificationBadge level={s.classification} />
              <span className="ml-auto text-[11.5px] text-subtle">{[s.type, s.project, s.updated ? timeAgo(s.updated) : null].filter(Boolean).join(" · ")}</span>
            </div>
            {s.excerpt ? <p className="mt-0.5 line-clamp-2 pl-7 text-[12px] text-muted">{t("excerpt", { text: s.excerpt })}</p> : null}
          </li>
        ))}
      </ul>
      {block.data.artifact_id ? (
        <button onClick={() => ctx.onOpenArtifact(block.data.artifact_id!)} className="mt-2 text-[12px] text-accent hover:underline">{t("openArtifact")}</button>
      ) : null}
    </div>
  );
}

// --- tool / generic -------------------------------------------------------------------------------

function ToolBlock({ block }: { block: Block<{ tool: string; status: string; summary?: string; error?: string; duration_ms?: number }> }) {
  return (
    <div className="flex items-center gap-2 px-1 text-[12.5px] text-subtle">
      <Wrench className="size-3.5" /> {block.data.tool.replaceAll("_", " ")}
      <StepIcon status={block.data.status} />
      {block.data.error ? <span className="text-danger">{block.data.error}</span> : null}
      {block.data.duration_ms ? <span>· {block.data.duration_ms} ms</span> : null}
    </div>
  );
}

function TableBlock({ block }: { block: Block<{ columns: string[]; rows: string[][] }> }) {
  return (
    <div className="overflow-x-auto rounded-[12px] border border-border">
      <table className="w-full text-[13px]">
        <thead className="bg-surface-2 text-left text-subtle">
          <tr>{block.data.columns.map((c) => <th key={c} className="px-3 py-2 font-medium">{c}</th>)}</tr>
        </thead>
        <tbody>
          {block.data.rows.map((row, i) => (
            <tr key={i} className="border-t border-border">{row.map((cell, j) => <td key={j} className="px-3 py-2 text-muted">{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChecklistBlock({ block }: { block: Block<{ title?: string; items: { text: string; done: boolean }[] }> }) {
  return (
    <div className="rounded-[12px] border border-border bg-surface px-4 py-3">
      {block.data.title ? <div className="mb-1.5 text-[13px] font-medium">{block.data.title}</div> : null}
      {block.data.items.map((item) => (
        <div key={item.text} className="flex items-center gap-2 text-[13px] text-muted">
          <StepIcon status={item.done ? "completed" : "pending"} /> {item.text}
        </div>
      ))}
    </div>
  );
}

function TaskBlock({ block }: { block: Block<{ task_id: string; objective: string; status: string }> }) {
  return (
    <Link href={`/work?task=${block.data.task_id}`} className="flex items-center gap-2 rounded-[12px] border border-border bg-surface px-4 py-2.5 text-[13px] hover:border-accent/40">
      <StepIcon status={block.data.status} /> {block.data.objective}
    </Link>
  );
}

export function BlockView({ block, ctx, live }: { block: Block; ctx: BlockContext; live: boolean }) {
  switch (block.type) {
    case "text":
      return <TextBlockView block={block as never} />;
    case "progress":
      return <ProgressBlock block={block as never} live={live} ctx={ctx} />;
    case "plan":
      return <PlanBlock block={block as never} ctx={ctx} />;
    case "workflow":
      return <WorkflowBlock block={block as never} ctx={ctx} />;
    case "question":
      return <QuestionBlock block={block as never} ctx={ctx} />;
    case "context_sources":
      return <ContextBlock block={block as never} />;
    case "artifact":
      return <ArtifactBlock block={block as never} ctx={ctx} />;
    case "decision":
      return <DecisionBlock block={block as never} ctx={ctx} />;
    case "warning":
    case "error":
      return <NoticeBlock block={block as never} ctx={ctx} />;
    case "citations":
      return <CitationsBlock block={block as never} ctx={ctx} />;
    case "tool_execution":
      return <ToolBlock block={block as never} />;
    case "table":
      return <TableBlock block={block as never} />;
    case "checklist":
      return <ChecklistBlock block={block as never} />;
    case "task":
      return <TaskBlock block={block as never} />;
    default:
      return null;
  }
}
