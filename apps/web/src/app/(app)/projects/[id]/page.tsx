"use client";

import { Badge, Button, cn, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowRight, Check, ChevronRight, ExternalLink, FileText, Lightbulb, Orbit } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import { Composer } from "@/components/composer/composer";
import { ClassificationBadge, ErrorNotice } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { useArtifacts, useProject, useSkill, useTask, useTasks } from "@/lib/api/hooks";
import type { ChangeEvent, TaskStep, WorkItem } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { useComposer } from "@/stores/ui";

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section className={cn("rounded-[20px] border border-border bg-surface p-5 shadow-panel", className)}>{children}</section>;
}

function Stepper({ steps }: { steps: TaskStep[] }) {
  const currentIndex = steps.findIndex((s) => s.status !== "completed" && s.status !== "skipped");
  return (
    <ol className="flex items-start">
      {steps.map((step, i) => {
        const done = step.status === "completed" || step.status === "skipped";
        const current = i === currentIndex;
        return (
          <li key={step.id} className="flex min-w-0 flex-1 flex-col items-center text-center">
            <div className="flex w-full items-center">
              <span className={cn("h-0.5 flex-1", i === 0 ? "invisible" : done || current ? "bg-accent/60" : "bg-border")} />
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border-2",
                  done ? "border-success bg-success text-white" : current ? "border-accent bg-accent-soft" : "border-border bg-surface",
                )}
              >
                {done ? <Check className="size-3.5" /> : current ? <span className="size-2 rounded-full bg-accent" /> : null}
              </span>
              <span className={cn("h-0.5 flex-1", i === steps.length - 1 ? "invisible" : done ? "bg-accent/60" : "bg-border")} />
            </div>
            <span className={cn("mt-2 line-clamp-2 px-1 text-[12px]", current ? "font-medium text-accent" : done ? "text-text" : "text-subtle")}>{step.title}</span>
          </li>
        );
      })}
    </ol>
  );
}

