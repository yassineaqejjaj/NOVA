"use client";

import { Badge, Button, cn, Skeleton, Tabs, TabsList, TabsTrigger } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Check, CircleDashed, FileText, FlaskConical, ListTodo, Loader2, X, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { EmptyState, Page, PageHeader } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { useProjects, useTask, useTasks } from "@/lib/api/hooks";
import type { WorkItem } from "@/lib/api/types";
import { duration, timeAgo } from "@/lib/format";

const STATUS: Record<string, { label: string; tone: "accent" | "warning" | "success" | "danger" | "neutral" }> = {
  queued: { label: "Queued", tone: "neutral" },
  scheduled: { label: "Scheduled", tone: "neutral" },
  running: { label: "Running", tone: "accent" },
  waiting_user: { label: "Waiting for you", tone: "warning" },
  completed: { label: "Completed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

function StepStatus({ status }: { status: string }) {
  if (status === "completed") return <Check className="size-3.5 text-success" />;
  if (status === "running") return <Loader2 className="size-3.5 animate-spin text-accent" />;
  if (status === "failed") return <XCircle className="size-3.5 text-danger" />;
  if (status === "waiting_user") return <CircleDashed className="size-3.5 text-warning" />;
  return <span className="mx-[3px] block size-2 rounded-full border border-subtle" />;
}

function WorkRow({ item, projectName, selected, onSelect }: { item: WorkItem; projectName?: string; selected: boolean; onSelect: () => void }) {
  const s = STATUS[item.status] ?? STATUS.queued!;
  return (
    <button onClick={onSelect} className={cn("flex w-full items-center gap-4 border-b border-border px-4 py-3 text-left transition-colors hover:bg-surface", selected && "bg-surface")}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] text-text">{item.objective}</div>
        <div className="mt-0.5 truncate text-[12px] text-subtle">
          {[projectName, item.skills.join(" → ") || null, item.scheduled_for ? `scheduled for ${new Date(item.scheduled_for).toLocaleString()}` : timeAgo(item.created_at)].filter(Boolean).join(" · ")}
        </div>
      </div>
      {item.progress_total ? (
        <div className="hidden w-28 sm:block">
          <div className="h-1 overflow-hidden rounded-full bg-surface-3">
            <motion.div className="h-full bg-accent" initial={false} animate={{ width: `${(item.progress_done / item.progress_total) * 100}%` }} transition={{ duration: 0.25 }} />
          </div>
          <div className="mt-1 text-right text-[11px] text-subtle">{item.progress_done} / {item.progress_total} steps</div>
        </div>
      ) : null}
      <Badge tone={s.tone}>{s.label}</Badge>
    </button>
  );
}

function WorkDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: task } = useTask(id);
  const client = useQueryClient();
  const retry = useMutation({
    mutationFn: () => api.post(`/executions/${id}/retry`),
    onSuccess: () => { toast("Retrying from the last completed step."); void client.invalidateQueries({ queryKey: ["tasks"] }); },
  });
  const cancel = useMutation({
    mutationFn: () => api.post(`/executions/${id}/cancel`),
    onSuccess: () => { toast("Cancelled."); void client.invalidateQueries({ queryKey: ["tasks"] }); },
  });
  if (!task) return <div className="p-5"><Skeleton className="h-32 w-full" /></div>;
  const s = STATUS[task.status] ?? STATUS.queued!;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b border-border px-5 py-4">
        <div className="min-w-0 flex-1">
          <Badge tone={s.tone}>{s.label}</Badge>
          <h2 className="mt-1.5 text-[15px] font-semibold leading-snug">{task.objective}</h2>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close"><X /></Button>
      </div>
      <div className="flex-1 space-y-6 overflow-y-auto px-5 py-4 text-[13px]">
        <section>
          <h3 className="mb-2 text-[11.5px] font-medium uppercase tracking-wider text-subtle">Plan</h3>
          {task.steps?.length ? (
            <ol className="space-y-1.5">
              {task.steps.map((step) => (
                <li key={step.id} className="flex items-start gap-2.5">
                  <span className="mt-0.5"><StepStatus status={step.status} /></span>
                  <div className="min-w-0">
                    <div className="text-text">{step.title}</div>
                    <div className="text-[11.5px] text-subtle">{[step.skill_name && `${step.skill_name} v${step.skill_version}`, step.detail].filter(Boolean).join(" · ")}</div>
                  </div>
                </li>
              ))}
            </ol>
          ) : <p className="text-subtle">{task.status === "scheduled" ? "The plan is created when the work starts." : "No plan yet."}</p>}
        </section>
        {task.artifacts?.length ? (
          <section>
            <h3 className="mb-2 text-[11.5px] font-medium uppercase tracking-wider text-subtle">Outputs</h3>
            {task.artifacts.map((a) => (
              <Link key={a.id} href={`/artifacts/${a.id}`} className="flex items-center gap-2 rounded-[10px] px-2 py-1.5 hover:bg-surface-2">
                <FileText className="size-3.5 text-accent" /> <span className="truncate">{a.title}</span> <Badge>v{a.version}</Badge>
              </Link>
            ))}
          </section>
        ) : null}
        <section className="grid grid-cols-2 gap-x-4 gap-y-2">
          <Meta label="Created" value={new Date(task.created_at).toLocaleString()} />
          <Meta label="Duration" value={duration(task.duration_seconds)} />
          <Meta label="Model" value={task.model ?? "—"} />
          <Meta label="Tokens" value={task.usage?.input_tokens != null ? `${task.usage.input_tokens} in · ${task.usage.output_tokens ?? 0} out` : "—"} />
          <Meta label="Trace ID" value={task.trace_id ?? "—"} mono />
          <Meta
            label="FORGE evaluation"
            value={
              task.evaluation ? (
                <a href={task.evaluation.url ?? "#"} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                  <FlaskConical className="size-3" />
                  {task.evaluation.composite_score != null ? `${Math.round(task.evaluation.composite_score)} / 100` : task.evaluation.status ?? "queued"}
                  {task.evaluation.passed != null ? (task.evaluation.passed ? " · passed" : " · not passed") : ""}
                </a>
              ) : "Not evaluated"
            }
          />
        </section>
        {task.error ? <p className="rounded-[10px] bg-danger/[0.06] px-3 py-2 text-muted">{task.error}</p> : null}
      </div>
      <div className="flex gap-2 border-t border-border px-5 py-3">
        {task.conversation_id ? <Button variant="secondary" size="sm" asChild><Link href={`/c/${task.conversation_id}`}>Open conversation</Link></Button> : null}
        {task.status === "failed" ? <Button size="sm" variant="primary" onClick={() => retry.mutate()} disabled={retry.isPending}>Retry</Button> : null}
        {["queued", "running", "waiting_user", "scheduled"].includes(task.status) ? <Button size="sm" variant="ghost" onClick={() => cancel.mutate()}>Cancel</Button> : null}
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

const EMPTY: Record<string, string> = {
  active: "NOVA has no active tasks.",
  scheduled: "Nothing scheduled.",
  completed: "Completed work will appear here.",
  failed: "No failed work. Good.",
};

function WorkPage() {
  const params = useSearchParams();
  const router = useRouter();
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
          <PageHeader title="Work" description="Everything NOVA is doing, has done, or will do for you." />
          <Tabs value={tab} onValueChange={(v) => { setTab(v); router.replace(`/work?tab=${v}`, { scroll: false }); }}>
            <TabsList>
              <TabsTrigger value="active">Active</TabsTrigger>
              <TabsTrigger value="scheduled">Scheduled</TabsTrigger>
              <TabsTrigger value="completed">Completed</TabsTrigger>
              <TabsTrigger value="failed">Failed</TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="mt-4 overflow-hidden rounded-[14px] border border-border">
            {isLoading ? <div className="space-y-2 p-4"><Skeleton className="h-10" /><Skeleton className="h-10" /></div> : null}
            {items?.map((item) => (
              <WorkRow key={item.id} item={item} projectName={item.project_id ? names.get(item.project_id) : undefined} selected={selected === item.id} onSelect={() => select(item.id)} />
            ))}
          </div>
          {items && items.length === 0 ? <div className="mt-4"><EmptyState icon={<ListTodo />} title={EMPTY[tab] ?? ""} description={tab === "active" ? "Ask NOVA for something on Today." : undefined} /></div> : null}
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