function CurrentWorkflow({ task }: { task: WorkItem }) {
  const { data: detail } = useTask(task.id);
  const steps = detail?.steps ?? [];
  const pct = task.status === "completed" ? 100 : task.progress_total ? Math.round((task.progress_done / task.progress_total) * 100) : 0;
  const current = steps.find((s) => s.status !== "completed" && s.status !== "skipped") ?? steps.at(-1);
  const state = task.status === "completed" ? "Completed" : task.status === "waiting_user" ? "Waiting for you" : task.status === "failed" ? "Failed" : "In progress";
  return (
    <Card>
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[17px] font-semibold tracking-tight">{task.skills[0] ?? "Current work"}</h2>
          <p className="mt-0.5 line-clamp-1 text-[13px] text-muted">{task.objective}</p>
        </div>
        <Badge className="shrink-0 whitespace-nowrap" tone={task.status === "completed" ? "success" : task.status === "failed" ? "danger" : "accent"}>
          {state} · {pct}%
        </Badge>
      </div>
      {!detail ? <Skeleton className="h-10" /> : steps.length ? <Stepper steps={steps} /> : null}
      {current ? (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-[16px] border border-border bg-background/60 p-4">
          <div className="min-w-0">
            <div className="text-[12px] text-subtle">{task.status === "completed" ? "Last stage" : "Current stage"}</div>
            <div className="mt-0.5 text-[15px] font-semibold">{current.title}</div>
            {current.detail ? <div className="mt-0.5 text-[12.5px] text-muted">{current.detail}</div> : null}
            {task.progress_total ? <div className="mt-3 w-56 max-w-full">
              <div className="mb-1 text-[11.5px] text-subtle">
                {task.progress_done} / {task.progress_total} steps
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                <motion.div className="h-full rounded-full bg-gradient-to-r from-[#f9a8bf] to-accent" initial={false} animate={{ width: `${Math.max(pct, 4)}%` }} />
              </div>
            </div> : null}
          </div>
          <Button variant="secondary" className="rounded-full" asChild>
            <Link href={task.conversation_id ? `/c/${task.conversation_id}` : `/work?task=${task.id}`}>
              View details <ArrowRight />
            </Link>
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

function WhatsNext({ task, projectId }: { task: WorkItem | undefined; projectId: string }) {
  const { data: detail } = useTask(task?.id ?? null);
  const lastSkill = detail?.steps?.at(-1)?.skill_id ?? null;
  const { data: skill } = useSkill(lastSkill);
  const composer = useComposer();
  const pending = (detail?.steps ?? []).filter((s) => s.status === "pending" || s.status === "running" || s.status === "waiting_user");
  const suggestions = (skill?.composes_with ?? []).slice(0, 4);
  const start = (text: string) => {
    composer.setProject(projectId);
    composer.setDraft(text);
    document.getElementById("nova-composer")?.focus();
  };
  return (
    <Card>
      <h2 className="mb-3 text-[15px] font-semibold">What&apos;s next</h2>
      <ul className="space-y-2">
        {pending.map((s) => (
          <li key={s.id} className="flex items-center gap-2.5 text-[13.5px]">
            <span className="size-4 shrink-0 rounded-[5px] border border-border-strong" />
            <span className="flex-1">{s.title}</span>
            <span className="text-[11.5px] text-subtle">{s.status === "waiting_user" ? "needs you" : "queued"}</span>
          </li>
        ))}
        {suggestions.map((id) => (
          <li key={id}>
            <button onClick={() => start(`/${id} `)} className="group flex w-full items-center gap-2.5 text-left text-[13.5px]">
              <span className="size-4 shrink-0 rounded-[5px] border border-border-strong group-hover:border-accent" />
              <span className="flex-1 capitalize group-hover:text-accent">{id.replaceAll("-", " ")}</span>
              <ChevronRight className="size-3.5 text-subtle" />
            </button>
          </li>
        ))}
        {!pending.length && !suggestions.length ? <li className="text-[13px] text-subtle">Ask NOVA to start something below.</li> : null}
      </ul>
    </Card>
  );
}

function Insights({ decisions, orbitUrl }: { decisions: ChangeEvent[]; orbitUrl: string | null }) {
  const [first, ...rest] = decisions;
  return (
    <Card>
      <h2 className="mb-4 flex items-center gap-2 text-[15px] font-semibold">
        <Lightbulb className="size-4 text-accent" /> Key insights so far
        <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[11px] font-semibold leading-5 text-accent-fg">{decisions.length}</span>
      </h2>
      {first ? (
        <>
          <div className="rounded-[16px] border border-border bg-background/60 p-4">
            <p className="text-[16px] font-semibold leading-snug">{first.title.replace(/^[^:]{0,40}:\s*/, "")}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-subtle">
              <Badge tone={first.type === "memory.validated" ? "success" : "neutral"}>{first.type === "memory.validated" ? "Validated in ORBIT" : first.type_label}</Badge>
              <ClassificationBadge level={first.classification} />
              <span>{timeAgo(first.created_at)}</span>
            </div>
            {first.summary ? <p className="mt-2 line-clamp-2 text-[12.5px] text-muted">{first.summary}</p> : null}
            {orbitUrl ? (
              <a href={`${orbitUrl}/memory`} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">
                View evidence <ArrowRight className="size-3.5" />
              </a>
            ) : null}
          </div>
          <ul className="mt-2 divide-y divide-border">
            {rest.slice(0, 4).map((d) => (
              <li key={d.id} className="flex items-center gap-2 py-2 text-[13px]">
                <span className="min-w-0 flex-1 truncate">{d.title.replace(/^[^:]{0,40}:\s*/, "")}</span>
                <span className="shrink-0 text-[11.5px] text-subtle">{timeAgo(d.created_at)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-[13px] text-subtle">Decisions validated in ORBIT for this project appear here.</p>
      )}
    </Card>
  );
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const { data: project, isLoading } = useProject(id);
  const { data: active } = useTasks("active", id);
  const { data: done } = useTasks("completed", id);
  const { data: artifacts } = useArtifacts({ project_id: id });
  const setProject = useComposer((s) => s.setProject);
  useEffect(() => setProject(id), [id, setProject]);
  const context = useQuery({
    queryKey: ["context-project", id],
    queryFn: () => api.get<{ decisions: ChangeEvent[]; documents: ChangeEvent[] }>(`/context/projects/${id}`),
    enabled: !!project?.orbit_slug,
    retry: false,
  });

  if (isLoading || !project) {
    return (
      <div className="mx-auto max-w-[1120px] p-8">
        <Skeleton className="h-10 w-1/3" />
        <Skeleton className="mt-6 h-64" />
      </div>
    );
  }
  // Prefer a multi-step workflow over a single answer for the stepper card.
  const workflows = [...(active ?? []), ...(done ?? [])];
  const latest = workflows.find((t) => t.progress_total > 1) ?? workflows[0];

  return (
    <div className="relative min-h-screen">
      <div className="mx-auto w-full max-w-[1120px] px-5 pb-36 pt-6 md:px-8">
        <nav className="flex items-center gap-1.5 text-[12.5px] text-subtle">
          <Link href="/projects" className="hover:text-text">Projects</Link>
          <ChevronRight className="size-3" />
          <span className="text-muted">{project.name}</span>
        </nav>
        <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-[28px] font-semibold tracking-tight">{project.name}</h1>
            <p className="mt-1 max-w-2xl text-[14px] text-muted">{project.description || "No description yet."}</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex -space-x-2">
              {project.people.slice(0, 4).map((p) => (
                <span key={p.name} title={`${p.name} · ${p.role}`} className="flex size-8 items-center justify-center rounded-full border-2 border-background bg-surface-3 text-[12px] font-semibold">
                  {p.name.slice(0, 1)}
                </span>
              ))}
            </div>
            {project.orbit_url ? (
              <Button variant="secondary" className="rounded-full" asChild>
                <a href={project.orbit_url} target="_blank" rel="noreferrer"><Orbit /> Open in ORBIT <ExternalLink /></a>
              </Button>
            ) : null}
          </div>
        </header>

        {project.context_error ? (
          <div className="mt-4"><ErrorNotice title="ORBIT context is unavailable for this project" message={project.context_error.message} /></div>
        ) : null}

        <Tabs defaultValue="overview" className="mt-6">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="insights">Insights</TabsTrigger>
            <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
            <TabsTrigger value="context">Context</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="mt-5">
            <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
              <div className="space-y-5">
                {latest ? <CurrentWorkflow task={latest} /> : (
                  <Card><p className="text-[13.5px] text-muted">No work yet in {project.name}. Tell NOVA what you need below.</p></Card>
                )}
                <Insights decisions={project.decisions} orbitUrl={project.orbit_url} />
              </div>
              <div className="space-y-5">
                <WhatsNext task={latest} projectId={id} />
                <Card>
                  <h2 className="mb-3 text-[15px] font-semibold">At a glance</h2>
                  <dl className="grid grid-cols-3 gap-3 text-center">
                    {[
                      ["Decisions", project.decisions.length],
                      ["Artifacts", artifacts?.length ?? 0],
                      ["Active", active?.length ?? 0],
                    ].map(([label, value]) => (
                      <div key={label as string} className="rounded-[14px] bg-background/60 py-3">
                        <dt className="text-[11.5px] text-subtle">{label}</dt>
                        <dd className="text-[22px] font-semibold">{value}</dd>
                      </div>
                    ))}
                  </dl>
                </Card>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="insights" className="mt-5 grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-2">
            <Insights decisions={project.decisions} orbitUrl={project.orbit_url} />
            <Card>
              <h2 className="mb-3 text-[15px] font-semibold">Recent activity</h2>
              <ActivityFeed filters={{ project_id: id }} compact />
            </Card>
          </TabsContent>

          <TabsContent value="artifacts" className="mt-5">
            <Card className="p-2">
              {artifacts?.length ? (
                <ul className="divide-y divide-border">
                  {artifacts.map((a) => (
                    <li key={a.id}>
                      <Link href={`/artifacts/${a.id}`} className="flex items-center gap-3 px-3 py-3 hover:bg-surface-2">
                        <span className="flex size-9 items-center justify-center rounded-[10px] bg-accent-soft text-accent"><FileText className="size-4" /></span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-medium">{a.title}</span>
                          <span className="text-[12px] text-subtle">{a.type_name} · v{a.version} · {timeAgo(a.updated_at)}</span>
                        </span>
                        <ClassificationBadge level={a.classification} />
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="p-4 text-[13.5px] text-subtle">Your work with NOVA will appear here.</p>
              )}
            </Card>
          </TabsContent>

          <TabsContent value="context" className="mt-5 grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-2">
            <Card>
              <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold"><Orbit className="size-4 text-accent" /> Decisions in ORBIT</h2>
              {context.data?.decisions.length ? context.data.decisions.map((d) => (
                <div key={d.id} className="border-b border-border py-2 text-[13.5px] last:border-0">{d.title}<div className="text-[12px] text-subtle">{d.type_label} · {timeAgo(d.created_at)}</div></div>
              )) : <p className="text-[13px] text-subtle">{project.orbit_slug ? "No recent decision changes." : "This project is not linked to ORBIT."}</p>}
            </Card>
            <Card>
              <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold"><FileText className="size-4 text-accent" /> Sources</h2>
              {context.data?.documents.length ? context.data.documents.map((d) => (
                <div key={d.id} className="border-b border-border py-2 text-[13.5px] last:border-0">{d.title}<div className="text-[12px] text-subtle">{d.type_label} · {timeAgo(d.created_at)}</div></div>
              )) : <p className="text-[13px] text-subtle">No recent document changes.</p>}
              <Link href="/context" className="mt-3 inline-block text-[12.5px] text-accent hover:underline">Open ORBIT Context</Link>
            </Card>
          </TabsContent>
        </Tabs>
      </div>

      <div className="fixed inset-x-0 bottom-16 z-30 px-4 md:bottom-6 md:left-[224px]">
        <div className="mx-auto max-w-[760px]">
          <Composer variant="pill" placeholder={`Ask NOVA about ${project.name}…`} />
        </div>
      </div>
    </div>
  );
}
